#!/usr/bin/env python3
"""Restore the prebuilt corpus and RAG indexes bundled with this repository."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "data" / "bundled-index"
PAYLOAD = BUNDLE / "payload"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    manifest = json.loads((BUNDLE / "manifest.json").read_text(encoding="utf-8"))
    groups: dict[str, list[dict]] = {}
    for entry in manifest["files"]:
        relative = Path(entry.get("file", entry.get("part", "")))
        source = (BUNDLE / relative).resolve()
        if BUNDLE.resolve() not in source.parents or not source.is_file():
            raise SystemExit(f"Missing or unsafe bundle file: {relative}")
        if sha256(source) != entry["sha256"]:
            raise SystemExit(f"Checksum mismatch: {relative}")
        target = (ROOT / entry["target"]).resolve()
        if ROOT.resolve() not in target.parents:
            raise SystemExit(f"Unsafe output path: {entry['target']}")
        if "part" in entry:
            groups.setdefault(entry["target"], []).append(entry)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())

    for target_name, parts in groups.items():
        target = (ROOT / target_name).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as output:
            for part in sorted(parts, key=lambda item: item["order"]):
                with (BUNDLE / part["part"]).open("rb") as source:
                    while block := source.read(1024 * 1024):
                        output.write(block)
    print(f"Restored {len(manifest['files'])} verified bundle files into data/.")


if __name__ == "__main__":
    main()
