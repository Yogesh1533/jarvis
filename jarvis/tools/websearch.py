"""Web search, news (DuckDuckGo, free, no API key) and page reading."""
import re
from html import unescape


def search(query, max_results=5):
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
    import requests

    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("Only http(s) URLs can be read")
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
