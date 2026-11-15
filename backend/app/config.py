from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


def source_paths(variable: str, default: str) -> list[Path]:
    """Read comma-separated source paths, resolving relative paths from the repo root."""
    paths = []
    for item in os.getenv(variable, default).split(","):
        item = item.strip()
        if item:
            path = Path(item).expanduser()
            paths.append(path if path.is_absolute() else ROOT / path)
    return paths


class Settings(BaseSettings):
    """All settings can be overridden with environment variables or the repo-level `.env`."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    # --- Sources -------------------------------------------------------------
    telegram_exports: list[Path] = source_paths(
        "TELEGRAM_EXPORTS",
        "sources/telegram-aqval-alanaam.json,sources/telegram-anarchonomy.json",
    )
    pdf_sources: list[Path] = source_paths("PDF_SOURCES", "sources/weblog-badbakht.pdf")
    stopwords_file: Path = ROOT / "persian_stop_words.txt"

    # --- Storage -------------------------------------------------------------
    data_dir: Path = ROOT / "data"
    collection_name: str = "eric_archive"

    # --- Embeddings / retrieval ----------------------------------------------
    # multilingual-e5-large handles Persian well and runs on CPU. BAAI/bge-m3 is a
    # stronger (and slower) alternative with an 8k context window.
    embed_model: str = "intfloat/multilingual-e5-large"
    embed_device: str = "cpu"
    embed_batch_size: int = 8  # small batches are faster on CPU (less padding)
    embed_max_chars: int = 1400  # longer posts are embedded as several windows of the same post
    pdf_chunk_chars: int = 1100
    pdf_chunk_overlap: int = 200

    # Cross-encoder reranking of the fused candidates. Better precision, ~1-3 s extra on CPU.
    rerank_enabled: bool = False
    rerank_model: str = "BAAI/bge-reranker-v2-m3"

    weblog_share: float = 0.3  # fraction of unfiltered search results reserved for weblog posts
    candidate_pool: int = 40  # per retriever, before fusion
    rrf_k: int = 60

    # --- LLM (any OpenAI-compatible endpoint: Ollama, LM Studio, vLLM, OpenAI, OpenRouter, ...) ---
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "qwen3:8b"
    llm_api_key: str = ""
    llm_temperature: float = 0.6
    # Output cap per model call. Without it, providers like OpenRouter reserve credit for the model's
    # full output limit (e.g. 65k tokens) and refuse the request if your balance can't cover that.
    llm_max_tokens: int = 8192  # 0 = no limit
    llm_max_tool_rounds: int = 6
    llm_max_tool_calls: int = 12  # lookups per answer; then the model must answer

    persona_name: str = "Archive Author"

    # --- Optional web search (toggle per message in the UI) ---------------------
    # "auto" uses Tavily or Brave when a key is set (here or in the UI), else DuckDuckGo (no key).
    search_provider: str = "auto"
    search_api_key: str = ""

    # --- Attachments -------------------------------------------------------------
    max_upload_mb: int = 25
    max_attachment_chars: int = 60_000  # extracted text per file sent to the model

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def corpus_file(self) -> Path:
        return self.data_dir / "corpus.jsonl"

    @property
    def bm25_dir(self) -> Path:
        return self.data_dir / "bm25"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def runtime_settings_file(self) -> Path:
        return self.data_dir / "llm_settings.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
