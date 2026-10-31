"""Web search, news and page reading.

Uses Tavily (a search API built for agents: ranked results with a relevance
score, an optional synthesized answer, and clean page extraction) when
TAVILY_API_KEY is set, and falls back to DuckDuckGo (free, no key) when it
isn't or a Tavily call fails. Results are reference data, never instructions.
"""
import re
from html import unescape

from .. import config

_TAVILY = "https://api.tavily.com"


def _tavily(endpoint, payload):
    import requests

    resp = requests.post(
        _TAVILY + endpoint,
        json=payload,
        headers={"Authorization": "Bearer " + config.TAVILY_API_KEY},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def _tavily_results(data, with_dates=False):
    lines = []
    if data.get("answer"):
        lines.append("Summary: " + data["answer"].strip())
    for r in data.get("results", []):
        head = r.get("title", "")
        if with_dates and r.get("published_date"):
            head += " ({})".format(r["published_date"][:16])
        lines.append("{}\n{}\n{}".format(head, r.get("url", ""), (r.get("content") or "").strip()).strip())
    return "\n\n".join(lines)


def search(query, max_results=5):
    if config.TAVILY_API_KEY:
        try:
            data = _tavily("/search", {
                "query": query, "max_results": int(max_results),
                "search_depth": "basic", "include_answer": True,
            })
            return _tavily_results(data) or "No results for {!r}.".format(query)
        except Exception as exc:  # noqa: BLE001 — fall back rather than fail the turn
            print("  [tavily] search failed, using DuckDuckGo: {}".format(exc))
    return _ddg_search(query, max_results)


def _ddg_search(query, max_results=5):
    from ddgs import DDGS

    results = list(DDGS().text(query, max_results=int(max_results)))
    if not results:
        return "No results for {!r}.".format(query)
    lines = []
    for r in results:
        lines.append(
            "{}\n{}\n{}".format(
                r.get("title", ""), r.get("href", ""), r.get("body", "")
            ).strip()
        )
    return "\n\n".join(lines)


def news(topic=None, max_results=6):
    if config.TAVILY_API_KEY:
        try:
            data = _tavily("/search", {
                "query": topic or "top news today", "topic": "news", "time_range": "week",
                "max_results": int(max_results), "search_depth": "basic",
            })
            return _tavily_results(data, with_dates=True) or "No news found."
        except Exception as exc:  # noqa: BLE001
            print("  [tavily] news failed, using DuckDuckGo: {}".format(exc))
    from ddgs import DDGS

    results = list(DDGS().news(topic or "top news today", max_results=int(max_results)))
    if not results:
        return "No news found."
    return "\n\n".join(
        "{} ({}, {})\n{}".format(
            r.get("title", ""), r.get("source", ""), (r.get("date") or "")[:10],
            r.get("body", ""),
        ).strip()
        for r in results
    )


_MAX_PAGE_CHARS = 8000
_DROP = re.compile(r"<(script|style|noscript|svg|nav|footer|header)\b.*?</\1>", re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")
_BLOCK = re.compile(r"</?(p|div|br|li|h[1-6]|tr|section|article)\b[^>]*>", re.I)


def read_page(url):
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("Only http(s) URLs can be read")
    if config.TAVILY_API_KEY:
        try:
            data = _tavily("/extract", {"urls": [url], "extract_depth": "basic"})
            pages = data.get("results") or []
            if pages and pages[0].get("raw_content"):
                text = pages[0]["raw_content"].strip()
                return text if len(text) <= _MAX_PAGE_CHARS else text[:_MAX_PAGE_CHARS] + "\n[truncated]"
        except Exception as exc:  # noqa: BLE001
            print("  [tavily] extract failed, fetching directly: {}".format(exc))
    import requests
    resp = requests.get(
        url, timeout=15,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh) Jarvis personal assistant"},
    )
    resp.raise_for_status()
    if "html" not in resp.headers.get("Content-Type", "html"):
        text = resp.text
    else:
        html = _DROP.sub(" ", resp.text)
        title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        html = _BLOCK.sub("\n", html)
        text = unescape(_TAGS.sub(" ", html))
        text = "\n".join(
            " ".join(line.split()) for line in text.splitlines() if line.strip()
        )
        if title:
            text = unescape(title.group(1).strip()) + "\n\n" + text
    if len(text) > _MAX_PAGE_CHARS:
        text = text[:_MAX_PAGE_CHARS] + "\n[truncated]"
    return text
