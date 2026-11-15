"""Tools the agent can call. Each returns (text for the model, structured payload for the UI)."""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from ..ingest.documents import Document
from ..rag.retriever import Filters, Retriever

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_archive",
            "description": (
                "Recall what you wrote on a subject (semantic + keyword search over your Telegram posts and weblog essays). "
                "Unfiltered recall always includes your best-matching blog essays. Query in Persian for best results."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look for, ideally in Persian."},
                    "source": {
                        "type": "string",
                        "enum": ["all", "telegram", "weblog"],
                        "description": "Only your Telegram posts, or only your weblog essays. Default all.",
                    },
                    "date_from": {"type": "string", "description": "Optional lower bound, YYYY or YYYY-MM-DD."},
                    "date_to": {"type": "string", "description": "Optional upper bound, YYYY or YYYY-MM-DD."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 15, "description": "Default 8."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_document",
            "description": (
                "Re-read one of your posts in full by id: the whole essay for a weblog id, or for a Telegram post also "
                "the post it replies to and your posts just before and after it."
            ),
            "parameters": {
                "type": "object",
                "properties": {"doc_id": {"type": "string", "description": "An id returned by search_archive."}},
                "required": ["doc_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_mentions",
            "description": (
                "How often and when you used an exact word or phrase in everything you wrote (spelling- and half-space-"
                "insensitive): number of posts per year, plus the first, last and a few sample posts. "
                "Use for questions like 'how often / since when did you write about X'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "phrase": {"type": "string", "description": "Word or phrase, usually in Persian."},
                    "source": {"type": "string", "enum": ["all", "telegram", "weblog"]},
                },
                "required": ["phrase"],
            },
        },
    },
]


def doc_card(doc: Document, excerpt_chars: int | None = 320) -> dict:
    """Compact JSON shape shared by tool payloads and the documents API."""
    text = doc.text if excerpt_chars is None or len(doc.text) <= excerpt_chars else doc.text[:excerpt_chars] + "…"
    return {
        "id": doc.id,
        "source": doc.source,
        "source_type": doc.source_type,
        "date": doc.date[:10],
        "title": doc.title,
        "text": text,
        "pages": doc.meta.get("pages", ""),
        "message_id": doc.meta.get("message_id"),
    }


def _for_model(doc: Document, max_chars: int = 1800) -> str:
    text = doc.text if len(doc.text) <= max_chars else doc.text[:max_chars] + " …[truncated; use read_document]"
    head = f"[[{doc.id}]] {doc.source} · {doc.date[:10] or 'undated'}"
    if doc.title:
        head += f" · «{doc.title}»"
    if doc.meta.get("forwarded_from"):
        head += f" · forwarded from {doc.meta['forwarded_from']}"
    return f"{head}\n{text}"


