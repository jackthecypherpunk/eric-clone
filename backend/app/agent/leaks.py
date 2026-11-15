"""Some models (notably DeepSeek through some providers) occasionally write their tool calls as raw markup
in the answer text instead of as structured tool calls, e.g.

    <｜DSML｜function_calls>
    <｜DSML｜invoke name="search_archive">
    <｜DSML｜parameter name="query" string="true">…</｜DSML｜parameter>

`LeakFilter` keeps that markup out of the streamed answer, and `parse_leaked_calls` turns it back into tool calls.
"""
from __future__ import annotations

import json
import re

MARKERS = ("<｜DSML｜", "<|DSML|", "<｜tool", "<|tool", "<tool_call>", "<function_calls>")
_INVOKE = re.compile(r"invoke\s+name=\"([^\"]+)\"\s*>(.*?)(?:</[^>]*invoke>|(?=<[^>]*invoke\s)|\Z)", re.S)
_PARAM = re.compile(r"parameter\s+name=\"([^\"]+)\"(?:\s+string=\"(true|false)\")?\s*>(.*?)</[^>]*parameter>", re.S)
_TOOL_CALL_JSON = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)


class LeakFilter:
    """Streams text through, but holds back everything from the first tool-call marker onwards."""

    def __init__(self) -> None:
        self._pending = ""  # text that might be the start of a marker
        self.held = ""  # markup that was kept out of the answer
        self.holding = False

    def feed(self, text: str) -> str:
        if self.holding:
            self.held += text
            return ""
        buf = self._pending + text
        hits = [i for m in MARKERS if (i := buf.find(m)) != -1]
        if hits:
            i = min(hits)
            self.held, self.holding, self._pending = buf[i:], True, ""
            return buf[:i]
        # Keep back a tail that could still grow into a marker in the next chunk.
        keep = max((n for m in MARKERS for n in range(1, len(m)) if buf.endswith(m[:n])), default=0)
        self._pending = buf[len(buf) - keep:] if keep else ""
        return buf[: len(buf) - keep]

    def flush(self) -> str:
        out, self._pending = self._pending, ""
        return out


def parse_leaked_calls(markup: str) -> list[dict]:
    """Returns [{"name", "arguments"(JSON string)}] found in leaked markup."""
    calls = []
    for name, body in _INVOKE.findall(markup):
        args = {}
        for key, is_string, value in _PARAM.findall(body):
            value = value.strip()
            if is_string == "false":
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    pass
            args[key] = value
        calls.append({"name": name.strip(), "arguments": json.dumps(args, ensure_ascii=False)})
    for raw in _TOOL_CALL_JSON.findall(markup):
        try:
            obj = json.loads(raw)
            calls.append({"name": obj["name"], "arguments": json.dumps(obj.get("arguments", {}), ensure_ascii=False)})
        except (json.JSONDecodeError, KeyError):
            continue
    return calls
