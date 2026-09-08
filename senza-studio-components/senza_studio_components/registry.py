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

from .components import approval_flow, approval_with_notice
from .tools import db_query, lookup_topic, send_email

PREFABS: list[dict] = [
    {
        "name": "db_query",
        "kind": "tool",
        "keywords": ["数据库", "查询", "查数据", "sql", "sqlite", "表", "select"],
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
        "keywords": ["查资料", "百科", "词条", "简介", "encyclopedia", "wikipedia"],
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
        "keywords": ["邮件", "发邮件", "邮箱", "通知", "email", "smtp", "notify"],
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

# 能力组件——一组 step + 内部连线，spec 里用 `component: <name>` 引用，
# Studio 的 preprocess.py 在编译前展开成真正的 step。定义本身只是数据，
# 展开逻辑和校验都在 Studio 侧（组件包不该依赖 Studio 的 spec 语义）。
COMPONENTS: list[dict] = [
    approval_flow.COMPONENT,
    approval_with_notice.COMPONENT,
]


def get_components() -> dict[str, dict]:
    """{name: definition} —— preprocess.py 展开时按名字查这张表。"""
    return {c["name"]: c for c in COMPONENTS}


def get_component(name: str) -> dict | None:
    return get_components().get(name)


def _component_public_fields(c: dict) -> dict:
    """给元 agent 看的投影——不含 steps/edges/ports 这些展开细节：spec 里
    只写引用，元 agent 需要知道的是"这个组件干什么、要填什么参数、有哪些
    出口"，内部结构是预处理器的事。"""
    return {
        "name": c["name"],
        "kind": "component",
        "description": c["description"],
        "params": c.get("params", {}),
        "ports": sorted(c.get("ports", {}).get("exits", {})),
    }


def get_tools() -> dict[str, Callable]:
    """{name: callable} — same calling convention as a project's tools/registry.py,
    so play.py can merge this in without any special-casing."""
    return {p["name"]: p["callback"] for p in PREFABS}


def _public_fields(p: dict) -> dict:
    return {"name": p["name"], "kind": p["kind"], "description": p["description"], "parameters": p["parameters"]}


def list_prefabs(kind: str | None = None) -> dict:
    """Returns {"tools": [...], "components": [...]}.

    kind filters to one family ("tool" / "component"); None or "all" returns
    both. The two families are returned under separate keys rather than one
    flat list because they enter a spec differently — a tool is bound to an
    existing step (``tool: db_query``), a component *becomes* steps
    (``component: approval_flow``).
    """
    tools = (
        [_public_fields(p) for p in PREFABS]
        if kind in (None, "all", "tool")
        else []
    )
    components = (
        [_component_public_fields(c) for c in COMPONENTS]
        if kind in (None, "all", "component")
        else []
    )
    return {"tools": tools, "components": components}


def _keywords(definition: dict) -> list[str]:
    """人工挑的检索词，补充 name/description 覆盖不到的说法。

    最主要是解决中文检索：description 是英文的（要喂给模型），而 Studio 的
    用户是用中文描述需求的，元 agent 转述时也常常直接用中文调
    recommend_prefabs。没有这一层的话，"需要有人工审批" 一条都匹配不到——
    _WORD_RE 是 [a-z0-9_]+，中文根本切不出词（亲测返回空列表）。
    """
    return [k.lower() for k in definition.get("keywords", [])]


def _keyword_score(definition: dict, text: str) -> int:
    """命中一个检索词记 3 分——和 name 命中同权重，因为检索词是人工挑的，
    信号比描述里碰巧出现的词强。

    中文按子串匹配（中文没有词边界，切不出词）；英文检索词仍按整词匹配，
    避免退回 "need" 命中 "needed" 那种误匹配。
    """
    score = 0
    words = set(_WORD_RE.findall(text))
    for keyword in _keywords(definition):
        if keyword.isascii():
            if keyword in words:
                score += 3
        elif keyword in text:
            score += 3
    return score


def _searchable() -> list[tuple[dict, dict]]:
    """[(定义, 对外投影)] —— 工具和能力组件都能被搜到/被推荐。两者的对外
    投影字段不一样（工具有 parameters，组件有 params/ports），靠每条自带的
    kind 区分。"""
    return [(p, _public_fields(p)) for p in PREFABS] + [
        (c, _component_public_fields(c)) for c in COMPONENTS
    ]


def search_prefabs(query: str) -> list[dict]:
    """Case-insensitive substring match over name + description, across both
    tools and capability components — no embedding search or ranking model,
    just a plain keyword filter."""
    q = query.lower().strip()
    if not q:
        return []
    return [
        public
        for definition, public in _searchable()
        if q in definition["name"].lower()
        or q in definition["description"].lower()
        or any(q in keyword or keyword in q for keyword in _keywords(definition))
    ]


def recommend_prefabs(description: str) -> list[dict]:
    """v1: a weighted whole-word-overlap heuristic between the stated need and
    each prefab's name/description — over both tools and capability components.

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
    text = description.lower()
    words = {
        w for w in _WORD_RE.findall(text) if len(w) > 2 and w not in _STOPWORDS
    }
    scored: list[tuple[int, dict]] = []
    for definition, public in _searchable():
        name_words = set(_WORD_RE.findall(definition["name"].lower()))
        desc_words = set(_WORD_RE.findall(definition["description"].lower()))
        score = 3 * len(words & name_words) + len(words & desc_words)
        score += _keyword_score(definition, text)
        if score > 0:
            scored.append((score, public))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [public for _, public in scored]
