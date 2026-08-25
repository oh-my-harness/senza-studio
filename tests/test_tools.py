"""元 agent 工具回调测试。

Senza 的 Rust-backed ``Tool`` 对象不暴露 ``.callback`` 属性，因此测试
直接调用各 factory 暴露的 ``make_*_callbacks`` 回调闭包，验证它们确实
修改了 spec / project。同时验证 ``make_*_tools`` 产出的 Tool 名称正确。
"""
import json

from studio_backend.config import StudioConfig
from studio_backend.project import Project
from studio_backend.spec import Spec
from studio_backend.tools.doc_tools import make_doc_callbacks, make_doc_tools
from studio_backend.tools.prefab_tools import make_prefab_callbacks, make_prefab_tools
from studio_backend.tools.spec_tools import make_spec_callbacks, make_spec_tools


def _find_tool(tools, name):
    for t in tools:
        if t.name == name:
            return t
    raise KeyError(name)


def _cb(callbacks, name):
    return callbacks[name]


# ── spec_tools ───────────────────────────────────────────


def test_add_step_tool():
    spec = Spec()
    cbs = make_spec_callbacks(spec)
    result = _cb(cbs, "add_step")(
        {
            "name": "classify",
            "description": "分类",
            "type": "agent",
            "prompt_template": "hi",
        },
        None,
    )
    assert "added" in result.lower() or "ok" in result.lower()
    data = spec.get_current_spec()
    assert data["stages"][0]["name"] == "classify"


def test_add_edge_tool():
    spec = Spec()
    spec.add_step("a", "a", "agent")
    spec.add_step("b", "b", "terminal")
    cbs = make_spec_callbacks(spec)
    _cb(cbs, "add_edge")({"from": "a", "to": "b", "condition": "success"}, None)
    data = spec.get_current_spec()
    assert data["stages"][0]["next_on_success"] == "b"


def test_remove_step_tool():
    spec = Spec()
    spec.add_step("a", "a", "agent")
    cbs = make_spec_callbacks(spec)
    _cb(cbs, "remove_step")({"name": "a"}, None)
    data = spec.get_current_spec()
    assert len(data["stages"]) == 0


def test_set_step_property_tool():
    spec = Spec()
    spec.add_step("a", "a", "agent")
    cbs = make_spec_callbacks(spec)
    _cb(cbs, "set_step_property")(
        {"step": "a", "key": "output_key", "value": "result_a"}, None
    )
    data = spec.get_current_spec()
    assert data["stages"][0]["output_key"] == "result_a"


def test_bind_tool_tool():
    spec = Spec()
    spec.add_step("a", "a", "agent")
    cbs = make_spec_callbacks(spec)
    _cb(cbs, "bind_tool")({"step": "a", "tool_ref": "db_query"}, None)
    data = spec.get_current_spec()
    assert data["stages"][0]["tool"] == "db_query"


def test_set_ui_config_tool():
    spec = Spec()
    spec.add_step("a", "a", "agent")
    cbs = make_spec_callbacks(spec)
    _cb(cbs, "set_ui_config")({"step": "a", "display": "chat"}, None)
    data = spec.get_current_spec()
    assert data["stages"][0]["ui"]["display"] == "chat"


def test_set_ui_config_with_fields():
    spec = Spec()
    spec.add_step("a", "a", "agent")
    cbs = make_spec_callbacks(spec)
    _cb(cbs, "set_ui_config")(
        {"step": "a", "display": "table", "fields": ["x", "y"]}, None
    )
    data = spec.get_current_spec()
    assert data["stages"][0]["ui"]["fields"] == ["x", "y"]


def test_get_current_spec_tool():
    spec = Spec()
    spec.add_step("a", "a", "agent")
    cbs = make_spec_callbacks(spec)
    result = _cb(cbs, "get_current_spec")({}, None)
    data = json.loads(result)
    assert len(data["stages"]) == 1
    assert data["stages"][0]["name"] == "a"


def test_validate_spec_tool_passes():
    spec = Spec()
    spec.add_step("a", "a", "agent")
    spec.add_step("b", "b", "terminal")
    spec.add_edge("a", "b", "success")
    cbs = make_spec_callbacks(spec)
    result = _cb(cbs, "validate_spec")({}, None)
    assert "valid" in result.lower() or "ok" in result.lower()


