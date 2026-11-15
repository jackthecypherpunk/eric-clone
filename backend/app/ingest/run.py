"""Build the archive index.

    uv run python -m app.ingest.run            # resume: embeds only what is missing
    uv run python -m app.ingest.run --rebuild  # drop the Chroma collection and start over
    uv run python -m app.ingest.run --limit 500  # quick smoke test on a subset
"""
from __future__ import annotations

import argparse
import logging
import time

from tqdm import tqdm

from ..config import get_settings
from ..rag.corpus import save_corpus
from ..rag.embeddings import Embedder
from ..rag.index import DenseIndex, LexicalIndex, windows_for
from .documents import Document
from .pdf import load_pdf
from .telegram import load_export

log = logging.getLogger("ingest")


def collect(limit: int | None = None) -> list[Document]:
    s = get_settings()
    docs: list[Document] = []
    for path in s.telegram_exports:
        if path.exists():
            docs.extend(load_export(path))
        else:
            log.warning("Missing Telegram export: %s", path)
    for path in s.pdf_sources:
        if path.exists():
            docs.extend(load_pdf(path, s.pdf_chunk_chars, s.pdf_chunk_overlap))
        else:
            log.warning("Missing PDF: %s", path)
    if limit:
        # Spread a smoke-test subset across every source instead of taking the first N posts.
        step = max(1, len(docs) // limit)
        docs = docs[::step][:limit]
    return docs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rebuild", action="store_true", help="delete the vector collection first")
    parser.add_argument("--limit", type=int, help="index only N documents (for testing)")
    parser.add_argument("--chunk", type=int, default=512, help="windows per embedding/upsert round")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    s = get_settings()
    t0 = time.time()
    docs = collect(args.limit)
    log.info("Collected %d documents", len(docs))

    save_corpus(s.corpus_file, docs)
    LexicalIndex(s).build(docs)
    log.info("Saved corpus and BM25 index")

    embedder = Embedder(s.embed_model, s.embed_device, s.embed_batch_size)
    dense = DenseIndex(s, embedder)
    if args.rebuild:
        dense.reset()

    windows = [w for d in docs for w in windows_for(d, s.embed_max_chars)]
    todo = dense.missing(windows)
    log.info("%d embedding windows total, %d to embed with %s", len(windows), len(todo), s.embed_model)
    # Similar lengths per batch -> far less padding -> much faster on CPU.
    todo.sort(key=lambda w: len(w.text))
    with tqdm(total=len(todo), unit="win", desc="embedding") as bar:
        for i in range(0, len(todo), args.chunk):
            batch = todo[i:i + args.chunk]
            dense.add(batch, embedder.embed_passages([w.text for w in batch]))
            bar.update(len(batch))

    log.info("Done: %d documents, %d vectors in %.0fs", len(docs), dense.count(), time.time() - t0)


if __name__ == "__main__":
    main()
