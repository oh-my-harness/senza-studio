"""Prefab manifest + lookup functions.

Richer than a project's `tools/registry.py` contract (`get_tools() ->
{name: callable}`) because `list_prefabs`/`search_prefabs`/
`recommend_prefabs` need descriptive metadata (description, JSON-schema
parameters) to be useful to the meta-agent — `get_tools()` below is
derived from this manifest for compatibility with the calling convention
`play.py` already uses.
"""
from __future__ import annotations

import re
from typing import Callable

_WORD_RE = re.compile(r"[a-z0-9_]+")

# 用户描述需求时几乎必然出现、但对区分工具毫无帮助的词——不滤掉的话，
# 描述写得越长的工具越容易靠这些噪声词蹭到分数（见 recommend_prefabs）。
_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "from", "that", "this", "have", "has", "was",
        "are", "get", "got", "not", "need", "needs", "needed", "want", "wants",
        "would", "should", "could", "can", "will", "use", "using", "used", "make",
        "made", "some", "any", "all", "into", "out", "about", "their", "there",
        "then", "than", "when", "where", "what", "which", "who", "how", "why",
        "step", "steps", "workflow", "agent", "tool", "tools", "prefab", "prefabs",
        "data", "info", "information", "thing", "things", "part", "way", "help",
    }
)

from .tools import db_query, lookup_topic, send_email

PREFABS: list[dict] = [
    {
        "name": "db_query",
        "kind": "tool",
        "description": (
            "Run a read-only SELECT query against a SQLite database file and "
            "return the matching rows. Rejects non-SELECT statements."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "db_path": {"type": "string", "description": "Path to the SQLite database file"},
                "query": {"type": "string", "description": "A single read-only SELECT statement"},
            },
            "required": ["db_path", "query"],
        },
        "callback": db_query.run,
    },
    {
        "name": "lookup_topic",
        "kind": "tool",
        "description": (
            "Look up an encyclopedia-style summary for a NAMED TOPIC (e.g. 'France', "
            "'Eiffel Tower', 'Python programming language') via DuckDuckGo's Instant "
            "Answer API. No API key needed. This is NOT a web search and does NOT "
            "answer questions — 'capital of France' returns nothing, 'France' returns "
            "an abstract. Pass a noun phrase naming a thing, and check the returned "
            "'found' field, since many topics have no entry. If you need real ranked "
            "web search results, no prefab covers that yet."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "A noun phrase naming a topic/entity, NOT a question",
                },
            },
            "required": ["topic"],
        },
        "callback": lookup_topic.run,
    },
    {
        "name": "send_email",
        "kind": "tool",
        "description": (
            "Send an email via SMTP. Requires the deploying user to configure "
            "SENZA_SMTP_HOST/PORT/USER/PASSWORD environment variables."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body text"},
            },
            "required": ["to", "subject", "body"],
        },
        "callback": send_email.run,
    },
]


def get_tools() -> dict[str, Callable]:
    """{name: callable} — same calling convention as a project's tools/registry.py,
    so play.py can merge this in without any special-casing."""
    return {p["name"]: p["callback"] for p in PREFABS}


def _public_fields(p: dict) -> dict:
    return {"name": p["name"], "kind": p["kind"], "description": p["description"], "parameters": p["parameters"]}


def list_prefabs(kind: str | None = None) -> dict:
    """Returns {"tools": [...], "components": []} — capability components are a
    later slice (they need the spec preprocessor, which doesn't exist yet)."""
    tools = [_public_fields(p) for p in PREFABS if kind in (None, "all", p["kind"])]
    return {"tools": tools, "components": []}


def search_prefabs(query: str) -> list[dict]:
    """Case-insensitive substring match over name + description — no embedding
    search or ranking model, just a plain keyword filter."""
    q = query.lower().strip()
    if not q:
        return []
    return [
        _public_fields(p)
        for p in PREFABS
        if q in p["name"].lower() or q in p["description"].lower()
    ]


def recommend_prefabs(description: str) -> list[dict]:
    """v1: a weighted whole-word-overlap heuristic between the stated need and
    each prefab's name/description.

    Three deliberate refinements over naive overlap counting, each fixing a
    real misranking observed while building this:

    1. Whole-word (not substring) matching — substring matching gives false
       hits like "need" inside "needed".
    2. Stopword filtering — generic words the user's phrasing always contains
       ("need", "want", "data", "use"...) match noise in any sufficiently long
       description and drown out the real signal.
    3. Name matches weigh more than description matches — otherwise simply
       writing a longer description makes a prefab outrank better matches
       (observed: lengthening lookup_topic's description alone made it beat
       send_email on an explicitly email-about-notifying-a-customer query).

    A real recommender (embeddings / LLM ranking) is future work; this stays
    intentionally simple rather than pretending to be more than it is.
    """
    words = {
        w
        for w in _WORD_RE.findall(description.lower())
        if len(w) > 2 and w not in _STOPWORDS
    }
    if not words:
        return []
    scored: list[tuple[int, dict]] = []
    for p in PREFABS:
        name_words = set(_WORD_RE.findall(p["name"].lower()))
        desc_words = set(_WORD_RE.findall(p["description"].lower()))
        score = 3 * len(words & name_words) + len(words & desc_words)
        if score > 0:
            scored.append((score, p))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [_public_fields(p) for _, p in scored]
