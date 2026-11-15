"""User attachments: images are passed to the model as images; documents are converted to text."""
from __future__ import annotations

import base64
import io
import json
import re
import uuid
import zipfile
from pathlib import Path

from .config import Settings

TEXT_EXT = {".txt", ".md", ".csv", ".tsv", ".json", ".html", ".htm", ".xml", ".srt", ".vtt", ".log", ".yaml", ".yml"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
MAX_IMAGE_SIDE = 1568  # larger images cost more tokens without helping most vision models
_ID = re.compile(r"^[0-9a-f]{32}$")


class UnsupportedFile(ValueError):
    pass


def _extract_pdf(data: bytes) -> tuple[str, dict]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = [f"[page {i}]\n{(p.extract_text() or '').strip()}" for i, p in enumerate(reader.pages, start=1)]
    text = "\n\n".join(pages)
    meta = {"pages": len(reader.pages)}
    if len(re.sub(r"\[page \d+\]|\s", "", text)) < 20 * max(1, len(reader.pages)):
        meta["warning"] = "almost no extractable text (probably a scanned PDF)"
    return text, meta


def _extract_docx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    paragraphs = re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.S)
    return "\n".join("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)) for p in paragraphs).strip()


def _normalize_image(data: bytes) -> tuple[bytes, str, dict]:
    from PIL import Image, ImageOps

    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    out = io.BytesIO()
    if img.mode in ("RGBA", "LA", "P"):
        img.convert("RGBA").save(out, "PNG", optimize=True)
        return out.getvalue(), "image/png", {"width": img.width, "height": img.height}
    img.convert("RGB").save(out, "JPEG", quality=88)
    return out.getvalue(), "image/jpeg", {"width": img.width, "height": img.height}


class AttachmentStore:
    def __init__(self, settings: Settings):
        self.dir = settings.uploads_dir
        self.max_bytes = settings.max_upload_mb * 1024 * 1024
        self.max_chars = settings.max_attachment_chars

    def save(self, filename: str, data: bytes) -> dict:
        if len(data) > self.max_bytes:
            raise UnsupportedFile(f"File is larger than {self.max_bytes // 1024 // 1024} MB.")
        ext = Path(filename).suffix.lower()
        att_id = uuid.uuid4().hex
        folder = self.dir / att_id
        meta: dict = {"id": att_id, "name": Path(filename).name[:200], "size": len(data)}

        if ext in IMAGE_EXT:
            try:
                blob, mime, extra = _normalize_image(data)
            except Exception as exc:
                raise UnsupportedFile("Could not read that image.") from exc
            meta |= {"kind": "image", "mime": mime, **extra}
            folder.mkdir(parents=True)
            (folder / "image").write_bytes(blob)
        else:
            if ext == ".pdf":
                text, extra = _extract_pdf(data)
                meta |= {"kind": "pdf", **extra}
            elif ext == ".docx":
                text = _extract_docx(data)
                meta["kind"] = "document"
            elif ext in TEXT_EXT:
                text = data.decode("utf-8", errors="replace")
                meta["kind"] = "text"
            else:
                raise UnsupportedFile(
                    f"{ext or 'This file type'} isn't supported. Send images, PDF, DOCX or text files "
                    "(audio and video can't be read by most chat models)."
                )
            meta |= {"chars": len(text), "truncated": len(text) > self.max_chars}
            folder.mkdir(parents=True)
            (folder / "text.txt").write_text(text, encoding="utf-8")
        (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return meta

    def _folder(self, att_id: str) -> Path:
        if not _ID.match(att_id):
            raise KeyError(att_id)
        folder = self.dir / att_id
        if not folder.is_dir():
            raise KeyError(att_id)
        return folder

    def meta(self, att_id: str) -> dict:
        return json.loads((self._folder(att_id) / "meta.json").read_text(encoding="utf-8"))

    def image_file(self, att_id: str) -> tuple[Path, str]:
        meta = self.meta(att_id)
        if meta.get("kind") != "image":
            raise KeyError(att_id)
        return self._folder(att_id) / "image", meta["mime"]

    def content_parts(self, att_ids: list[str]) -> list[dict]:
        """OpenAI-style content parts for a user message: image parts and/or text blocks."""
        parts: list[dict] = []
        for att_id in att_ids:
            try:
                meta = self.meta(att_id)
            except KeyError:
                parts.append({"type": "text", "text": f"[An attachment ({att_id}) is no longer available.]"})
                continue
            folder = self._folder(att_id)
            if meta["kind"] == "image":
                b64 = base64.b64encode((folder / "image").read_bytes()).decode()
                parts.append({"type": "text", "text": f"[Attached image: {meta['name']}]"})
                parts.append({"type": "image_url", "image_url": {"url": f"data:{meta['mime']};base64,{b64}"}})
                continue
            text = (folder / "text.txt").read_text(encoding="utf-8")
            notes = []
            if meta.get("warning"):
                notes.append(meta["warning"])
            if len(text) > self.max_chars:
                text = text[: self.max_chars]
                notes.append(f"truncated to the first {self.max_chars:,} of {meta['chars']:,} characters")
            note = f" ({'; '.join(notes)})" if notes else ""
            parts.append({"type": "text",
                          "text": f'<attachment name="{meta["name"]}" type="{meta["kind"]}"{note}>\n{text}\n</attachment>'})
        return parts
