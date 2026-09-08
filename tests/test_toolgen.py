"""定制工具代码校验测试（Phase 5 切片一）。

重点是**病态输入**：这段代码是 LLM 写的，语法错、死循环、sys.exit、名字对不
上都会真的发生，每一种都必须变成一条能喂回给模型让它自己改的错误，而不是把
Studio 后端挂掉。
"""
from __future__ import annotations

import ast

from studio_backend import toolgen
from studio_backend.toolgen import (
    MAX_ATTEMPTS,
    stub_source,
    validate_tool_source,
)


GOOD = '''
def fetch_order(args):
    return {"status": "shipped", "order_id": args.get("order_id")}

TOOL = {
    "name": "fetch_order",
    "description": "按订单号查询订单状态",
    "parameters": {
        "type": "object",
        "properties": {"order_id": {"type": "string", "description": "订单号"}},
        "required": ["order_id"],
    },
    "callback": fetch_order,
}
'''


def test_valid_tool_passes_and_returns_metadata():
    r = validate_tool_source("fetch_order", GOOD)
    assert r.ok, r.error
    assert r.tool["name"] == "fetch_order"
    assert r.tool["parameters"]["required"] == ["order_id"]
    # callback 跨不了进程边界，不该出现在结果里
    assert "callback" not in r.tool


# ── 名字 ─────────────────────────────────────────────────


def test_path_traversal_in_name_is_rejected():
    """工具名会直接当文件名用，而这个名字是模型给的——必须挡住路径穿越。"""
    r = validate_tool_source("../../etc/passwd", GOOD)
    assert not r.ok
    assert "不合法" in r.error


def test_non_identifier_names_are_rejected():
    for bad in ("Fetch-Order", "9lives", "has space", ""):
        r = validate_tool_source(bad, GOOD)
        assert not r.ok, bad


# ── 语法 / import ────────────────────────────────────────


def test_syntax_error_reports_the_line():
    r = validate_tool_source("broken", "def f(:\n    pass\n")
    assert not r.ok
    assert "语法错误" in r.error
    assert "第 1 行" in r.error


def test_import_time_exception_is_reported_not_raised():
    r = validate_tool_source("boom", "raise RuntimeError('kaboom')\n")
    assert not r.ok
    assert "kaboom" in r.error


def test_top_level_infinite_loop_times_out_instead_of_hanging(monkeypatch):
    """进程内 import 的话这一条会挂死整个 Studio 后端——子进程 + 超时存在的
    唯一理由就是它。

    把超时调到 1s 再测：默认的 10s 是留给真实工具里合理的慢 import 的，但让
    整个测试套件为这一条固定多花 10 秒不值得。
    """
    monkeypatch.setattr(toolgen, "IMPORT_TIMEOUT_SECONDS", 1)
    r = validate_tool_source("spin", "while True:\n    pass\n")
    assert not r.ok
    assert "超时" in r.error


def test_top_level_sys_exit_is_reported():
    """sys.exit 抛的是 SystemExit（不是 Exception），探针里要用 BaseException
    接住，否则子进程静静退出、结果文件是空的，只能报一句没信息量的错。"""
    r = validate_tool_source("quit", "import sys\nsys.exit(3)\n")
    assert not r.ok
    assert r.error  # 有具体原因，不是空的


def test_module_printing_does_not_break_result_parsing():
    """模型很爱在模块顶层加调试 print。结果走文件不走 stdout，就是为了不被
    这种输出搅乱。"""
    code = 'print("hello from module")\n' + GOOD
    r = validate_tool_source("fetch_order", code)
    assert r.ok, r.error


# ── TOOL 结构 ────────────────────────────────────────────


def test_missing_tool_dict_is_reported():
    r = validate_tool_source("nothing", "def f(args):\n    return 1\n")
    assert not r.ok
    assert "TOOL" in r.error


def test_tool_not_a_dict_is_reported():
    r = validate_tool_source("wrong", "TOOL = [1, 2, 3]\n")
    assert not r.ok
    assert "dict" in r.error


