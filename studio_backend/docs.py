"""项目文档的路径规则（Phase 6）。

上传接口和文档工具都要按用户/模型给的文件名拼路径，路径穿越的防护必须**只有
一份实现**——两处各写一遍，迟早有一处写漏。

布局：

    <project>/.studio/docs/<name>      用户上传的原文 + 元 agent 写的笔记
    <project>/.studio/ingest/<name>.json  解析结果缓存

缓存刻意放在 docs/ 外面：system_prompt 的 _document_list 会把 docs/ 下的文件
全列成"项目文档"，缓存混在里面会变成用户看不懂的噪声。
"""
from __future__ import annotations

from pathlib import Path

from .project import Project


def docs_dir(project: Project) -> Path:
    return project.path / ".studio" / "docs"


def ingest_dir(project: Project) -> Path:
    return project.path / ".studio" / "ingest"


def safe_document_name(raw: str) -> str | None:
    """校验一个文档名是否可用；不可用返回 None。

    带目录成分的名字**直接拒绝**，而不是取 basename 悄悄改名：浏览器上传永远
    只给裸文件名，出现 "/" 或 "\\" 要么是非浏览器客户端，要么就是在试探路径
    穿越，两种情况都该明确报错。悄悄把 "../../etc/passwd" 存成 "passwd" 虽然
    同样安全，但用户会发现自己传上去的文件莫名其妙换了个名字。
    """
    if not raw:
        return None
    name = raw.strip()
    if not name:
        return None
    if "/" in name or "\\" in name:
        return None
    if name in (".", ".."):
        return None
    if name.startswith("."):
        # 隐藏文件没有正当用途，而且会和 .ingest 之类的约定打架
        return None
    return name


def resolve_doc_path(project: Project, raw_name: str) -> Path | None:
    """docs/ 下某个文档的绝对路径；名字不安全或逃出 docs/ 时返回 None。

    即使 safe_document_name 已经剥掉了目录，这里仍然再用 is_relative_to 兜一次
    ——符号链接、奇怪的 unicode 都可能让第一层判断失效，而这一层是真正贴着文件
    系统的（沿用 write_document 从 Phase 1 起就在用的写法）。
    """
    name = safe_document_name(raw_name)
    if name is None:
        return None
    base = docs_dir(project).resolve()
    path = (base / name).resolve()
    if not path.is_relative_to(base):
        return None
    return path


def ingest_cache_path(project: Project, raw_name: str) -> Path:
    """解析结果缓存的路径。调用方应先用 resolve_doc_path 确认名字安全。"""
    name = safe_document_name(raw_name) or "_invalid"
    return ingest_dir(project) / f"{name}.json"


def list_documents(project: Project) -> list[str]:
    directory = docs_dir(project)
    if not directory.is_dir():
        return []
    return sorted(f.name for f in directory.iterdir() if f.is_file())


def cached_summary(project: Project, name: str) -> str | None:
    """已缓存的一行摘要，没有就返回 None。system prompt 用它给文档清单加注。"""
    import json

    path = ingest_cache_path(project, name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError):
        return None
    summary = data.get("summary")
    return summary if isinstance(summary, str) else None
