"""Settings the UI can change at runtime (persisted under data/, which is git-ignored)."""
from __future__ import annotations

import json
import threading
from typing import Literal

from pydantic import BaseModel, Field

from ..config import Settings

SearchProvider = Literal["auto", "tavily", "brave", "duckduckgo"]


def key_hint(key: str) -> str:
    """What the UI shows for a stored secret: never the key itself, only its last 4 characters."""
    return "" if not key else "•" * 8 + (key[-4:] if len(key) > 8 else "")


class LLMConfig(BaseModel):
    base_url: str = Field(min_length=1)
    model: str = Field(min_length=1)
    api_key: str = ""
    temperature: float = Field(default=0.6, ge=0, le=2)
    max_tokens: int = Field(default=8192, ge=0, le=128_000)  # 0 = no limit (send no cap)
    search_provider: SearchProvider = "auto"
    search_api_key: str = ""

    def public(self) -> dict:
        return {
            "base_url": self.base_url, "model": self.model, "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "has_api_key": bool(self.api_key), "api_key_hint": key_hint(self.api_key),
            "search_provider": self.search_provider,
            "has_search_api_key": bool(self.search_api_key), "search_api_key_hint": key_hint(self.search_api_key),
        }


class LLMConfigStore:
    def __init__(self, settings: Settings):
        self._path = settings.runtime_settings_file
        self._lock = threading.Lock()
        self._config = LLMConfig(base_url=settings.llm_base_url, model=settings.llm_model,
                                 api_key=settings.llm_api_key, temperature=settings.llm_temperature,
                                 max_tokens=settings.llm_max_tokens,
                                 search_provider=settings.search_provider, search_api_key=settings.search_api_key)
        if self._path.exists():
            try:
                saved = json.loads(self._path.read_text(encoding="utf-8"))
                self._config = LLMConfig(**{**self._config.model_dump(), **saved})
            except (ValueError, TypeError):
                pass

    def get(self) -> LLMConfig:
        return self._config

    def update(self, **changes) -> LLMConfig:
        """Secrets passed as None keep their stored value, so the UI never needs to read keys back."""
        with self._lock:
            data = self._config.model_dump()
            for key, value in changes.items():
                if value is None:
                    continue
                data[key] = value.strip() if isinstance(value, str) else value
            data["base_url"] = data["base_url"].rstrip("/")
            self._config = LLMConfig(**data)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(self._config.model_dump_json(indent=2), encoding="utf-8")
            return self._config
