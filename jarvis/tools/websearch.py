"""Web search via DuckDuckGo (free, no API key)."""


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
