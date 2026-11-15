"""Optional live web access for the agents: search (Tavily / Brave / DuckDuckGo) and page reading."""
from __future__ import annotations

import io
import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlparse

import httpx

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
MAX_PAGE_BYTES = 4_000_000
MAX_PAGE_CHARS = 12_000
_RECENCY = {"day": ("d", "pd", 1), "week": ("w", "pw", 7), "month": ("m", "pm", 31), "year": ("y", "py", 365)}


class WebError(Exception):
    pass


def resolve_provider(provider: str, api_key: str) -> str:
    if provider != "auto":
        return provider
    if not api_key:
        return "duckduckgo"
    return "tavily" if api_key.startswith("tvly-") else "brave"


def search(query: str, provider: str, api_key: str, max_results: int = 6, recency: str | None = None,
           news: bool = False) -> list[dict]:
    """Returns [{title, url, snippet, date}] from the chosen provider."""
    provider = resolve_provider(provider, api_key)
    max_results = max(1, min(max_results, 10))
    if provider in ("tavily", "brave") and not api_key:
        raise WebError(f"{provider} needs an API key (set it in Model settings → Web search).")
    if provider == "tavily":
        body = {"query": query, "search_depth": "advanced", "max_results": max_results,
                "topic": "news" if news else "general", "api_key": api_key}
        if recency in _RECENCY:
            body["days"] = _RECENCY[recency][2]
        res = httpx.post("https://api.tavily.com/search", json=body, timeout=30,
                         headers={"Authorization": f"Bearer {api_key}"})
        res.raise_for_status()
        return [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", ""),
                 "date": r.get("published_date") or ""} for r in res.json().get("results", [])]
    if provider == "brave":
        params = {"q": query, "count": max_results}
        if recency in _RECENCY:
            params["freshness"] = _RECENCY[recency][1]
        res = httpx.get("https://api.search.brave.com/res/v1/web/search", params=params, timeout=20,
                        headers={"X-Subscription-Token": api_key, "Accept": "application/json"})
        res.raise_for_status()
        return [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("description", ""),
                 "date": r.get("page_age") or r.get("age") or ""} for r in res.json().get("web", {}).get("results", [])]

    from ddgs import DDGS

    kwargs = {"max_results": max_results}
    if recency in _RECENCY:
        kwargs["timelimit"] = _RECENCY[recency][0]
    with DDGS() as ddg:
        rows = ddg.news(query, **kwargs) if news else ddg.text(query, **kwargs)
    return [{"title": r.get("title", ""), "url": r.get("url") or r.get("href", ""), "snippet": r.get("body", ""),
             "date": r.get("date", "")} for r in rows or []]


def _check_public(url: str) -> None:
    """Refuse anything that is not a public http(s) address, so the model can't reach this machine or the LAN."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise WebError("Only public http(s) URLs can be opened.")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise WebError(f"Could not resolve {parsed.hostname}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise WebError("That address points to a private or local network and was blocked.")


def fetch_page(url: str) -> dict:
    """Downloads a public page and returns its main text (HTML via trafilatura, PDFs via pypdf)."""
    with httpx.Client(timeout=25, headers={"User-Agent": UA}, follow_redirects=False) as client:
        for _ in range(5):  # follow redirects by hand so every hop is checked
            _check_public(url)
            with client.stream("GET", url) as res:
                if res.is_redirect:
                    url = urljoin(url, res.headers.get("location", ""))
                    continue
                res.raise_for_status()
                body = b""
                for chunk in res.iter_bytes():
                    body += chunk
                    if len(body) > MAX_PAGE_BYTES:
                        break
                ctype = res.headers.get("content-type", "")
            break
        else:
            raise WebError("Too many redirects.")

    if "pdf" in ctype or url.lower().endswith(".pdf"):
        from pypdf import PdfReader

        text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(body)).pages[:40])
        title = urlparse(url).path.rsplit("/", 1)[-1]
    else:
        import trafilatura

        html = body.decode(res.encoding or "utf-8", errors="replace")
        text = trafilatura.extract(html, url=url, include_comments=False, favor_recall=True) or ""
        meta = trafilatura.extract_metadata(html, default_url=url)
        title = (meta.title if meta else "") or url
    text = text.strip()
    if not text:
        raise WebError("No readable text on that page.")
    truncated = len(text) > MAX_PAGE_CHARS
    return {"url": url, "title": title, "text": text[:MAX_PAGE_CHARS], "truncated": truncated}
