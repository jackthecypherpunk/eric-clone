"""Weblog PDF (a Word export of a blog) -> blog posts -> overlapping, sentence-aware chunks.

The PDF is a flat dump of many blog posts. Each post starts with a date line such as
«آوریل 2012 ,9» followed by the title, and ends with a «N دیدگاه» (comment count) line.
We first rebuild posts from those markers so every chunk knows its post title, date and
pages, then split long posts into overlapping chunks.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader

from ..text import normalize
from .documents import Document

log = logging.getLogger(__name__)

_MONTHS = {
    "ژانویه": 1, "فوریه": 2, "مارس": 3, "آوریل": 4, "مه": 5, "می": 5, "ژوئن": 6,
    "ژوئیه": 7, "جولای": 7, "اوت": 8, "آگوست": 8, "سپتامبر": 9, "اکتبر": 10, "نوامبر": 11, "دسامبر": 12,
}
# pypdf renders Word's "April 9, 2012" as «آوریل 9 ,2012» (space after the month is sometimes lost).
_DATE_LINE = re.compile(rf"^({'|'.join(sorted(_MONTHS, key=len, reverse=True))})\s*(\d{{1,2}})\s*[,،]\s*(20\d\d)$")
_COMMENTS_LINE = re.compile(r"^\d*\s*دیدگاه\s*\d*$")
_BOILERPLATE = {"Follow:", "RSS", "Twitter"}
_SENTENCE_END = re.compile(r"(?<=[.!?؟…»])\s+")


@dataclass
class _Post:
    date: str
    title: str
    first_page: int
    lines: list[tuple[int, str]] = field(default_factory=list)  # (page, line)


def _parse_date(match: re.Match) -> str:
    month, day, year = _MONTHS[match.group(1)], int(match.group(2)), int(match.group(3))
    return f"{year:04d}-{month:02d}-{day:02d}"


def _lines(path: Path) -> Iterator[tuple[int, str]]:
    # pypdf keeps RTL word order and decodes the «لا» ligature correctly for this file;
    # PyMuPDF and poppler both turn it into «ال» (e.g. «مردساالر»).
    for page_no, page in enumerate(PdfReader(path).pages, start=1):
        for line in normalize(page.extract_text() or "").split("\n"):
            yield page_no, line.strip()


def _posts(path: Path) -> list[_Post]:
    posts: list[_Post] = []
    pending_title = False
    current: _Post | None = None
    for page, line in _lines(path):
        if not line or line in _BOILERPLATE:
            continue
        if m := _DATE_LINE.match(line):
            current = _Post(date=_parse_date(m), title="", first_page=page)
            posts.append(current)
            pending_title = True
            continue
        if _COMMENTS_LINE.match(line):
            continue
        if current is None:  # blog header before the first post
            continue
        if pending_title:
            current.title, pending_title = line, False
            continue
        current.lines.append((page, line))
    return [p for p in posts if p.lines]


def _paragraphs(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Re-join hard-wrapped PDF lines into paragraphs. A line ending in sentence punctuation closes one."""
    paras: list[tuple[int, str]] = []
    buf: list[str] = []
    start_page = lines[0][0] if lines else 0
    for page, line in lines:
        if not buf:
            start_page = page
        buf.append(line)
        if re.search(r"[.!?؟…:»]$", line) or len(line) < 40:
            paras.append((start_page, " ".join(buf)))
            buf = []
    if buf:
        paras.append((start_page, " ".join(buf)))
    return paras


def chunk_post(paragraphs: list[tuple[int, str]], size: int, overlap: int) -> list[tuple[list[int], str]]:
    """Pack sentences into ~`size`-char chunks; each new chunk starts with ~`overlap` chars of the previous one."""
    units: list[tuple[int, str]] = []
    for page, para in paragraphs:
        for sent in _SENTENCE_END.split(para):
            sent = sent.strip()
            while len(sent) > size:  # a single run-on "sentence": split at a word boundary
                cut = sent.rfind(" ", 0, size) if " " in sent[:size] else size
                units.append((page, sent[:cut]))
                sent = sent[cut:].strip()
            if sent:
                units.append((page, sent))

    chunks: list[tuple[list[int], str]] = []
    cur: list[tuple[int, str]] = []
    for unit in units:
        if cur and sum(len(u[1]) + 1 for u in cur) + len(unit[1]) > size:
            chunks.append((sorted({p for p, _ in cur}), " ".join(u for _, u in cur)))
            tail: list[tuple[int, str]] = []
            for u in reversed(cur):  # carry whole trailing sentences as overlap
                if sum(len(t[1]) for t in tail) + len(u[1]) > overlap:
                    break
                tail.insert(0, u)
            cur = tail
        cur.append(unit)
    if cur:
        chunks.append((sorted({p for p, _ in cur}), " ".join(u for _, u in cur)))
    return chunks


def load_pdf(path: Path, size: int, overlap: int, blog_name: str = "BadBakht") -> Iterator[Document]:
    posts = _posts(path)
    n_chunks = 0
    for post_no, post in enumerate(posts, start=1):
        chunks = chunk_post(_paragraphs(post.lines), size, overlap)
        for i, (pages, text) in enumerate(chunks):
            n_chunks += 1
            yield Document(
                id=f"blog:{post_no}:{i}",
                text=text,
                source_type="weblog",
                source=f"Weblog · {blog_name}",
                date=post.date,
                title=post.title,
                meta={
                    "post_no": post_no,
                    "chunk": i,
                    "chunks_in_post": len(chunks),
                    "pages": ",".join(map(str, pages)),
                    "file": path.name,
                },
            )
    log.info("%s: %d blog posts -> %d chunks", path.name, len(posts), n_chunks)
