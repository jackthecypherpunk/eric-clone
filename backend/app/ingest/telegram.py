"""Telegram Desktop JSON export -> one Document per post."""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from pathlib import Path

from ..text import normalize
from .documents import Document

log = logging.getLogger(__name__)

MIN_CHARS = 12  # drop bare emoji / "👆" style posts; channel one is full of short one-liners, so keep this low


def _slug(name: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or fallback


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(part if isinstance(part, str) else str(part.get("text", "")) for part in value)
    return ""


def load_export(path: Path) -> Iterator[Document]:
    export = json.loads(path.read_text(encoding="utf-8"))
    channel = export.get("name") or path.stem
    # Non-Latin channel names would slug to "", so fall back to the numeric channel id.
    slug = KNOWN_OWN_CHANNELS.get(channel) or _slug(channel, f"ch{export.get('id', path.stem)}")
    own_names = {channel}
    posts = [m for m in export.get("messages", []) if m.get("type") == "message"]
    by_id = {m["id"]: m for m in posts}
    kept = skipped = 0

    for m in posts:
        forwarded = m.get("forwarded_from")
        # Forwards from third parties are someone else's words; they must not shape the persona.
        if forwarded and forwarded not in own_names and forwarded not in KNOWN_OWN_CHANNELS:
            skipped += 1
            continue
        text = normalize(_text(m.get("text")))
        if len(text) < MIN_CHARS:
            skipped += 1
            continue

        reply_to = m.get("reply_to_message_id")
        reactions = sum(r.get("count", 0) for r in m.get("reactions", []) or [])
        meta = {
            "channel": channel,
            "channel_slug": slug,
            "message_id": m["id"],
            "author": m.get("author", ""),
            "forwarded_from": forwarded or "",
            "reply_to": f"tg:{slug}:{reply_to}" if reply_to in by_id else "",
            "has_media": bool(m.get("photo") or m.get("file")),
            "reactions": reactions,
        }
        kept += 1
        yield Document(
            id=f"tg:{slug}:{m['id']}",
            text=text,
            source_type="telegram",
            source=channel,
            date=m.get("date", ""),
            meta=meta,
        )
    log.info("%s: kept %d posts, skipped %d (empty/too short/third-party forwards)", path.name, kept, skipped)


# Both channels belong to the same author and forward each other. Values are short, readable id slugs.
KNOWN_OWN_CHANNELS = {"Anarchonomy": "anarchonomy", "اقوال الانعام": "aqval"}
