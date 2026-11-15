# Archive RAG Agent

A local web app for asking questions about a text archive. It combines semantic and keyword search (RAG), citations to source documents, and an optional OpenAI-compatible language model. This repository includes the source archive and prebuilt ChromaDB and BM25 indexes, so it can be run without reindexing.

## Features

- FastAPI backend and React/TypeScript interface.
- Hybrid retrieval with ChromaDB vectors and BM25 keyword search.
- Optional reranking, source/date filters, exact phrase counts, and source citations.
- Streaming conversations with tool use, optional web search, and file attachments.
- Persian text normalization and Telegram JSON/PDF ingestion are supported out of the box.
- Works with local endpoints such as Ollama or any OpenAI-compatible hosted API.

## Requirements

- Python 3.11 or 3.12
- [uv](https://docs.astral.sh/uv/)
- Node.js 20 or newer and npm
- Enough disk space for the embedding model and indexes (several GB for the default model)

## Quick start

```bash
git clone <repository-url>
cd <repository-directory>
cp .env.example .env
cd backend && uv sync && cd ..
cd web && npm ci && cd ..
```

### Included archive and indexes

The GitHub release includes `archive-data.zip` with the Telegram JSON exports, weblog PDF, corpus, ChromaDB vector store, and BM25 index. `scripts/dev.sh` downloads and extracts it automatically when the archive is not already present. For manual or single-process startup, run `python3 scripts/download_archive.py` first. No reindexing is needed. Source paths can be overridden with comma-separated `TELEGRAM_EXPORTS` and `PDF_SOURCES` entries in `.env`.

### Rebuild the indexes (optional)

```bash
cd backend
uv run python -m app.ingest.run
```

This creates the local corpus, ChromaDB vector index, and BM25 index in `data/`. The first run downloads the configured embedding model and may take a while; later runs add missing documents. Use `--rebuild` after changing the embedding model or to recreate the vector index, and `--limit 500` for a small trial run. Source files are restored from the release asset first.

### Configure a language model

Start with Ollama, for example:

```bash
ollama pull qwen3:8b
```

The sample `.env` uses `http://localhost:11434/v1`. You can instead set `LLM_BASE_URL`, `LLM_MODEL`, and `LLM_API_KEY` in `.env`, or configure the endpoint in the app's Model settings. Hosted API credentials are entered by each user and stored locally under `data/`.

### Run the app

From the repository root:

```bash
./scripts/dev.sh
```

Open <http://localhost:5173>. To serve the built interface and API together:

```bash
cd web && npm run build && cd ..
python3 scripts/download_archive.py
cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then open <http://127.0.0.1:8000>.

## Configuration

See `.env.example` for all options. Common settings:

| Variable | Purpose |
| --- | --- |
| `TELEGRAM_EXPORTS` | Comma-separated Telegram JSON input paths |
| `PDF_SOURCES` | Comma-separated PDF input paths |
| `DATA_DIR` | Local corpus and index directory (default: `data/`) |
| `EMBED_MODEL` | Sentence-transformers embedding model |
| `EMBED_DEVICE` | `cpu` or a supported accelerator such as `cuda` |
| `LLM_BASE_URL` | OpenAI-compatible API base URL |
| `LLM_MODEL` | Model identifier served by that endpoint |
| `LLM_API_KEY` | Optional API key; keep it private |
| `SEARCH_PROVIDER` | `auto`, `tavily`, `brave`, or `duckduckgo` |
| `SEARCH_API_KEY` | Optional web-search provider key |
| `RERANK_ENABLED` | Enable cross-encoder reranking (`true`/`false`) |

The app can run retrieval without an LLM by using its search page/API. Chat requires a configured model endpoint. Optional web search can use DuckDuckGo without a key or Tavily/Brave with a key.

## API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/status` | Index and model status |
| `POST` | `/api/chat` | Stream an answer as server-sent events |
| `GET` | `/api/search?q=...` | Search the indexed corpus |
| `GET` | `/api/mentions?phrase=...` | Find exact phrase occurrences |
| `GET` | `/api/documents/{id}` | Read a document and nearby context |
| `PUT` | `/api/settings/llm` | Update local model settings |

## Development

```bash
cd backend && uv run pytest
cd ../web && npm run lint && npm run build
```

## Privacy and data

The source archive and indexes are distributed as a GitHub release asset rather than Git objects. They may contain identifying details and copyrighted writing; review the applicable privacy, copyright, and platform terms before redistributing them. User uploads, model settings, and logs are local runtime data and are ignored by Git. Never commit API keys or a populated `.env` file.

## License

The application code is available under the MIT License. The archive documents in `sources/` remain subject to their authors' rights and applicable platform terms; the MIT License does not apply to those documents.
