"""Fast tests that need no model downloads: parsing, chunking, filtering, tools and the agent loop."""
from __future__ import annotations

import asyncio
import json

import httpx

from app.agent.runner import Agent
from app.agent.runtime_config import LLMConfig
from app.agent.tools import ToolRunner
from app.ingest.documents import Document
from app.ingest.pdf import _DATE_LINE, _parse_date, chunk_post
from app.rag.corpus import Corpus
from app.rag.index import windows_for
from app.rag.retriever import Filters, Hit
from app.text import fold, normalize, tokenize


def test_normalize_unifies_arabic_letters_and_digits():
    assert normalize("كتاب يك ۱۴۰۲") == "کتاب یک 1402"
    assert fold("می‌گویند") == fold("میگویند")


def test_tokenize_drops_short_tokens():
    assert tokenize("من و دولت، مالیات!") == ["من", "دولت", "مالیات"]


def test_pdf_date_line_formats():
    for line, iso in [("آوریل9 ,2012", "2012-04-09"), ("ژانویه 19 ,2012", "2012-01-19"), ("می 16 ,2011", "2011-05-16")]:
        m = _DATE_LINE.match(line)
        assert m, line
        assert _parse_date(m) == iso
    assert not _DATE_LINE.match("هفت ژوئن2011 شروع شد")


def test_chunk_post_respects_size_and_overlaps():
    sentences = [(1, f"جمله شماره {i} اینجاست.") for i in range(200)]
    chunks = chunk_post(sentences, size=300, overlap=60)
    assert len(chunks) > 5
    assert all(len(text) <= 300 for _, text in chunks)
    # the start of each chunk repeats the tail of the previous one
    assert chunks[1][1].split(".")[0] in chunks[0][1]


def _doc(i: int, text: str, date: str, source_type: str = "telegram", **meta) -> Document:
    return Document(id=f"tg:x:{i}", text=text, source_type=source_type, source="X", date=date,
                    meta={"channel_slug": "x", "message_id": i, **meta})


def test_long_posts_get_several_windows_but_one_doc():
    long = _doc(1, "\n".join("این یک جمله نسبتا طولانی است." for _ in range(200)), "2020-01-01")
    windows = windows_for(long, 1400)
    assert len(windows) > 1
    assert {w.doc.id for w in windows} == {"tg:x:1"}
    assert windows_for(_doc(2, "کوتاه", "2020-01-01"), 1400)[0].id == "tg:x:2#w0"


def test_filters():
    f = Filters(source_type="telegram", date_from="2020", date_to="2021-06")
    assert f.accepts(_doc(1, "a", "2020-01-01T10:00:00"))
    assert f.accepts(_doc(1, "a", "2021-06-30"))
    assert not f.accepts(_doc(1, "a", "2021-07-01"))
    assert not f.accepts(_doc(1, "a", "2020-05-05", source_type="weblog"))
    assert f.chroma_where() == {"$and": [{"source_type": "telegram"}, {"date_int": {"$gte": 20200101}},
                                         {"date_int": {"$lte": 20210631}}]}


class FakeRetriever:
    def __init__(self, docs):
        self.corpus = Corpus(docs)

    def search(self, query, k=8, filters=None):
        return [Hit(doc=d, score=1.0) for d in self.corpus.docs if (filters or Filters()).accepts(d)][:k]


DOCS = [
    _doc(1, "دولت دزد است و مالیات هم.", "2019-01-01"),
    _doc(2, "پاسخ به پست قبلی درباره مالیات", "2019-01-02", reply_to="tg:x:1"),
    _doc(3, "آخوند و دولت", "2023-05-05"),
]


def test_tools_read_and_mentions():
    tools = ToolRunner(FakeRetriever(DOCS))
    text, data = tools.run("read_document", '{"doc_id": "tg:x:2"}')
    assert "This post of yours replies to" in text and data["context"][0]["relation"] == "replied to"
    _, data = tools.run("find_mentions", {"phrase": "دولت"})
    assert data["total"] == 2 and data["by_year"] == {"2019": 1, "2023": 1}
    _, data = tools.run("search_archive", {"query": "x", "date_from": "2023"})
    assert [h["id"] for h in data["hits"]] == ["tg:x:3"]
    assert "error" in tools.run("nope", "{}")[1]


def _sse(chunks: list[dict]) -> bytes:
    return "".join(f"data: {json.dumps(c)}\n\n" for c in chunks).encode() + b"data: [DONE]\n\n"


