# Source archive

These are the raw documents the index was built from. They are kept separate
from the application code so the corpus can be audited, replaced, or rebuilt
without touching the backend.

| file | what it is | messages / posts | kept as documents |
|---|---|---:|---:|
| `telegram-aqval-alanaam.json` | Telegram Desktop JSON export | 30,454 | 29,902 |
| `telegram-anarchonomy.json` | Telegram Desktop JSON export | 14,756 | 13,712 |
| `weblog-badbakht.pdf` | 442-page Word-to-PDF weblog dump | 148 posts | 1,022 chunks |

Total in the shipped index: **44,636 documents**, **47,808 embedding
windows**, dates **2009-04-15 → 2026-02-18**.

## What is in the Telegram exports

They are standard [Telegram Desktop JSON exports](https://telegram.org/blog/export-and-more):
one JSON object with `name`, `type`, `id`, and a `messages` array. Each post
keeps its date, message id, reply target, reactions, and forward information.
Service messages (channel created, title changed, etc.) are present in the
export but skipped by the ingester, as are empty/emoji-only posts and forwards
from third-party channels.

## What is in the PDF

The PDF is a flat export of a weblog. The ingester reconstructs individual
posts from date lines such as `آوریل 9 ,2012` and the following title, then
splits long posts into overlapping ~1,100-character chunks. PDF metadata has
been stripped; the page content is unchanged.

## Rebuilding the index

The repository includes the prebuilt index under `data/bundled-index/`. After
cloning, restore it with `python3 scripts/restore_index.py`; indexing again is
optional:

```bash
cd backend && uv run python -m app.ingest.run            # build/resume
uv run python -m app.ingest.run --rebuild                # recreate the index
uv run python -m app.ingest.run --limit 500              # small trial run
```

Rebuilding with the default `intfloat/multilingual-e5-large` model took about
5¾ hours on a 16-core CPU for the full archive. If you change `EMBED_MODEL`,
you must use `--rebuild`.

## Rights and research use

The application code and the archive are packaged together for research and
personal study. The texts remain the work of their original author; no license
to redistribute them commercially is granted by this repository. If you publish
a fork, check the copyright and platform terms that apply to the writing.
