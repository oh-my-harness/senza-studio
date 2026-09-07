"""lookup_topic — encyclopedia-style summary for a named topic. No API key.

**This is NOT a web search.** It queries DuckDuckGo's Instant Answer API,
which only has entries for *named entities/topics* (mostly Wikipedia
abstracts) — it does not answer questions and does not return ranked search
results.

Verified behavior against the live API:
  "France"           -> full Wikipedia abstract
  "Eiffel Tower"     -> full Wikipedia abstract
  "capital of France" -> completely empty (the API returns no fields at all)

So callers must pass a noun phrase naming a thing ("France"), not a question
("what is the capital of France"). When there's no entry, `found` is False
and `answer` is empty — check `found` rather than assuming a hit.

If you need real web search (ranked results for arbitrary queries), that
needs a keyed search API — this tool cannot do it.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

_ENDPOINT = "https://api.duckduckgo.com/"
_TIMEOUT_SECONDS = 10


class LookupTopicError(RuntimeError):
    pass


def run(args: dict) -> dict:
    """args: {"topic": str}. Returns {"topic", "found", "answer", "source_url", "related"}."""
    topic = args.get("topic") or args.get("query")  # accept "query" as a legacy alias
    if not topic:
        raise LookupTopicError("topic is required")

    params = urllib.parse.urlencode(
        {"q": topic, "format": "json", "no_html": "1", "skip_disambig": "1"}
    )
    url = f"{_ENDPOINT}?{params}"

    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise LookupTopicError(f"lookup_topic request failed: {exc}") from exc

    answer = data.get("AbstractText") or data.get("Answer") or ""
    related = [
        {"text": t.get("Text"), "url": t.get("FirstURL")}
        for t in data.get("RelatedTopics", [])
        if isinstance(t, dict) and t.get("Text")
    ][:5]

    found = bool(answer or related)
    return {
        "topic": topic,
        "found": found,
        # Empty results are common and are NOT an error — say so explicitly
        # rather than handing back a silently blank string that looks like a
        # bug to whoever reads the step output.
        "answer": answer
        or (
            ""
            if found
            else f"No encyclopedia entry found for '{topic}'. "
            f"This tool only looks up named topics (e.g. 'France'), not questions."
        ),
        "source_url": data.get("AbstractURL") or "",
        "related": related,
    }