class ToolRunner:
    def __init__(self, retriever: Retriever):
        self.retriever = retriever

    def run(self, name: str, raw_args: str | dict) -> tuple[str, dict]:
        try:
            args = json.loads(raw_args or "{}") if isinstance(raw_args, str) else dict(raw_args)
        except json.JSONDecodeError:
            return f"Invalid JSON arguments: {raw_args!r}", {"error": "invalid arguments"}
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return f"Unknown tool {name}", {"error": f"unknown tool {name}"}
        try:
            return handler(**args)
        except TypeError as exc:
            return f"Bad arguments for {name}: {exc}", {"error": str(exc)}

    def _tool_search_archive(self, query: str, source: str = "all", date_from: str | None = None,
                             date_to: str | None = None, limit: int = 8) -> tuple[str, dict]:
        filters = Filters(source_type=None if source == "all" else source, date_from=date_from, date_to=date_to)
        hits = self.retriever.search(query, k=max(1, min(int(limit), 15)), filters=filters)
        if not hits:
            return "You never wrote anything matching this.", {"hits": []}
        text = "\n\n".join(_for_model(h.doc) for h in hits)
        return text, {"hits": [doc_card(h.doc) | {"score": round(h.score, 4)} for h in hits]}

    def _tool_read_document(self, doc_id: str) -> tuple[str, dict]:
        corpus = self.retriever.corpus
        doc = corpus.get(doc_id.strip("[] "))
        if doc is None:
            return f"No post with id {doc_id}.", {"error": "not found"}
        if doc.source_type == "weblog":
            chunks = corpus.blog_post(doc)
            body = "\n…\n".join(c.text for c in chunks)
            text = f"[[{doc.id}]] Your blog essay «{doc.title}» · {doc.date[:10]} · {len(chunks)} chunks (overlapping)\n{body}"
            return text, {"document": doc_card(doc, None), "context": [doc_card(c, 200) for c in chunks if c.id != doc.id]}

        parts, context = [], []
        if (parent_id := doc.meta.get("reply_to")) and (parent := corpus.get(parent_id)):
            parts.append("This post of yours replies to:\n" + _for_model(parent, 1200))
            context.append(doc_card(parent, 200) | {"relation": "replied to"})
        before, after = corpus.neighbors(doc.id, 2, 2)
        parts.append("THE POST:\n" + _for_model(doc, 6000))
        if before or after:
            parts.append("Your posts just before and after it, same channel:\n" + "\n\n".join(_for_model(d, 500) for d in before + after))
            context += [doc_card(d, 200) | {"relation": "before"} for d in before]
            context += [doc_card(d, 200) | {"relation": "after"} for d in after]
        return "\n\n".join(parts), {"document": doc_card(doc, None), "context": context}

    def _tool_find_mentions(self, phrase: str, source: str = "all") -> tuple[str, dict]:
        docs = sorted(self.retriever.corpus.find_phrase(phrase, source), key=lambda d: d.date)
        if not docs:
            return f"You never used «{phrase}» in anything you wrote.", {"total": 0, "by_year": {}, "samples": []}
        by_year = dict(sorted(Counter(d.date[:4] or "undated" for d in docs).items()))
        step = max(1, len(docs) // 6)
        samples = list({d.id: d for d in [docs[0], *docs[step:-1:step][:6], docs[-1]]}.values())
        text = (
            f"You used «{phrase}» in {len(docs)} posts. Per year: {by_year}.\n"
            f"First: {docs[0].date[:10]}, last: {docs[-1].date[:10]}.\nSamples (chronological):\n\n"
            + "\n\n".join(_for_model(d, 500) for d in samples)
        )
        return text, {"total": len(docs), "by_year": by_year, "samples": [doc_card(d, 240) for d in samples]}


WEB_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the live web for recent news and facts that are not in the writing. Returns titles, URLs, "
                "dates and snippets; open promising results with fetch_page."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query, in the language most sources use."},
                    "recency": {"type": "string", "enum": ["day", "week", "month", "year"],
                                "description": "Only results from this period (for current events)."},
                    "news": {"type": "boolean", "description": "Search news articles instead of the general web."},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_page",
            "description": "Open a web page (or online PDF) by URL and read its main text.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
]
WEB_TOOL_NAMES = {t["function"]["name"] for t in WEB_TOOLS}


class WebToolRunner:
    def __init__(self, provider: str, api_key: str):
        self.provider = provider
        self.api_key = api_key

    def run(self, name: str, raw_args: str | dict) -> tuple[str, dict]:
        from . import web

        try:
            args = json.loads(raw_args or "{}") if isinstance(raw_args, str) else dict(raw_args)
            if name == "web_search":
                provider = web.resolve_provider(self.provider, self.api_key)
                results = web.search(args["query"], self.provider, self.api_key, int(args.get("max_results") or 6),
                                     args.get("recency"), bool(args.get("news")))
                if not results:
                    return "No web results.", {"results": [], "provider": provider}
                text = "\n\n".join(
                    f"[{i}] {r['title']}\n{r['url']}" + (f"\n{r['date']}" if r["date"] else "") + f"\n{r['snippet']}"
                    for i, r in enumerate(results, start=1)
                )
                return text, {"results": results, "provider": provider}
            if name == "fetch_page":
                page = web.fetch_page(args["url"])
                note = "\n[page truncated]" if page["truncated"] else ""
                return f"{page['title']}\n{page['url']}\n\n{page['text']}{note}", {
                    "page": {"title": page["title"], "url": page["url"], "excerpt": page["text"][:400]}}
        except (KeyError, json.JSONDecodeError) as exc:
            return f"Bad arguments for {name}: {exc}", {"error": f"bad arguments: {exc}"}
        except web.WebError as exc:
            return str(exc), {"error": str(exc)}
        except Exception as exc:  # network errors, provider HTTP errors, rate limits
            return f"The web request failed: {exc}", {"error": f"web request failed: {exc}"}
        return f"Unknown tool {name}", {"error": f"unknown tool {name}"}
