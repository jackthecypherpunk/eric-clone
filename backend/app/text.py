"""Persian text normalization and tokenization shared by ingestion and retrieval."""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

ZWNJ = "‌"

_CHAR_MAP = str.maketrans({
    "ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه", "أ": "ا", "إ": "ا", "ٱ": "ا",
    # Persian and Arabic-Indic digits -> ASCII so dates/numbers match either way
    **{chr(0x06F0 + i): str(i) for i in range(10)},
    **{chr(0x0660 + i): str(i) for i in range(10)},
})
_DIACRITICS = re.compile(r"[ً-ٰٟـ]")  # harakat, superscript alef, tatweel
_BIDI = re.compile(r"[‎‏‪-‮⁦-⁩﻿]")
_SPACES = re.compile(r"[ \t   ]+")


def normalize(text: str) -> str:
    """Canonical form for *stored* text: unify letters/digits, strip bidi marks, keep ZWNJ and newlines."""
    text = unicodedata.normalize("NFKC", text)  # also folds PDF presentation forms
    text = _BIDI.sub("", text).translate(_CHAR_MAP)
    text = _DIACRITICS.sub("", text)
    text = re.sub(rf"\s*{ZWNJ}+\s*", ZWNJ, text)
    lines = [_SPACES.sub(" ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


_TOKEN = re.compile(r"[\w]+", re.UNICODE)


@lru_cache
def _stopwords(path: str) -> frozenset[str]:
    p = Path(path)
    if not p.exists():
        return frozenset()
    words = (fold(w) for w in p.read_text(encoding="utf-8").split("\n"))
    return frozenset(w for w in words if w)


def fold(text: str) -> str:
    """Aggressive form used for lexical matching: ZWNJ removed so «می‌گن» == «میگن»."""
    return normalize(text).replace(ZWNJ, "").lower()


def tokenize(text: str, stopwords_file: Path | None = None) -> list[str]:
    stop = _stopwords(str(stopwords_file)) if stopwords_file else frozenset()
    return [t for t in _TOKEN.findall(fold(text)) if len(t) > 1 and t not in stop]