def test_name_mismatch_is_reported():
    """spec 里 bind_tool 引用的是请求的那个名字，对不上就等于绑了个不存在的
    工具，Play 到那一步才报错。"""
    r = validate_tool_source("expected_name", GOOD)
    assert not r.ok
    assert "expected_name" in r.error and "fetch_order" in r.error


def test_non_callable_callback_is_reported():
    code = GOOD.replace('"callback": fetch_order,', '"callback": "fetch_order",')
    r = validate_tool_source("fetch_order", code)
    assert not r.ok
    assert "callback" in r.error


def test_empty_description_is_reported():
    code = GOOD.replace('"description": "按订单号查询订单状态",', '"description": "",')
    r = validate_tool_source("fetch_order", code)
    assert not r.ok
    assert "description" in r.error


# ── parameters JSON Schema ───────────────────────────────


def test_parameters_must_be_an_object_schema():
    code = GOOD.replace('"type": "object",', '"type": "array",')
    r = validate_tool_source("fetch_order", code)
    assert not r.ok
    assert "object" in r.error


def test_parameters_must_have_properties():
    code = GOOD.replace(
        '"properties": {"order_id": {"type": "string", "description": "订单号"}},', ""
    )
    r = validate_tool_source("fetch_order", code)
    assert not r.ok
    assert "properties" in r.error


def test_required_must_reference_declared_properties():
    code = GOOD.replace('"required": ["order_id"],', '"required": ["nope"],')
    r = validate_tool_source("fetch_order", code)
    assert not r.ok
    assert "nope" in r.error


def test_required_may_be_omitted():
    code = GOOD.replace('"required": ["order_id"],', "")
    r = validate_tool_source("fetch_order", code)
    assert r.ok, r.error


def test_parameters_missing_entirely_is_reported():
    code = GOOD.replace(
        '''    "parameters": {
        "type": "object",
        "properties": {"order_id": {"type": "string", "description": "订单号"}},
        "required": ["order_id"],
    },''',
        "",
    )
    r = validate_tool_source("fetch_order", code)
    assert not r.ok
    assert "parameters" in r.error


# ── stub ─────────────────────────────────────────────────


def test_stub_source_is_valid_python_and_self_describing():
    """stub 必须自己能通过校验——它要被真的写进 tools/generated/ 并被
    load_tool_registry 加载，语法坏掉的话连 Play 都起不来。"""
    src = stub_source("fetch_order", "按订单号查询", "第 3 行 NameError: requests")
    ast.parse(src)  # 语法合法
    r = validate_tool_source("fetch_order", src)
    assert r.ok, r.error


def test_stub_callback_raises_with_the_original_error():
    """跑到这一步时要带着最后一条校验错误炸出来，而不是一句 tool not found。"""
    src = stub_source("fetch_order", "按订单号查询", "第 3 行 NameError: requests")
    ns: dict = {}
    exec(compile(src, "<stub>", "exec"), ns)
    assert ns["TOOL"]["stub"] is True
    try:
        ns["TOOL"]["callback"]({})
    except NotImplementedError as exc:
        assert "requests" in str(exc)
        assert "fetch_order" in str(exc)
    else:
        raise AssertionError("stub 应该抛 NotImplementedError")


def test_stub_survives_quotes_in_the_error_message():
    """错误信息里带引号/反斜杠是常事（比如 SyntaxError 的原文），拼字符串时
    不转义就会生成语法坏掉的 stub。"""
    nasty = 'unexpected character after line continuation "\\" in def f(:'
    src = stub_source("weird_tool", 'desc with "quotes"', nasty)
    ast.parse(src)
    r = validate_tool_source("weird_tool", src)
    assert r.ok, r.error


def test_max_attempts_is_two():
    """roadmap 明确写的是失败重试最多 2 次。"""
    assert MAX_ATTEMPTS == 2


# ── generate_tool 回调（切片二） ─────────────────────────


import json as _json

from studio_backend.config import StudioConfig
from studio_backend.project import Project
from studio_backend.tools.gen_tools import make_gen_callbacks, make_gen_tools


