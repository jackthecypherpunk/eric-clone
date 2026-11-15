from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Document:
    """A retrievable unit as the reader sees it: one Telegram post or one weblog-post section."""

    id: str
    text: str
    source_type: str  # "telegram" | "weblog"
    source: str  # human-readable source name, e.g. channel or blog title
    date: str = ""  # ISO date (YYYY-MM-DD...) when known
    title: str = ""
    url: str = ""
    meta: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return asdict(self)

    @property
    def year(self) -> int:
        return int(self.date[:4]) if self.date[:4].isdigit() else 0

    def header(self) -> str:
        """Short context line prepended to each embedded window (contextual chunk header)."""
        bits = [self.source]
        if self.title:
            bits.append(self.title)
        if self.date:
            bits.append(self.date[:10])
        return " | ".join(bits)