def _chunk(delta: dict, finish=None) -> dict:
    return {"id": "c", "object": "chat.completion.chunk", "created": 0, "model": "m",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


def test_agent_loop_streams_tool_calls_then_answer():
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:  # first round: the model calls search_archive, arguments split across chunks
            chunks = [
                _chunk({"role": "assistant", "tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                                                              "function": {"name": "search_archive", "arguments": '{"query": "مال'}}]}),
                _chunk({"tool_calls": [{"index": 0, "function": {"arguments": 'یات"}'}}]}),
                _chunk({}, "tool_calls"),
            ]
        else:  # second round: answer with a citation
            chunks = [_chunk({"content": "دولت دزده "}), _chunk({"content": "[[tg:x:1]]"}), _chunk({}, "stop")]
        return httpx.Response(200, content=_sse(chunks), headers={"content-type": "text/event-stream"})

    agent = Agent(FakeRetriever(DOCS), "Eric", max_rounds=3,
                  http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    async def collect():
        return [e async for e in agent.run([{"role": "user", "content": "مالیات؟"}],
                                           LLMConfig(base_url="http://fake/v1", model="m"))]

    events = asyncio.run(collect())
    types = [e["type"] for e in events]
    assert types == ["tool_call", "tool_result", "token", "token", "done"]
    assert events[0]["arguments"] == {"query": "مالیات"}
    assert events[1]["summary"] == "3 passages"
    # the tool result was fed back to the model in the second request
    second = requests[1]["messages"]
    assert second[-2]["tool_calls"][0]["function"]["name"] == "search_archive"
    assert second[-1]["role"] == "tool" and "[[tg:x:1]]" in second[-1]["content"]
    assert "tools" in requests[0] and "Eric" in requests[0]["messages"][0]["content"]
    # an explicit output cap, so providers don't reserve credit for the model's full output limit
    assert requests[0]["max_tokens"] == 8192


def test_key_hint_never_reveals_the_key():
    from app.agent.runtime_config import key_hint

    assert key_hint("") == ""
    assert key_hint("sk-or-v1-abcdefgh1234") == "••••••••1234"
    assert key_hint("short") == "••••••••"


def test_fetch_page_blocks_local_addresses():
    import pytest

    from app.agent import web

    for url in ("http://127.0.0.1:8000/api/status", "http://localhost/", "http://10.0.0.1/", "file:///etc/passwd"):
        with pytest.raises(web.WebError):
            web.fetch_page(url)


def test_attachments_text_image_and_unsupported(tmp_path):
    import io

    import pytest
    from PIL import Image

    from app.attachments import AttachmentStore, UnsupportedFile
    from app.config import Settings

    store = AttachmentStore(Settings(data_dir=tmp_path, max_attachment_chars=10))
    txt = store.save("notes.md", "سلام دنیا، این یک یادداشت است".encode())
    buf = io.BytesIO()
    Image.new("RGB", (4000, 1000)).save(buf, "PNG")
    img = store.save("big.png", buf.getvalue())
    assert img["kind"] == "image" and img["width"] == 1568
    parts = store.content_parts([txt["id"], img["id"], "f" * 32])
    assert "truncated" in parts[0]["text"] and parts[2]["type"] == "image_url"
    assert "no longer available" in parts[3]["text"]
    with pytest.raises(UnsupportedFile):
        store.save("clip.mp4", b"0000")


def test_agent_kind_and_web_toggle_change_prompt_and_tools():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=_sse([_chunk({"content": "ok"}), _chunk({}, "stop")]),
                              headers={"content-type": "text/event-stream"})

    agent = Agent(FakeRetriever(DOCS), "Eric", max_rounds=2,
                  http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    cfg = LLMConfig(base_url="http://fake/v1", model="m")
    user = [{"role": "user", "content": [{"type": "text", "text": "hi"},
                                         {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}}]}]

    async def go(kind, web):
        return [e async for e in agent.run(user, cfg, kind, web)]

    asyncio.run(go("clone", False))
    asyncio.run(go("analyst", True))
    clone, analyst = seen
    tool_names = lambda req: {t["function"]["name"] for t in req["tools"]}
    assert "web_search" not in tool_names(clone) and {"web_search", "fetch_page"} <= tool_names(analyst)
    assert "speaking for yourself" in clone["messages"][0]["content"]
    assert "You are NOT Eric" in analyst["messages"][0]["content"]
    assert analyst["messages"][1]["content"][1]["type"] == "image_url"  # multimodal content passed through


def test_stopping_an_answer_closes_the_upstream_request():
    closed = asyncio.Event()

    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for i in range(1000):
                yield f"data: {json.dumps(_chunk({'content': f'token{i} '}))}\n\n".encode()
                await asyncio.sleep(0.01)

        async def aclose(self):
            closed.set()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=SlowStream(), headers={"content-type": "text/event-stream"})

    agent = Agent(FakeRetriever(DOCS), "Eric", max_rounds=1,
                  http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    async def go():
        gen = agent.run([{"role": "user", "content": "hi"}], LLMConfig(base_url="http://fake/v1", model="m"))
        assert (await gen.__anext__())["type"] == "token"
        await gen.aclose()  # what happens when the browser disconnects mid-answer
        await asyncio.wait_for(closed.wait(), 1)

    asyncio.run(go())


def test_no_limit_option_and_length_notice():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        # a thinking model that spends the whole budget reasoning and never writes an answer
        chunks = [_chunk({"reasoning_content": "thinking…"}), _chunk({}, "length")]
        return httpx.Response(200, content=_sse(chunks), headers={"content-type": "text/event-stream"})

    agent = Agent(FakeRetriever(DOCS), "Eric", max_rounds=1,
                  http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    async def go(max_tokens):
        cfg = LLMConfig(base_url="http://fake/v1", model="m", max_tokens=max_tokens)
        return [e async for e in agent.run([{"role": "user", "content": "hi"}], cfg)]

    events = asyncio.run(go(0))
    assert "max_tokens" not in seen[0]  # "No limit" sends no cap
    notice = next(e for e in events if e["type"] == "notice")["message"]
    assert "still thinking" in notice and events[-1]["type"] == "done"
    asyncio.run(go(2048))
    assert seen[1]["max_tokens"] == 2048


def test_empty_answer_gets_a_notice():
    def handler(request: httpx.Request) -> httpx.Response:
        chunks = [_chunk({"reasoning_content": "hmm"}), _chunk({}, "stop")]
        return httpx.Response(200, content=_sse(chunks), headers={"content-type": "text/event-stream"})

    agent = Agent(FakeRetriever(DOCS), "Eric", max_rounds=1,
                  http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    async def go():
        return [e async for e in agent.run([{"role": "user", "content": "hi"}],
                                           LLMConfig(base_url="http://fake/v1", model="m"))]

    notice = next(e for e in asyncio.run(go()) if e["type"] == "notice")["message"]
    assert "without writing an answer" in notice and "stop" in notice


def test_leak_filter_hides_markup_split_across_chunks():
    from app.agent.leaks import LeakFilter, parse_leaked_calls

    f = LeakFilter()
    text = ('بخشی از جواب. <｜DSML｜function_calls>\n<｜DSML｜invoke name="search_archive">\n'
            '<｜DSML｜parameter name="query" string="true">امید</｜DSML｜parameter>\n'
            '<｜DSML｜parameter name="limit" string="false">5</｜DSML｜parameter>\n</｜DSML｜invoke>')
    shown = "".join(f.feed(text[i:i + 3]) for i in range(0, len(text), 3)) + f.flush()
    assert shown == "بخشی از جواب. "
    calls = parse_leaked_calls(f.held)
    assert calls == [{"name": "search_archive", "arguments": '{"query": "امید", "limit": 5}'}]


def _scripted_agent(script, **kw):
    """Agent whose model replies with script[i] (a list of deltas + finish reason) on request i."""
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        deltas, finish = script[min(len(requests) - 1, len(script) - 1)]
        chunks = [_chunk(d) for d in deltas] + [_chunk({}, finish)]
        return httpx.Response(200, content=_sse(chunks), headers={"content-type": "text/event-stream"})

    agent = Agent(FakeRetriever(DOCS), "Eric", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kw)

    async def go():
        return [e async for e in agent.run([{"role": "user", "content": "q"}], LLMConfig(base_url="http://f/v1", model="m"))]

    return asyncio.run(go()), requests


def test_tool_calls_leaked_into_reasoning_are_executed():
    markup = '<｜DSML｜invoke name="search_archive"><｜DSML｜parameter name="query" string="true">x</｜DSML｜parameter></｜DSML｜invoke>'
    events, _ = _scripted_agent([([{"reasoning_content": "let me search " + markup}], "stop"),
                                 ([{"content": "جواب"}], "stop")], max_rounds=3)
    assert [e["type"] for e in events if e["type"] in ("tool_call", "tool_result", "token")] == ["tool_call", "tool_result", "token"]


def test_budget_forces_a_final_answer_without_tools():
    call = {"tool_calls": [{"index": 0, "id": "c", "type": "function",
                            "function": {"name": "search_archive", "arguments": '{"query": "x"}'}}]}
    events, requests = _scripted_agent([([call], "tool_calls"), ([call], "tool_calls"), ([{"content": "done"}], "stop")],
                                       max_rounds=6, max_tool_calls=2)
    assert sum(e["type"] == "tool_call" for e in events) == 2
    final = requests[-1]
    assert final["tool_choice"] == "none" and "research for this question is finished" in final["messages"][-1]["content"]
    assert events[-1]["type"] == "done" and any(e["type"] == "token" for e in events)


def test_empty_final_answer_is_retried_once():
    call = {"tool_calls": [{"index": 0, "id": "c", "type": "function",
                            "function": {"name": "search_archive", "arguments": '{"query": "x"}'}}]}
    events, requests = _scripted_agent([([call], "tool_calls"), ([{"reasoning_content": "hmm"}], "stop"),
                                        ([{"content": "answer"}], "stop")], max_rounds=1)
    assert "did not write an answer" in requests[-1]["messages"][-1]["content"]
    assert "".join(e["text"] for e in events if e["type"] == "token") == "answer"