def test_validate_spec_tool_fails():
    spec = Spec()
    spec.add_step("a", "a", "agent")
    cbs = make_spec_callbacks(spec)
    result = _cb(cbs, "validate_spec")({}, None)
    assert "error" in result.lower() or "fail" in result.lower()


def test_remove_edge_tool():
    spec = Spec()
    spec.add_step("a", "a", "agent")
    spec.add_step("b", "b", "terminal")
    spec.add_edge("a", "b", "success")
    cbs = make_spec_callbacks(spec)
    _cb(cbs, "remove_edge")(
        {"from": "a", "to": "b", "condition": "success"}, None
    )
    data = spec.get_current_spec()
    assert "next_on_success" not in data["stages"][0]


def test_add_step_error_returns_error_message():
    """工具回调不抛异常，返回错误字符串。"""
    spec = Spec()
    spec.add_step("a", "a", "agent")
    cbs = make_spec_callbacks(spec)
    result = _cb(cbs, "add_step")(
        {"name": "a", "description": "dup", "type": "agent"}, None
    )
    assert "error" in result.lower()


def test_spec_tools_factory_returns_tools_with_names():
    spec = Spec()
    tools = make_spec_tools(spec)
    names = {t.name for t in tools}
    assert names == {
        "add_step",
        "add_edge",
        "remove_step",
        "remove_edge",
        "set_step_property",
        "bind_tool",
        "set_ui_config",
        "get_current_spec",
        "validate_spec",
    }


# ── doc_tools ────────────────────────────────────────────


def test_write_document_tool(tmp_path):
    config = StudioConfig(
        home_dir=str(tmp_path / ".senza-studio"),
        model="test",
        api_key="k",
        api_base="",
    )
    proj = Project.create(config, "测试")
    cbs = make_doc_callbacks(proj)
    _cb(cbs, "write_document")({"name": "design.md", "content": "# 设计笔记"}, None)
    doc_path = proj.path / ".studio" / "docs" / "design.md"
    assert doc_path.exists()
    assert "设计笔记" in doc_path.read_text(encoding="utf-8")


def test_list_documents_tool(tmp_path):
    config = StudioConfig(
        home_dir=str(tmp_path / ".senza-studio"),
        model="test",
        api_key="k",
        api_base="",
    )
    proj = Project.create(config, "测试")
    (proj.path / ".studio" / "docs" / "note.md").write_text("hi", encoding="utf-8")
    cbs = make_doc_callbacks(proj)
    result = _cb(cbs, "list_documents")({}, None)
    assert "note.md" in result


def test_list_documents_empty(tmp_path):
    config = StudioConfig(
        home_dir=str(tmp_path / ".senza-studio"),
        model="test",
        api_key="k",
        api_base="",
    )
    proj = Project.create(config, "测试")
    cbs = make_doc_callbacks(proj)
    result = _cb(cbs, "list_documents")({}, None)
    assert json.loads(result) == []


def test_doc_tools_factory_returns_tools_with_names():
    config = StudioConfig(
        home_dir="/tmp/senza-studio-doc-factory-test",
        model="test",
        api_key="k",
        api_base="",
    )
    proj = Project.create(config, "factory-test")
    tools = make_doc_tools(proj)
    names = {t.name for t in tools}
    assert names == {"write_document", "list_documents"}


# ── prefab_tools ─────────────────────────────────────────


def test_prefab_tools_return_empty():
    cbs = make_prefab_callbacks()
    result = _cb(cbs, "list_prefabs")({}, None)
    assert "[]" in result or "empty" in result.lower() or "no" in result.lower()


def test_prefab_search_returns_empty():
    cbs = make_prefab_callbacks()
    result = _cb(cbs, "search_prefabs")({"query": "db"}, None)
    assert json.loads(result) == []


def test_prefab_recommend_returns_empty():
    cbs = make_prefab_callbacks()
    result = _cb(cbs, "recommend_prefabs")({"description": "query a db"}, None)
    assert json.loads(result) == []


def test_prefab_tools_factory_returns_three_tools():
    tools = make_prefab_tools()
    assert len(tools) == 3
    names = {t.name for t in tools}
    assert names == {"list_prefabs", "search_prefabs", "recommend_prefabs"}
