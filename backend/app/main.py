from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .agent.runner import Agent
from .agent.runtime_config import LLMConfigStore, SearchProvider
from .agent.tools import ToolRunner, doc_card
from .attachments import AttachmentStore, UnsupportedFile
from .config import get_settings
from .rag.retriever import Filters, Retriever

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")
settings = get_settings()


class State:
    retriever: Retriever
    agent: Agent
    tools: ToolRunner
    llm: LLMConfigStore
    attachments: AttachmentStore


state = State()


@asynccontextmanager
async def lifespan(_: FastAPI):
    state.retriever = Retriever(settings)
    state.agent = Agent(state.retriever, settings.persona_name, settings.llm_max_tool_rounds,
                        max_tool_calls=settings.llm_max_tool_calls)
    state.tools = ToolRunner(state.retriever)
    state.llm = LLMConfigStore(settings)
    state.attachments = AttachmentStore(settings)
    if not state.retriever.ready:
        log.warning("Archive index is empty. Run: uv run python -m app.ingest.run")
    # Load the embedding model in the background so the first question isn't slow.
    asyncio.get_running_loop().run_in_executor(None, state.retriever.warm_up)
    yield


app = FastAPI(title="Archive RAG Agent", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


# --- status & settings -----------------------------------------------------------

@app.get("/api/status")
def status():
    r = state.retriever
    return {
        "ready": r.ready,
        "persona": settings.persona_name,
        "corpus": r.corpus.stats(),
        "vectors": r.dense.count(),
        "embed_model": settings.embed_model,
        "rerank": settings.rerank_model if settings.rerank_enabled else None,
        "llm": state.llm.get().public(),
    }


class LLMSettingsIn(BaseModel):
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    temperature: float = Field(default=0.6, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=0, le=128_000, description="0 = no limit")
    api_key: str | None = Field(default=None, max_length=500, description="omit to keep the stored key")
    search_provider: SearchProvider | None = None
    search_api_key: str | None = Field(default=None, max_length=500, description="omit to keep the stored key")


@app.put("/api/settings/llm")
def update_llm(body: LLMSettingsIn):
    if not body.base_url.startswith(("http://", "https://")):
        raise HTTPException(400, "Base URL must start with http:// or https://")
    return state.llm.update(**body.model_dump()).public()


class ModelsIn(BaseModel):
    base_url: str | None = None
    api_key: str | None = None  # omit to use the stored key


@app.post("/api/settings/models")
async def list_models(body: ModelsIn):
    """Lists models from the configured (or given) OpenAI-compatible endpoint, for the model picker."""
    cfg = state.llm.get()
    base_url = (body.base_url or cfg.base_url).rstrip("/")
    url = base_url + "/models"
    # Never send the stored key to a different endpoint than the one it was saved for.
    key = body.api_key if body.api_key is not None else (cfg.api_key if base_url == cfg.base_url else "")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            res = await client.get(url, headers={"Authorization": f"Bearer {key}"} if key else {})
            res.raise_for_status()
            return {"models": sorted(m["id"] for m in res.json().get("data", []))}
    except Exception as exc:
        return {"models": [], "error": f"Could not list models at {url}: {exc}"}


# --- chat ------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=40_000)
    attachments: list[str] = Field(default_factory=list, max_length=10)


class ChatIn(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=60)
    agent: Literal["clone", "analyst"] = "clone"
    web_search: bool = False


def _model_message(m: ChatMessage) -> dict:
    if m.role != "user" or not m.attachments:
        return {"role": m.role, "content": m.content}
    text = m.content or "(see the attached files)"
    return {"role": "user", "content": [{"type": "text", "text": text}, *state.attachments.content_parts(m.attachments)]}


@app.post("/api/chat")
async def chat(body: ChatIn):
    if body.messages[-1].role != "user":
        raise HTTPException(400, "The last message must come from the user.")
    if not state.retriever.ready:
        raise HTTPException(503, "The archive is not indexed yet. Run the ingestion first.")

    history = [_model_message(m) for m in body.messages[-30:]]

    async def stream():
        try:
            async for event in state.agent.run(history, state.llm.get(), body.agent, body.web_search):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:  # client pressed stop / closed the tab
            raise
        except Exception as exc:
            log.exception("chat failed")
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --- attachments ------------------------------------------------------------------

@app.post("/api/attachments")
async def upload(file: UploadFile = File(...)):
    data = await file.read(state.attachments.max_bytes + 1)
    try:
        return await asyncio.to_thread(state.attachments.save, file.filename or "file", data)
    except UnsupportedFile as exc:
        raise HTTPException(415, str(exc)) from exc


@app.get("/api/attachments/{att_id}/image")
def attachment_image(att_id: str):
    try:
        path, mime = state.attachments.image_file(att_id)
    except KeyError:
        raise HTTPException(404, "Not found") from None
    return FileResponse(path, media_type=mime)


# --- direct research endpoints (no LLM) ------------------------------------------

@app.get("/api/search")
def search(q: str = Query(min_length=1, max_length=500), source: Literal["all", "telegram", "weblog"] = "all",
           date_from: str | None = None, date_to: str | None = None, limit: int = Query(20, ge=1, le=50)):
    hits = state.retriever.search(
        q, k=limit, filters=Filters(None if source == "all" else source, date_from, date_to)
    )
    return {"hits": [doc_card(h.doc, 600) | {"score": round(h.score, 4)} for h in hits]}


@app.get("/api/mentions")
def mentions(phrase: str = Query(min_length=1, max_length=200), source: Literal["all", "telegram", "weblog"] = "all"):
    return state.tools.run("find_mentions", {"phrase": phrase, "source": source})[1]


@app.get("/api/documents/{doc_id:path}")
def document(doc_id: str):
    _, data = state.tools.run("read_document", {"doc_id": doc_id})
    if "error" in data:
        raise HTTPException(404, data["error"])
    return data


# --- production: serve the built UI (cd web && npm run build) from the same origin ---------
_dist = settings.data_dir.parent / "web" / "dist"
if _dist.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
