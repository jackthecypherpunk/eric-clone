"""The agent loop. Streams events the UI renders live:

    {"type": "reasoning", "text"}                       model thinking tokens (if the model emits them)
    {"type": "token", "text"}                           answer tokens
    {"type": "tool_call", "id", "name", "arguments"}    the model decided to call a tool
    {"type": "tool_result", "id", "name", "summary", "data", "elapsed_ms"}
    {"type": "notice", "message"}                       non-fatal info (e.g. tool-less fallback)
    {"type": "done", "elapsed_ms", "usage"}
    {"type": "error", "message"}
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from openai import APIError, AsyncOpenAI, BadRequestError

from ..rag.retriever import Retriever
from .leaks import MARKERS, LeakFilter, parse_leaked_calls
from .prompts import FALLBACK_NOTE, system_prompt
from .runtime_config import LLMConfig
from .tools import TOOLS, WEB_TOOL_NAMES, WEB_TOOLS, ToolRunner, WebToolRunner, _for_model, doc_card

log = logging.getLogger(__name__)

Event = dict[str, Any]

BUDGET_NOTE = """
# Research budget
You have at most {n} lookups (tool calls) per answer. Plan them: 2-5 well-chosen lookups answer most questions.
Stop as soon as you have enough evidence and write the answer; more searching is not better.
"""
FINAL_NOTE = "(Note from the app, not from the user.)"
FINAL_NUDGE = (f"{FINAL_NOTE} Your research for this question is finished. Using only what you found above, write "
               "your final answer to the user's last message now. Do not call or write out any tools.")
FINAL_NUDGE_AGAIN = (f"{FINAL_NOTE} You did not write an answer. Write your answer to the user now, as plain text, "
                     "based on what you found. No tool calls.")


def _has_marker(text: str) -> bool:
    return any(m in text for m in MARKERS)


def _summary(name: str, data: dict) -> str:
    if "error" in data:
        return data["error"]
    if name == "search_archive":
        return f"{len(data.get('hits', []))} passages"
    if name == "read_document":
        return f"read {data['document']['id']}" + (f" + {len(data['context'])} related" if data.get("context") else "")
    if name == "find_mentions":
        return f"{data.get('total', 0)} documents"
    if name == "web_search":
        return f"{len(data.get('results', []))} results · {data.get('provider', '')}"
    if name == "fetch_page":
        return data["page"]["title"][:60]
    return "done"


def _tools_unsupported(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(s in msg for s in ("does not support tools", "tool use is not supported", "tools is not supported",
                                  "function calling is not", "tool_choice"))


class Agent:
    def __init__(self, retriever: Retriever, persona_name: str, max_rounds: int, http_client=None,
                 max_tool_calls: int = 12):
        self.retriever = retriever
        self.http_client = http_client  # injectable for tests
        self.tools = ToolRunner(retriever)
        self.persona_name = persona_name
        self.max_rounds = max_rounds
        self.max_tool_calls = max_tool_calls

    async def run(self, history: list[dict], config: LLMConfig, agent: str = "clone",
                  web: bool = False) -> AsyncIterator[Event]:
        """`agent` is "clone" (speaks as the author) or "analyst" (studies the author); `web` enables live web tools."""
        started = time.monotonic()
        client = AsyncOpenAI(base_url=config.base_url, api_key=config.api_key or "not-needed", timeout=180,
                             http_client=self.http_client)
        system = system_prompt(agent, self.persona_name, self.retriever.corpus.stats(), web) + BUDGET_NOTE.format(
            n=self.max_tool_calls)
        tools = TOOLS + WEB_TOOLS if web else TOOLS
        web_runner = WebToolRunner(config.search_provider, config.search_api_key)
        messages: list[dict] = [{"role": "system", "content": system}, *history]
        usage: dict[str, int] = {}
        use_tools = True
        calls_used = 0
        final = False  # once set, the model must answer from what it has
        retried_final = False

        for round_no in range(self.max_rounds + 2):
            if not final and (round_no >= self.max_rounds or calls_used >= self.max_tool_calls):
                final = True
                messages.append({"role": "user", "content": FINAL_NUDGE})
            content, tool_calls, finish_reason, reasoning = "", {}, None, ""
            leak = LeakFilter()
            request = dict(model=config.model, messages=messages, temperature=config.temperature, stream=True,
                           stream_options={"include_usage": True},
                           **({"max_tokens": config.max_tokens} if config.max_tokens else {}))
            if use_tools:
                # Tools stay listed on the final round (some models break when they disappear mid-
                # conversation); tool_choice="none" makes the model answer instead of calling them.
                request |= {"tools": tools, "tool_choice": "none" if final else "auto"}
            try:
                try:
                    stream = await client.chat.completions.create(**request)
                except BadRequestError:
                    if not (final and use_tools):
                        raise
                    # Provider doesn't accept tool_choice="none": answer without tools listed.
                    request.pop("tools"), request.pop("tool_choice")
                    stream = await client.chat.completions.create(**request)
                # Closing the stream also ends the upstream request when the user stops or leaves;
                # otherwise the provider keeps generating (and keeps credit reserved for it).
                async with stream:
                    async for chunk in stream:
                        if chunk.usage:
                            for k in ("prompt_tokens", "completion_tokens"):
                                usage[k] = usage.get(k, 0) + (getattr(chunk.usage, k, 0) or 0)
                        if not chunk.choices:
                            continue
                        finish_reason = chunk.choices[0].finish_reason or finish_reason
                        delta = chunk.choices[0].delta
                        # Ollama/vLLM/DeepSeek/OpenRouter expose thinking under different names.
                        thinking = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
                        if thinking:
                            reasoning += thinking
                            yield {"type": "reasoning", "text": thinking}
                        if delta.content and (visible := leak.feed(delta.content)):
                            content += visible
                            yield {"type": "token", "text": visible}
                        for tc in delta.tool_calls or []:
                            slot = tool_calls.setdefault(tc.index if tc.index is not None else len(tool_calls),
                                                         {"id": "", "name": "", "arguments": ""})
                            if tc.id:
                                slot["id"] = tc.id
                            if tc.function and tc.function.name:
                                slot["name"] += tc.function.name
                            if tc.function and tc.function.arguments:
                                slot["arguments"] += tc.function.arguments
                if rest := leak.flush():
                    content += rest
                    yield {"type": "token", "text": rest}
            except BadRequestError as exc:
                if use_tools and not final and _tools_unsupported(exc):
                    # The model can't call tools: retrieve once up front and answer from that.
                    use_tools = False
                    yield {"type": "notice", "message": f"{config.model} does not support tool calling; "
                                                        "falling back to automatic retrieval."}
                    async for event in self._fallback_retrieval(messages, history):
                        yield event
                    continue
                yield {"type": "error", "message": _api_error(exc)}
                return
            except APIError as exc:
                yield {"type": "error", "message": _api_error(exc)}
                return
            except Exception as exc:  # connection refused, DNS, timeouts...
                log.exception("LLM call failed")
                yield {"type": "error", "message": f"Could not reach the model at {config.base_url}: {exc}"}
                return

            # Tool calls written as text (in the answer or the reasoning) instead of as real tool calls.
            leaked_markup = leak.held or (reasoning if not content.strip() and _has_marker(reasoning) else "")
            if not tool_calls and leaked_markup:
                leaked = parse_leaked_calls(leaked_markup)
                log.info("round %d: model wrote %d tool call(s) as text", round_no, len(leaked))
                if leaked and not final:
                    tool_calls = {i: {"id": "", **c} for i, c in enumerate(leaked)}

            log.info("round %d: model=%s finish=%s content=%d chars tool_calls=%d calls_used=%d usage=%s", round_no,
                     config.model, finish_reason, len(content), len(tool_calls), calls_used, usage)

            if not tool_calls and not content.strip() and final and not retried_final:
                # Asked to answer but produced nothing (often: tried to call a tool anyway). Insist once.
                retried_final = True
                messages.append({"role": "user", "content": FINAL_NUDGE_AGAIN})
                continue
            if finish_reason == "length" and not tool_calls:
                # Thinking models spend the same budget on hidden reasoning, so they can run out
                # before writing anything. Say so instead of ending silently.
                limit = f"{config.max_tokens:,}-token" if config.max_tokens else "model's maximum"
                yield {"type": "notice", "message": (
                    f"The reply hit the {limit} length limit"
                    + (" while the model was still thinking, before it wrote an answer" if not content else "")
                    + ". Raise 'Max answer length' in Model settings (or choose 'No limit') and ask again."
                )}
            elif not tool_calls and not content.strip():
                yield {"type": "notice", "message": (
                    f"The model ended without writing an answer (finish reason: {finish_reason or 'none given'}). "
                    "Ask again, or try another model if this keeps happening."
                )}
            if not tool_calls:
                yield {"type": "done", "elapsed_ms": int((time.monotonic() - started) * 1000), "usage": usage}
                return

            calls = [tool_calls[i] for i in sorted(tool_calls)][: max(1, self.max_tool_calls - calls_used)]
            for i, call in enumerate(calls):
                call["id"] = call["id"] or f"call_{round_no}_{i}"
            messages.append({
                "role": "assistant", "content": content or None,
                "tool_calls": [{"id": c["id"], "type": "function",
                                "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}} for c in calls],
            })
            for call in calls:
                yield {"type": "tool_call", "id": call["id"], "name": call["name"], "arguments": _parse(call["arguments"])}
                t0 = time.monotonic()
                runner = web_runner if call["name"] in WEB_TOOL_NAMES else self.tools
                text, data = await asyncio.to_thread(runner.run, call["name"], call["arguments"])
                yield {"type": "tool_result", "id": call["id"], "name": call["name"], "summary": _summary(call["name"], data),
                       "data": data, "elapsed_ms": int((time.monotonic() - t0) * 1000)}
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": text})
            calls_used += len(calls)
            left = self.max_tool_calls - calls_used
            messages[-1]["content"] += (
                f"\n\n[{left} lookups left. Answer as soon as you have enough evidence.]" if left > 0 else
                "\n\n[No lookups left. Write your answer now.]"
            )
        # Out of rounds without an answer (should not happen: the final round forbids tools).
        yield {"type": "notice", "message": "The model kept trying to research instead of answering. Ask again."}
        yield {"type": "done", "elapsed_ms": int((time.monotonic() - started) * 1000), "usage": usage}

    async def _fallback_retrieval(self, messages: list[dict], history: list[dict]) -> AsyncIterator[Event]:
        last = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
        question = last if isinstance(last, str) else " ".join(
            p["text"] for p in last if p.get("type") == "text" and not p["text"].startswith(("<attachment", "[Attached")))
        call_id = "auto_search"
        yield {"type": "tool_call", "id": call_id, "name": "search_archive", "arguments": {"query": question}}
        t0 = time.monotonic()
        hits = await asyncio.to_thread(self.retriever.search, question, 10)
        data = {"hits": [doc_card(h.doc) | {"score": round(h.score, 4)} for h in hits]}
        yield {"type": "tool_result", "id": call_id, "name": "search_archive", "summary": _summary("search_archive", data),
               "data": data, "elapsed_ms": int((time.monotonic() - t0) * 1000)}
        excerpts = "\n\n".join(_for_model(h.doc) for h in hits) or "Nothing relevant found."
        messages[0] = {"role": "system", "content": messages[0]["content"] + FALLBACK_NOTE.format(excerpts=excerpts)}


def _parse(arguments: str) -> Any:
    try:
        return json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return arguments


def _api_error(exc: APIError) -> str:
    if getattr(exc, "status_code", None) == 402:
        return (f"The provider refused the request for lack of credit: {_raw_api_error(exc)} "
                "Lower 'Max answer length' in Model settings, or add credit.")
    return _raw_api_error(exc)


def _raw_api_error(exc: APIError) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
    return str(exc)
