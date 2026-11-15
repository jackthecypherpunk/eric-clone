"""In-memory view of every ingested document, used for full-text reads, context, and exact-phrase research queries."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from ..ingest.documents import Document
from ..text import fold


def save_corpus(path: Path, docs: list[Document]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for doc in docs:
            f.write(json.dumps(doc.to_json(), ensure_ascii=False) + "\n")


class Corpus:
    def __init__(self, docs: list[Document]):
        self.docs = docs
        self.by_id = {d.id: d for d in docs}
        self.position = {d.id: i for i, d in enumerate(docs)}
        self._folded: list[str] | None = None
        # Ordered siblings for "what came before/after" context.
        self._sequence: dict[str, list[str]] = defaultdict(list)
        for d in docs:
            self._sequence[self._sequence_key(d)].append(d.id)
        self._seq_index = {doc_id: (key, i) for key, ids in self._sequence.items() for i, doc_id in enumerate(ids)}

    @classmethod
    def load(cls, path: Path) -> Corpus:
        if not path.exists():
            return cls([])
        with path.open(encoding="utf-8") as f:
            return cls([Document(**json.loads(line)) for line in f if line.strip()])

    @staticmethod
    def _sequence_key(d: Document) -> str:
        return d.meta.get("channel_slug", "") if d.source_type == "telegram" else d.source_type

    def __len__(self) -> int:
        return len(self.docs)

    def get(self, doc_id: str) -> Document | None:
        return self.by_id.get(doc_id)

    def neighbors(self, doc_id: str, before: int = 1, after: int = 1) -> tuple[list[Document], list[Document]]:
        if doc_id not in self._seq_index:
            return [], []
        key, i = self._seq_index[doc_id]
        ids = self._sequence[key]
        return [self.by_id[x] for x in ids[max(0, i - before):i]], [self.by_id[x] for x in ids[i + 1:i + 1 + after]]

    def blog_post(self, doc: Document) -> list[Document]:
        """All chunks of the blog post that `doc` belongs to, in order."""
        post_no = doc.meta.get("post_no")
        n = doc.meta.get("chunks_in_post", 1)
        return [c for i in range(n) if (c := self.by_id.get(f"blog:{post_no}:{i}"))]

    def find_phrase(self, phrase: str, source_type: str | None = None) -> list[Document]:
        if self._folded is None:
            self._folded = [fold(d.text) for d in self.docs]
        needle = fold(phrase)
        if not needle:
            return []
        return [
            d for d, text in zip(self.docs, self._folded)
            if needle in text and (source_type in (None, "all") or d.source_type == source_type)
        ]

    def stats(self) -> dict:
        counts: dict[str, int] = defaultdict(int)
        for d in self.docs:
            counts[d.source] += 1
        dates = sorted(d.date[:10] for d in self.docs if d.date)
        return {"documents": len(self.docs), "by_source": dict(counts),
                "date_range": [dates[0], dates[-1]] if dates else None}
