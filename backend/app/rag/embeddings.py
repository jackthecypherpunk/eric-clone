from __future__ import annotations

import logging
import threading
from functools import cached_property

import numpy as np

log = logging.getLogger(__name__)
_load_lock = threading.Lock()  # warm-up and the first request may race to load the same model


class Embedder:
    """SentenceTransformer wrapper that applies the query/passage prefixes some models were trained with."""

    def __init__(self, model_name: str, device: str = "cpu", batch_size: int = 32):
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self._model = None
        lowered = model_name.lower()
        if "e5" in lowered:
            self.query_prefix, self.passage_prefix = "query: ", "passage: "
        else:  # bge-m3, gte, etc. need no prefix for symmetric retrieval
            self.query_prefix = self.passage_prefix = ""

    @property
    def model(self):
        with _load_lock:
            if self._model is None:
                from sentence_transformers import SentenceTransformer

                log.info("Loading embedding model %s on %s", self.model_name, self.device)
                self._model = SentenceTransformer(self.model_name, device=self.device)
                self._model.max_seq_length = min(self._model.max_seq_length or 512, 512)
            return self._model

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return self._encode([self.passage_prefix + t for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._encode([self.query_prefix + text])[0]

    def _encode(self, texts: list[str]) -> np.ndarray:
        return self.model.encode(
            texts, batch_size=self.batch_size, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
        )


class Reranker:
    def __init__(self, model_name: str, device: str = "cpu"):
        self.model_name = model_name
        self.device = device

    @cached_property
    def model(self):
        from sentence_transformers import CrossEncoder

        log.info("Loading reranker %s", self.model_name)
        return CrossEncoder(self.model_name, device=self.device, max_length=512)

    def scores(self, query: str, passages: list[str]) -> list[float]:
        return [float(s) for s in self.model.predict([(query, p) for p in passages], batch_size=16)]
