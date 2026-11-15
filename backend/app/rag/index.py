"""Builds and queries the two indexes: ChromaDB (dense) and BM25 (lexical)."""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass

import bm25s
import chromadb
import numpy as np

from ..config import Settings
from ..ingest.documents import Document
from ..ingest.pdf import chunk_post
from ..text import tokenize
from .embeddings import Embedder

log = logging.getLogger(__name__)


@dataclass
class Window:
    """The text actually embedded. Usually 1:1 with a Document; long Telegram posts get several windows."""

    id: str
    doc: Document
    text: str


def windows_for(doc: Document, max_chars: int) -> list[Window]:
    if doc.source_type == "weblog" or len(doc.text) <= max_chars:
        parts = [doc.text]
    else:
        # A post is still the retrieval unit; we only split so the embedder (512 tokens) sees all of it.
        parts = [t for _, t in chunk_post([(0, p) for p in doc.text.split("\n") if p.strip()], max_chars, 200)]
    head = doc.header()
    return [Window(id=f"{doc.id}#w{i}", doc=doc, text=f"{head}\n{part}") for i, part in enumerate(parts)]


def date_int(date: str) -> int:
    digits = date[:10].replace("-", "")
    return int(digits) if digits.isdigit() and len(digits) == 8 else 0


def chroma_metadata(doc: Document) -> dict:
    return {
        "doc_id": doc.id,
        "source_type": doc.source_type,
        "source": doc.source,
        "date": doc.date[:10],
        "date_int": date_int(doc.date),
        "year": doc.year,
    }


class DenseIndex:
    def __init__(self, settings: Settings, embedder: Embedder):
        self.settings = settings
        self.embedder = embedder
        settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(settings.chroma_dir))
        self.collection = self.client.get_or_create_collection(
            settings.collection_name,
            metadata={"hnsw:space": "cosine", "embed_model": embedder.model_name},
            embedding_function=None,
        )
        indexed_with = (self.collection.metadata or {}).get("embed_model")
        if indexed_with and indexed_with != embedder.model_name:
            raise RuntimeError(
                f"Collection '{settings.collection_name}' was built with {indexed_with}, but EMBED_MODEL is "
                f"{embedder.model_name}. Re-run ingestion with --rebuild or set COLLECTION_NAME."
            )

    def reset(self) -> None:
        self.client.delete_collection(self.collection.name)
        self.__init__(self.settings, self.embedder)

    def count(self) -> int:
        return self.collection.count()

    def missing(self, windows: list[Window]) -> list[Window]:
        existing: set[str] = set()
        for i in range(0, len(windows), 5000):
            ids = [w.id for w in windows[i:i + 5000]]
            existing.update(self.collection.get(ids=ids, include=[])["ids"])
        return [w for w in windows if w.id not in existing]

    def add(self, windows: list[Window], vectors: np.ndarray) -> None:
        self.collection.upsert(
            ids=[w.id for w in windows],
            embeddings=vectors.tolist(),
            documents=[w.text for w in windows],
            metadatas=[chroma_metadata(w.doc) for w in windows],
        )

    def query(self, text: str, n: int, where: dict | None) -> list[tuple[str, float]]:
        """Returns (doc_id, cosine similarity) best-first, one entry per document."""
        if not self.count():
            return []
        res = self.collection.query(
            query_embeddings=[self.embedder.embed_query(text).tolist()],
            n_results=min(n * 2, self.count()),  # windows of the same post collapse below
            where=where,
            include=["metadatas", "distances"],
        )
        seen: dict[str, float] = {}
        for meta, dist in zip(res["metadatas"][0], res["distances"][0]):
            doc_id = meta["doc_id"]
            if doc_id not in seen:
                seen[doc_id] = 1.0 - float(dist)
        return list(seen.items())[:n]


class LexicalIndex:
    """BM25 over Persian-normalized, stopword-filtered tokens of each full document."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.retriever: bm25s.BM25 | None = None
        self.doc_ids: list[str] = []

    def build(self, docs: Iterable[Document]) -> None:
        docs = list(docs)
        self.doc_ids = [d.id for d in docs]
        tokens = [tokenize(f"{d.title} {d.text}", self.settings.stopwords_file) or ["∅"] for d in docs]
        self.retriever = bm25s.BM25()
        self.retriever.index(tokens, show_progress=False)
        self.settings.bm25_dir.mkdir(parents=True, exist_ok=True)
        self.retriever.save(str(self.settings.bm25_dir))
        (self.settings.bm25_dir / "doc_ids.json").write_text(json.dumps(self.doc_ids), encoding="utf-8")

    def load(self) -> bool:
        ids_file = self.settings.bm25_dir / "doc_ids.json"
        if not ids_file.exists():
            return False
        self.retriever = bm25s.BM25.load(str(self.settings.bm25_dir))
        self.doc_ids = json.loads(ids_file.read_text(encoding="utf-8"))
        return True

    def query(self, text: str, n: int, keep=lambda doc_id: True) -> list[tuple[str, float]]:
        if self.retriever is None or not self.doc_ids:
            return []
        q = tokenize(text, self.settings.stopwords_file)
        known = [t for t in q if t in self.retriever.vocab_dict]
        if not known:
            return []
        k = min(len(self.doc_ids), n * 10)  # over-fetch so metadata filters still leave n results
        idx, scores = self.retriever.retrieve([known], k=k, show_progress=False, return_as="tuple")
        out = []
        for i, s in zip(idx[0], scores[0]):
            if s <= 0:
                break
            doc_id = self.doc_ids[int(i)]
            if keep(doc_id):
                out.append((doc_id, float(s)))
                if len(out) == n:
                    break
        return out
