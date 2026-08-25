"""文档工具——元 agent 写笔记/设计记录，列出项目文档。

Phase 1 只实现 write_document 和 list_documents。
ingest_document / read_document 在 Phase 6 实现。

Senza 的 Rust-backed Tool 对象不暴露 ``.callback`` 属性，因此回调闭包
单独由 :func:`make_doc_callbacks` 产出，:func:`make_doc_tools` 仅负责
将它们包装成 Tool 列表。
"""
from __future__ import annotations

import json
from typing import Any, Callable

import senza

from ..project import Project


def make_doc_callbacks(project: Project) -> dict[str, Callable[[dict, Any], str]]:
    """返回 ``{tool_name: callback}`` ——绑定到 project 的文档工具回调。"""
    callbacks: dict[str, Callable[[dict, Any], str]] = {}

    def _write_document(args, ctx):
        name = args["name"]
        content = args["content"]
        doc_path = project.path / ".studio" / "docs" / name
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(content, encoding="utf-8")
        return f"Document '{name}' saved."

    callbacks["write_document"] = _write_document

    def _list_documents(args, ctx):
        docs_dir = project.path / ".studio" / "docs"
        if not docs_dir.exists():
            return "[]"
        files = sorted(f.name for f in docs_dir.iterdir() if f.is_file())
        return json.dumps(files, ensure_ascii=False)

    callbacks["list_documents"] = _list_documents

    return callbacks


_SCHEMAS: dict[str, dict] = {
    "write_document": {
        "description": (
            "Write a document (design notes, decision records, etc.) "
            "to the project."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "File name (e.g. 'design-notes.md')",
                },
                "content": {"type": "string", "description": "Document content"},
            },
            "required": ["name", "content"],
        },
    },
    "list_documents": {
        "description": "List all documents in the project.",
        "parameters": {"type": "object", "properties": {}},
    },
}


def make_doc_tools(project: Project) -> list:
    """创建绑定到 project 的文档工具列表。"""
    callbacks = make_doc_callbacks(project)
    tools = []
    for name, cb in callbacks.items():
        schema = _SCHEMAS[name]
        tools.append(
            senza.create_tool(
                name=name,
                description=schema["description"],
                parameters=schema["parameters"],
                callback=cb,
            )
        )
    return tools
