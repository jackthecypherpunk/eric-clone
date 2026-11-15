"""Hybrid retrieval: dense (Chroma) + lexical (BM25), fused with Reciprocal Rank Fusion, optionally reranked."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, replace

from ..config import Settings
from ..ingest.documents import Document
from .corpus import Corpus
from .embeddings import Embedder, Reranker
from .index import DenseIndex, LexicalIndex, date_int

log = logging.getLogger(__name__)


@dataclass
class Hit:
    doc: Document
    score: float
    dense_rank: int | None = None
    lexical_rank: int | None = None


@dataclass
class Filters:
    source_type: str | None = None  # "telegram" | "weblog" | None
    date_from: str | None = None  # YYYY or YYYY-MM-DD
    date_to: str | None = None

    def _bounds(self) -> tuple[int, int]:
        lo = date_int(_pad(self.date_from, "01-01")) if self.date_from else 0
        hi = date_int(_pad(self.date_to, "12-31")) if self.date_to else 0
        return lo, hi

    def chroma_where(self) -> dict | None:
        clauses: list[dict] = []
        if self.source_type in ("telegram", "weblog"):
            clauses.append({"source_type": self.source_type})
        lo, hi = self._bounds()
        if lo:
            clauses.append({"date_int": {"$gte": lo}})
        if hi:
            clauses.append({"date_int": {"$lte": hi}})
        if not clauses:
            return None
        return clauses[0] if len(clauses) == 1 else {"$and": clauses}

    def accepts(self, doc: Document) -> bool:
        if self.source_type in ("telegram", "weblog") and doc.source_type != self.source_type:
            return False
        lo, hi = self._bounds()
        d = date_int(doc.date)
        return not ((lo and d < lo) or (hi and d > hi))


def _pad(value: str, suffix: str) -> str:
    value = value.strip()
    if len(value) == 4:
        return f"{value}-{suffix}"
    if len(value) == 7:
        return f"{value}-{suffix[-2:]}"  # day 31 is fine: bounds are compared as YYYYMMDD integers
    return value


class Retriever:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.embedder = Embedder(settings.embed_model, settings.embed_device, settings.embed_batch_size)
        self.corpus = Corpus.load(settings.corpus_file)
        self.dense = DenseIndex(settings, self.embedder)
        self.lexical = LexicalIndex(settings)
        self.lexical.load()
        self.reranker = Reranker(settings.rerank_model, settings.embed_device) if settings.rerank_enabled else None
        self._lock = threading.Lock()  # torch CPU inference is not worth parallelizing per request

    def warm_up(self) -> None:
        if len(self.corpus):
            self.embedder.embed_query("warm up")
            if self.reranker:
                self.reranker.scores("warm up", ["warm up"])

    @property
    def ready(self) -> bool:
        return len(self.corpus) > 0 and self.dense.count() > 0

    def search(self, query: str, k: int = 8, filters: Filters | None = None) -> list[Hit]:
        filters = filters or Filters()
        if filters.source_type:
            return self._search_one(query, k, filters)
        # The weblog is ~2% of the corpus, so in a single ranking the Telegram posts always crowd
        # it out. Rank each source on its own and reserve a share of the slots for the weblog.
        weblog = self._search_one(query, k, replace(filters, source_type="weblog"))
        quota = min(len(weblog), max(1, round(k * self.settings.weblog_share)))
        telegram = self._search_one(query, k - quota, replace(filters, source_type="telegram"))
        return sorted(weblog[:quota] + telegram, key=lambda h: h.score, reverse=True)

    def _search_one(self, query: str, k: int, filters: Filters) -> list[Hit]:
        pool = self.settings.candidate_pool
        with self._lock:
            dense = self.dense.query(query, pool, filters.chroma_where())
        lexical = self.lexical.query(query, pool, keep=lambda i: (d := self.corpus.get(i)) is not None and filters.accepts(d))

        fused: dict[str, Hit] = {}
        rrf_k = self.settings.rrf_k
        for rank, (doc_id, _) in enumerate(dense):
            if doc := self.corpus.get(doc_id):
                hit = fused.setdefault(doc_id, Hit(doc=doc, score=0.0))
                hit.score += 1.0 / (rrf_k + rank + 1)
                hit.dense_rank = rank + 1
        for rank, (doc_id, _) in enumerate(lexical):
            if doc := self.corpus.get(doc_id):
                hit = fused.setdefault(doc_id, Hit(doc=doc, score=0.0))
                hit.score += 1.0 / (rrf_k + rank + 1)
                hit.lexical_rank = rank + 1

        hits = sorted(fused.values(), key=lambda h: h.score, reverse=True)
        if self.reranker and hits:
            candidates = hits[: max(k * 3, 20)]
            with self._lock:
                scores = self.reranker.scores(query, [h.doc.text[:1500] for h in candidates])
            for h, s in zip(candidates, scores):
                h.score = s
            hits = sorted(candidates, key=lambda h: h.score, reverse=True)

        # Several chunks of one blog post would waste slots; keep the best one (read_document shows the rest).
        seen_posts: set[int] = set()
        unique = []
        for h in hits:
            post = h.doc.meta.get("post_no") if h.doc.source_type == "weblog" else None
            if post is not None:
                if post in seen_posts:
                    continue
                seen_posts.add(post)
            unique.append(h)
        return unique[:k]
