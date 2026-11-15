#!/usr/bin/env python3
"""Download and safely extract the bundled source and RAG index release asset."""
from __future__ import annotations

import json
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.github.com/repos/jackthecypherpunk/eric-clone/releases/latest"
ASSET = "archive-data.zip"


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "archive-rag-agent"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as out:
        while chunk := response.read(1024 * 1024):
            out.write(chunk)


def main() -> None:
    if (ROOT / "data" / "corpus.jsonl").exists() and (ROOT / "sources").is_dir():
        print("Archive data already present; skipping download.")
        return
    request = urllib.request.Request(API, headers={"User-Agent": "archive-rag-agent"})
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    asset = next((item for item in release.get("assets", []) if item["name"] == ASSET), None)
    if asset is None:
        raise SystemExit(f"Release {release.get('tag_name')} does not contain {ASSET}")

    archive = ROOT / ASSET
    print(f"Downloading {ASSET} ({asset['size'] / (1024**2):.0f} MiB)…")
    download(asset["browser_download_url"], archive)
    try:
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                target = (ROOT / member.filename).resolve()
                if ROOT not in target.parents and target != ROOT:
                    raise SystemExit(f"Unsafe path in archive: {member.filename}")
            bundle.extractall(ROOT)
    finally:
        archive.unlink(missing_ok=True)
    print("Archive data is ready.")


if __name__ == "__main__":
    main()