def _project(tmp_path, name="生成测试"):
    return Project.create(
        StudioConfig(
            home_dir=str(tmp_path / ".senza-studio"),
            model="test-model",
            api_key="k",
            api_base="",
        ),
        name,
    )


def test_generate_tool_writes_the_file_on_success(tmp_path):
    proj = _project(tmp_path)
    cb = make_gen_callbacks(proj)["generate_tool"]
    out = cb({"name": "fetch_order", "description": "查订单", "code": GOOD}, None)
    assert "error" not in out.lower()
    written = proj.path / "tools" / "generated" / "fetch_order.py"
    assert written.exists()
    assert written.read_text(encoding="utf-8") == GOOD


def test_generate_tool_does_not_write_a_file_when_validation_fails(tmp_path):
    """校验没过就落盘的话，Play 会加载一个坏文件——错误从"生成失败"变成
    运行时炸，更难查。"""
    proj = _project(tmp_path)
    cb = make_gen_callbacks(proj)["generate_tool"]
    out = cb({"name": "broken", "description": "d", "code": "def f(:\n"}, None)
    assert out.startswith("Error:")
    assert not (proj.path / "tools" / "generated" / "broken.py").exists()


def test_generate_tool_writes_a_stub_after_two_failures(tmp_path):
    proj = _project(tmp_path)
    cb = make_gen_callbacks(proj)["generate_tool"]
    args = {"name": "flaky", "description": "会失败的工具", "code": "def f(:\n"}

    first = cb(dict(args), None)
    assert "还可以再试" in first
    assert not (proj.path / "tools" / "generated" / "flaky.py").exists()

    second = cb(dict(args), None)
    assert "stub" in second
    stub = proj.path / "tools" / "generated" / "flaky.py"
    assert stub.exists()
    # stub 自己必须是能加载的合法模块
    assert validate_tool_source("flaky", stub.read_text(encoding="utf-8")).ok


def test_a_successful_retry_clears_the_failure_count(tmp_path):
    """改对了就不该还背着之前的失败次数——否则下次再失败一次就直接落 stub。"""
    proj = _project(tmp_path)
    cb = make_gen_callbacks(proj)["generate_tool"]
    cb({"name": "fetch_order", "description": "d", "code": "def f(:\n"}, None)
    cb({"name": "fetch_order", "description": "d", "code": GOOD}, None)
    out = cb({"name": "fetch_order", "description": "d", "code": "def f(:\n"}, None)
    assert "还可以再试" in out  # 又从第 1 次开始算，而不是直接落 stub


def test_invalid_name_never_writes_anything_even_after_repeated_failures(tmp_path):
    """名字会直接当文件名用。名字非法时落 stub 等于按模型给的路径写盘
    （"../../x"），必须一次都不写。"""
    proj = _project(tmp_path)
    cb = make_gen_callbacks(proj)["generate_tool"]
    args = {"name": "../../evil", "description": "d", "code": GOOD}
    for _ in range(4):
        assert cb(dict(args), None).startswith("Error:")
    generated = proj.path / "tools" / "generated"
    assert sorted(p.name for p in generated.glob("*.py")) == []
    assert not (tmp_path / "evil.py").exists()


def test_empty_code_is_rejected(tmp_path):
    proj = _project(tmp_path)
    cb = make_gen_callbacks(proj)["generate_tool"]
    assert cb({"name": "x", "description": "d", "code": "   "}, None).startswith("Error:")


def test_list_generated_tools(tmp_path):
    proj = _project(tmp_path)
    cbs = make_gen_callbacks(proj)
    assert _json.loads(cbs["list_generated_tools"]({}, None)) == []
    cbs["generate_tool"]({"name": "fetch_order", "description": "d", "code": GOOD}, None)
    assert _json.loads(cbs["list_generated_tools"]({}, None)) == ["fetch_order"]


def test_gen_tools_factory_exposes_both_tools(tmp_path):
    tools = make_gen_tools(_project(tmp_path))
    assert {t.name for t in tools} == {"generate_tool", "list_generated_tools"}
