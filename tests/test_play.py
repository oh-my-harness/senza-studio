"""Play executor/judge 回调测试（不依赖真实 LLM 调用）。

与 test_tools.py 同一模式：直接调用 make_executor/make_judge 产出的回调
闭包，而不经过 senza.create_executor/create_judge 包装（不暴露 .callback）。
"""
import pytest

import studio_backend.play as play
from studio_backend.config import StudioConfig
from studio_backend.play import (
    PENDING_APPROVAL,
    _append_routing_instruction,
    _call_tool,
    _extract_json_fields,
    _normalize_tool_result,
    build_route_maps,
    decision_context_key,
    get_entry_inputs,
    load_tool_registry,
    make_executor,
    make_judge,
    render_prompt_template,
    render_tool_args,
)
from studio_backend.project import Project


class FakeEngine:
    """假 WorkflowEngine——只记录 set_context_variable 的调用，不碰真实 SDK。"""

    def __init__(self):
        self.written: dict = {}

    def set_context_variable(self, key, value):
        self.written[key] = value


# ── build_route_maps ─────────────────────────────────────


def test_build_route_maps():
    spec_dict = {
        "stages": [
            {
                "name": "classify",
                "type": "checker",
                "next_on_complaint": "handle_complaint",
                "next_on_question": "handle_question",
            },
            {"name": "handle_complaint", "type": "agent", "next_on_success": "end"},
            {"name": "end", "type": "terminal"},
        ]
    }
    stage_by_name, routes_by_name = build_route_maps(spec_dict)

    assert set(stage_by_name) == {"classify", "handle_complaint", "end"}
    assert stage_by_name["classify"]["type"] == "checker"
    assert routes_by_name["classify"] == {
        "complaint": "handle_complaint",
        "question": "handle_question",
    }
    assert routes_by_name["handle_complaint"] == {"success": "end"}
    assert routes_by_name["end"] == {}


# ── get_entry_inputs ─────────────────────────────────────


def test_get_entry_inputs_scans_prompt_template_placeholders():
    spec_dict = {
        "stages": [
            {
                "name": "intake",
                "type": "agent",
                "prompt_template": "Customer said: {{customer_message}}",
            },
            {"name": "end", "type": "terminal"},
        ]
    }
    assert get_entry_inputs(spec_dict) == ["customer_message"]


def test_get_entry_inputs_ignores_ui_fields_display_config():
    """回归测试：ui.fields 是展示配置（这个 step 的输出用哪些字段渲染
    chart/table 卡片），不是输入需求——同名字段纯属巧合时不该被当输入。"""
    spec_dict = {
        "stages": [
            {
                "name": "classify",
                "type": "agent",
                "prompt_template": "Classify: {{customer_message}}",
                "ui": {"display": "chart", "fields": ["route", "reasoning"]},
            },
            {"name": "end", "type": "terminal"},
        ]
    }
    assert get_entry_inputs(spec_dict) == ["customer_message"]


def test_get_entry_inputs_dedupes_repeated_placeholder():
    spec_dict = {
        "stages": [
            {
                "name": "intake",
                "type": "agent",
                "prompt_template": "{{customer_message}} ... again: {{customer_message}}",
            },
        ]
    }
    assert get_entry_inputs(spec_dict) == ["customer_message"]


def test_get_entry_inputs_empty_when_no_placeholders():
    spec_dict = {"stages": [{"name": "intake", "type": "agent", "prompt_template": "hi"}]}
    assert get_entry_inputs(spec_dict) == []


def test_get_entry_inputs_empty_spec():
    assert get_entry_inputs({"stages": []}) == []


# ── render_prompt_template ───────────────────────────────


def test_render_prompt_template_substitutes_double_brace():
    result = render_prompt_template("Hello {{name}}!", {"name": "world"})
    assert result == "Hello world!"


def test_render_prompt_template_leaves_missing_var_untouched():
    result = render_prompt_template("Hello {{name}}!", {})
    assert result == "Hello {{name}}!"


def test_render_prompt_template_ignores_single_brace_json():
    template = 'Respond as JSON: {"classification": "a" | "b"}. Message: {{customer_message}}'
    result = render_prompt_template(template, {"customer_message": "hi"})
    assert result == 'Respond as JSON: {"classification": "a" | "b"}. Message: hi'


# ── make_judge ───────────────────────────────────────────


def test_judge_routes_to_target():
    routes_by_name = {"step1": {"success": "step2"}}
    judge = make_judge(routes_by_name)
    result = judge({"step_id": "step1", "structured": {"route_key": "success"}})
    assert result == "to:step2"


def test_judge_fails_on_unknown_route():
    routes_by_name = {"step1": {"success": "step2"}}
    judge = make_judge(routes_by_name)
    result = judge({"step_id": "step1", "structured": {"route_key": "nope"}})
    assert result.startswith("fail:")


def test_judge_fails_on_missing_structured():
    routes_by_name = {"step1": {"success": "step2"}}
    judge = make_judge(routes_by_name)
    result = judge({"step_id": "step1", "structured": None})
    assert result.startswith("fail:")


def test_judge_fail_includes_executor_output_detail():
    """回归测试：fail 消息得带上 executor 真正的错误详情，不然日志面板
    只看得到一句"no route for 'error'"，看不出到底为什么——得跑去 Game
    view 才知道，比如"step type 'checker' not supported until Phase 3"。"""
    routes_by_name = {"review": {"approve": "send"}}
    judge = make_judge(routes_by_name)
    result = judge(
        {
            "step_id": "review",
            "structured": {"route_key": "error"},
            "output": "Error: step type 'checker' not supported until Phase 3",
        }
    )
    assert result.startswith("fail:")
    assert "not supported until Phase 3" in result


def test_judge_fail_without_output_still_works():
    """ctx 里没有 output 字段（比如老测试/其它调用方）不该报错，退化成
    原来的消息就好。"""
    routes_by_name = {"step1": {"success": "step2"}}
    judge = make_judge(routes_by_name)
    result = judge({"step_id": "step1", "structured": {"route_key": "nope"}})
    assert result == "fail:no route for 'nope' from 'step1'"


def test_judge_pauses_on_pending_approval():
    routes_by_name = {"review": {"approve": "end", "reject": "manual"}}
    judge = make_judge(routes_by_name)
    result = judge(
        {"step_id": "review", "structured": {"route_key": PENDING_APPROVAL}}
    )
    assert result.startswith("pause:")
    assert "review" in result


# ── make_executor ────────────────────────────────────────


def test_executor_rejects_unknown_step():
    executor = make_executor({}, {}, "test-model", provider=None, env=None, engine_ref={})
    result = executor({"step_id": "ghost"})
    assert result["structured"]["route_key"] == "error"
    assert "ghost" in result["output"]


def test_executor_rejects_unsupported_type():
    stage_by_name = {"weird1": {"name": "weird1", "type": "component"}}
    executor = make_executor(
        stage_by_name, {}, "test-model", provider=None, env=None, engine_ref={}
    )
    result = executor({"step_id": "weird1"})
    assert result["structured"]["route_key"] == "error"
    assert "component" in result["output"]


# ── make_executor: checker steps (human approval) ─────────


def test_executor_checker_pending_when_no_decision():
    stage_by_name = {"review": {"name": "review", "type": "checker"}}
    executor = make_executor(
        stage_by_name, {}, "test-model", provider=None, env=None, engine_ref={}
    )
    result = executor({"step_id": "review", "context": {}})
    assert result["structured"]["route_key"] == PENDING_APPROVAL


def test_executor_checker_routes_on_existing_decision():
    stage_by_name = {"review": {"name": "review", "type": "checker"}}
    executor = make_executor(
        stage_by_name, {}, "test-model", provider=None, env=None, engine_ref={}
    )
    ctx = {"step_id": "review", "context": {decision_context_key("review"): "approve"}}
    result = executor(ctx)
    assert result["structured"]["route_key"] == "approve"


def test_decision_context_key_is_stable_and_unique_per_step():
    assert decision_context_key("a") != decision_context_key("b")
    assert decision_context_key("a") == decision_context_key("a")


# ── _extract_json_fields ──────────────────────────────────


def test_extract_json_fields_finds_trailing_object():
    output = 'This looks like a complaint.\n{"route": "complaint", "summary": "mad customer"}'
    fields, clean = _extract_json_fields(output)
    assert fields == {"route": "complaint", "summary": "mad customer"}
    assert clean == "This looks like a complaint."


def test_extract_json_fields_missing_is_empty():
    fields, clean = _extract_json_fields("just a plain answer")
    assert fields == {}
    assert clean == "just a plain answer"


def test_extract_json_fields_invalid_json_is_empty():
    fields, clean = _extract_json_fields("not json: {oops not valid}")
    assert fields == {}
    assert clean == "not json: {oops not valid}"


def test_extract_json_fields_non_dict_is_empty():
    fields, clean = _extract_json_fields('a list not object: [1, 2, 3] and {"a": 1}')
    # 最后一个花括号块是个合法 dict，应该正常解析
    assert fields == {"a": 1}


def test_extract_json_fields_uses_last_blob_if_multiple():
    output = '{"route": "complaint"} intermediate text {"route": "question"}'
    fields, _ = _extract_json_fields(output)
    assert fields == {"route": "question"}


def test_append_routing_instruction_mentions_all_routes():
    prompt = _append_routing_instruction("classify this", ["complaint", "question"])
    assert prompt.startswith("classify this")
    assert '"complaint"' in prompt
    assert '"question"' in prompt


def test_executor_multi_route_extracts_from_llm_output(monkeypatch):
    """端到端验证 play_executor 的多路由分支实际调用了 _extract_json_fields——
    用假 harness/假 LLM 输出隔离掉真实网络调用。"""
    stage_by_name = {
        "classify": {
            "name": "classify",
            "type": "agent",
            "prompt_template": "classify this",
        },
    }
    routes_by_name = {
        "classify": {"complaint": "handle_complaint", "question": "handle_question"}
    }

    class FakeBuilder:
        def provider(self, *a, **k):
            return self

        def env(self, *a, **k):
            return self

        def build(self):
            return "fake-harness"

    monkeypatch.setattr(play.senza, "HarnessBuilder", lambda model: FakeBuilder())
    monkeypatch.setattr(
        play,
        "_run_agent_step",
        lambda harness, prompt, emit: (
            'This is a complaint.\n{"route": "complaint"}',
            0,
        ),
    )

    executor = make_executor(
        stage_by_name, routes_by_name, "test-model", provider=None, env=None, engine_ref={}
    )
    result = executor({"step_id": "classify", "context": {}, "emit": None})

    assert result["structured"]["route_key"] == "complaint"
    assert result["output"] == "This is a complaint."


def test_executor_writes_extra_json_fields_to_context(monkeypatch):
    """核心的上下文传递回归测试：agent step 吐出的 JSON 里，除了 route 之外
    的字段（比如 summary）应该通过 engine_ref 写进共享 context，供下游 step
    的 prompt_template 用 {{summary}} 引用。"""
    stage_by_name = {
        "classify": {
            "name": "classify",
            "type": "agent",
            "prompt_template": "classify this",
        },
    }
    routes_by_name = {"classify": {"complaint": "next", "question": "other"}}

    class FakeBuilder:
        def provider(self, *a, **k):
            return self

        def env(self, *a, **k):
            return self

        def build(self):
            return "fake-harness"

    monkeypatch.setattr(play.senza, "HarnessBuilder", lambda model: FakeBuilder())
    monkeypatch.setattr(
        play,
        "_run_agent_step",
        lambda harness, prompt, emit: (
            'Some reasoning here.\n{"route": "complaint", "summary": "customer is upset"}',
            0,
        ),
    )

    fake_engine = FakeEngine()
    engine_ref = {"engine": fake_engine}
    executor = make_executor(
        stage_by_name, routes_by_name, "test-model", provider=None, env=None, engine_ref=engine_ref
    )
    executor({"step_id": "classify", "context": {}, "emit": None})

    assert fake_engine.written["summary"] == "customer is upset"
    assert "route" not in fake_engine.written  # route 只用来路由，不污染 context


def test_executor_writes_output_key_to_context(monkeypatch):
    stage_by_name = {
        "draft": {
            "name": "draft",
            "type": "agent",
            "prompt_template": "draft something",
            "output_key": "draft_reply",
            "next_on_success": "end",
        },
    }
    routes_by_name = {"draft": {"success": "end"}}

    class FakeBuilder:
        def provider(self, *a, **k):
            return self

        def env(self, *a, **k):
            return self

        def build(self):
            return "fake-harness"

    monkeypatch.setattr(play.senza, "HarnessBuilder", lambda model: FakeBuilder())
    monkeypatch.setattr(
        play, "_run_agent_step", lambda harness, prompt, emit: ("Dear customer, sorry...", 0)
    )

    fake_engine = FakeEngine()
    engine_ref = {"engine": fake_engine}
    executor = make_executor(
        stage_by_name, routes_by_name, "test-model", provider=None, env=None, engine_ref=engine_ref
    )
    result = executor({"step_id": "draft", "context": {}, "emit": None})

    assert fake_engine.written["draft_reply"] == "Dear customer, sorry..."
    assert result["structured"]["route_key"] == "success"


# ── make_executor: Inspector runtime "_debug" payload ───────


def test_executor_agent_debug_includes_rendered_prompt_and_tool_calls(monkeypatch):
    stage_by_name = {
        "draft": {"name": "draft", "type": "agent", "prompt_template": "hi {{name}}"},
    }

    class FakeHarness:
        def usage(self):
            return {"input_tokens": 10, "output_tokens": 5}

    class FakeBuilder:
        def provider(self, *a, **k):
            return self

        def env(self, *a, **k):
            return self

        def build(self):
            return FakeHarness()

    monkeypatch.setattr(play.senza, "HarnessBuilder", lambda model: FakeBuilder())
    monkeypatch.setattr(
        play, "_run_agent_step", lambda harness, prompt, emit: ("hello", 3)
    )

    executor = make_executor(
        stage_by_name, {}, "test-model", provider=None, env=None, engine_ref={}
    )
    result = executor({"step_id": "draft", "context": {"name": "Bob"}, "emit": None})

    debug = result["structured"]["_debug"]
    assert debug["prompt"] == "hi Bob"
    assert debug["tool_calls_count"] == 3
    assert debug["usage"] == {"input_tokens": 10, "output_tokens": 5}


def test_executor_agent_debug_usage_none_when_harness_has_no_usage(monkeypatch):
    """harness.usage() 报错（比如假 harness 根本没这方法）不该让整个 step
    崩掉——usage 只是 Inspector 的锦上添花信息，取不到就是 None。"""
    stage_by_name = {"draft": {"name": "draft", "type": "agent", "prompt_template": "x"}}

    class FakeBuilder:
        def provider(self, *a, **k):
            return self

        def env(self, *a, **k):
            return self

        def build(self):
            return "fake-harness-with-no-usage-method"

    monkeypatch.setattr(play.senza, "HarnessBuilder", lambda model: FakeBuilder())
    monkeypatch.setattr(play, "_run_agent_step", lambda harness, prompt, emit: ("ok", 0))

    executor = make_executor(
        stage_by_name, {}, "test-model", provider=None, env=None, engine_ref={}
    )
    result = executor({"step_id": "draft", "context": {}, "emit": None})
    assert result["structured"]["_debug"]["usage"] is None


def test_executor_tool_debug_includes_tool_name_and_rendered_args():
    def echo(args):
        return "ok"

    stage_by_name = {
        "lookup": {
            "name": "lookup",
            "type": "tool",
            "tool": "echo",
            "tool_args": {"city": "{{city}}"},
        },
    }
    executor = make_executor(
        stage_by_name,
        {},
        "test-model",
        provider=None,
        env=None,
        engine_ref={},
        tools_by_name={"echo": echo},
    )
    result = executor({"step_id": "lookup", "context": {"city": "Boston"}})

    assert result["structured"]["_debug"] == {"tool": "echo", "args": {"city": "Boston"}}


# ── make_executor: GameView table/chart "fields" payload ────


def test_executor_agent_structured_includes_fields_for_table_chart(monkeypatch):
    stage_by_name = {
        "classify": {"name": "classify", "type": "agent", "prompt_template": "classify this"},
    }

    class FakeBuilder:
        def provider(self, *a, **k):
            return self

        def env(self, *a, **k):
            return self

        def build(self):
            return "fake-harness"

    monkeypatch.setattr(play.senza, "HarnessBuilder", lambda model: FakeBuilder())
    monkeypatch.setattr(
        play,
        "_run_agent_step",
        lambda harness, prompt, emit: (
            'Some text.\n{"risk_score": 0.4, "category": "billing"}',
            0,
        ),
    )

    executor = make_executor(
        stage_by_name, {}, "test-model", provider=None, env=None, engine_ref={}
    )
    result = executor({"step_id": "classify", "context": {}, "emit": None})

    assert result["structured"]["fields"] == {"risk_score": 0.4, "category": "billing"}


def test_executor_tool_structured_includes_fields_for_table_chart():
    def weather_tool(args):
        return {"temperature": 72, "condition": "sunny"}

    stage_by_name = {"lookup": {"name": "lookup", "type": "tool", "tool": "weather"}}
    executor = make_executor(
        stage_by_name,
        {},
        "test-model",
        provider=None,
        env=None,
        engine_ref={},
        tools_by_name={"weather": weather_tool},
    )
    result = executor({"step_id": "lookup", "context": {}})

    assert result["structured"]["fields"] == {"temperature": 72, "condition": "sunny"}


def test_executor_no_engine_ref_does_not_crash(monkeypatch):
    """engine_ref["engine"] 还没设置（比如测试直接调用 make_executor 且不
    模拟 play() 的晚绑定）时，写 context 应该静默跳过，不报错。"""
    stage_by_name = {
        "draft": {"name": "draft", "type": "agent", "prompt_template": "x", "output_key": "k"}
    }

    class FakeBuilder:
        def provider(self, *a, **k):
            return self

        def env(self, *a, **k):
            return self

        def build(self):
            return "fake-harness"

    monkeypatch.setattr(play.senza, "HarnessBuilder", lambda model: FakeBuilder())
    monkeypatch.setattr(play, "_run_agent_step", lambda harness, prompt, emit: ("ok", 0))

    executor = make_executor(
        stage_by_name, {}, "test-model", provider=None, env=None, engine_ref={}
    )
    result = executor({"step_id": "draft", "context": {}, "emit": None})
    assert result["output"] == "ok"


# ── render_tool_args ──────────────────────────────────────


def test_render_tool_args_substitutes_string_values():
    args = render_tool_args({"city": "{{city}}"}, {"city": "Boston"})
    assert args == {"city": "Boston"}


def test_render_tool_args_passes_through_non_string_values():
    args = render_tool_args({"limit": 5, "verbose": True}, {})
    assert args == {"limit": 5, "verbose": True}


def test_render_tool_args_empty_dict_for_no_declared_args():
    assert render_tool_args({}, {"anything": "in context"}) == {}


def test_render_tool_args_parses_json_encoded_string():
    """回归测试：实测元 agent 的 LLM 调用 set_step_property 时偶尔会把
    tool_args 吐成一段 JSON 字符串而不是真正的嵌套 dict——不防御的话
    tool_args.items() 会直接 AttributeError，把整个 executor 回调打崩。"""
    args = render_tool_args('{"city": "{{city}}"}', {"city": "Boston"})
    assert args == {"city": "Boston"}


def test_render_tool_args_invalid_json_string_is_empty_dict():
    assert render_tool_args("not valid json", {}) == {}


def test_render_tool_args_non_dict_non_string_is_empty_dict():
    assert render_tool_args(["a", "list"], {}) == {}
    assert render_tool_args(None, {}) == {}
    assert render_tool_args(42, {}) == {}


# ── _normalize_tool_result ─────────────────────────────────


def test_normalize_tool_result_string_is_output_directly():
    fields, output, route = _normalize_tool_result("72F and sunny")
    assert fields == {}
    assert output == "72F and sunny"
    assert route is None


def test_normalize_tool_result_none_is_empty_output():
    fields, output, route = _normalize_tool_result(None)
    assert fields == {}
    assert output == ""
    assert route is None


def test_normalize_tool_result_dict_extracts_route_and_fields():
    fields, output, route = _normalize_tool_result(
        {"route": "approve", "risk_score": 0.2}
    )
    assert route == "approve"
    assert fields == {"risk_score": 0.2}
    assert "route" not in fields


def test_normalize_tool_result_dict_uses_explicit_output_field():
    fields, output, route = _normalize_tool_result({"output": "done", "extra": 1})
    assert output == "done"
    assert fields == {"output": "done", "extra": 1}


def test_normalize_tool_result_dict_without_output_falls_back_to_json():
    fields, output, route = _normalize_tool_result({"temperature": 72})
    assert output == '{"temperature": 72}'


def test_normalize_tool_result_empty_dict_has_empty_output():
    fields, output, route = _normalize_tool_result({})
    assert fields == {}
    assert output == ""


# ── _call_tool (arity detection) ───────────────────────────


def test_call_tool_single_arg_callback():
    calls = []

    def cb(args):
        calls.append(args)
        return "ok"

    result = _call_tool(cb, {"a": 1}, {"step_id": "s"})
    assert result == "ok"
    assert calls == [{"a": 1}]


def test_call_tool_two_arg_callback_receives_ctx():
    calls = []

    def cb(args, ctx):
        calls.append((args, ctx))
        return "ok"

    _call_tool(cb, {"a": 1}, {"step_id": "s"})
    assert calls == [({"a": 1}, {"step_id": "s"})]


# ── load_tool_registry ──────────────────────────────────────


@pytest.fixture
def tmp_config(tmp_path):
    return StudioConfig(
        home_dir=str(tmp_path / ".senza-studio"),
        model="test-model",
        api_key="test-key",
        api_base="",
    )


def test_load_tool_registry_starter_file_returns_empty_no_error(tmp_config):
    """Project.create() 写的起始文件 get_tools() 返回 {}——新项目应该能
    干净地加载出一个空注册表，不报错。"""
    proj = Project.create(tmp_config, "测试项目")
    tools, error = load_tool_registry(proj)
    assert tools == {}
    assert error is None


def test_load_tool_registry_missing_file_returns_empty_no_error(tmp_config):
    proj = Project.create(tmp_config, "测试项目")
    (proj.path / "tools" / "registry.py").unlink()
    tools, error = load_tool_registry(proj)
    assert tools == {}
    assert error is None


def test_load_tool_registry_loads_real_callables(tmp_config):
    proj = Project.create(tmp_config, "测试项目")
    (proj.path / "tools" / "registry.py").write_text(
        "def add(args):\n"
        "    return {'sum': args['a'] + args['b']}\n"
        "\n"
        "def get_tools():\n"
        "    return {'add': add}\n",
        encoding="utf-8",
    )
    tools, error = load_tool_registry(proj)
    assert error is None
    assert tools["add"]({"a": 1, "b": 2}) == {"sum": 3}


def test_load_tool_registry_syntax_error_reports_message_not_raise(tmp_config):
    proj = Project.create(tmp_config, "测试项目")
    (proj.path / "tools" / "registry.py").write_text("def get_tools(:\n", encoding="utf-8")
    tools, error = load_tool_registry(proj)
    assert tools == {}
    assert error is not None


def test_load_tool_registry_non_dict_return_reports_message(tmp_config):
    proj = Project.create(tmp_config, "测试项目")
    (proj.path / "tools" / "registry.py").write_text(
        "def get_tools():\n    return ['not', 'a', 'dict']\n", encoding="utf-8"
    )
    tools, error = load_tool_registry(proj)
    assert tools == {}
    assert error is not None
    assert "dict" in error


def test_load_tool_registry_two_projects_do_not_leak_tools(tmp_config):
    """两个不同项目各自的 registry.py 不能互相污染——回归测试固定模块名
    缓存 bug（sys.modules 复用会让后加载的项目读到前一个项目的工具）。"""
    proj_a = Project.create(tmp_config, "项目A")
    proj_b = Project.create(tmp_config, "项目B")
    (proj_a.path / "tools" / "registry.py").write_text(
        "def get_tools():\n    return {'only_in_a': lambda args: 'a'}\n", encoding="utf-8"
    )
    (proj_b.path / "tools" / "registry.py").write_text(
        "def get_tools():\n    return {'only_in_b': lambda args: 'b'}\n", encoding="utf-8"
    )
    tools_a, _ = load_tool_registry(proj_a)
    tools_b, _ = load_tool_registry(proj_b)
    assert "only_in_a" in tools_a and "only_in_b" not in tools_a
    assert "only_in_b" in tools_b and "only_in_a" not in tools_b


# ── make_executor: tool steps ───────────────────────────────


def test_executor_tool_missing_binding_is_clean_error():
    stage_by_name = {"lookup": {"name": "lookup", "type": "tool"}}
    executor = make_executor(
        stage_by_name, {}, "test-model", provider=None, env=None, engine_ref={}
    )
    result = executor({"step_id": "lookup", "context": {}})
    assert result["structured"]["route_key"] == "error"
    assert "bind_tool" in result["output"]


def test_executor_tool_unknown_ref_is_clean_error():
    stage_by_name = {"lookup": {"name": "lookup", "type": "tool", "tool": "ghost_tool"}}
    executor = make_executor(
        stage_by_name,
        {},
        "test-model",
        provider=None,
        env=None,
        engine_ref={},
        tools_by_name={},
    )
    result = executor({"step_id": "lookup", "context": {}})
    assert result["structured"]["route_key"] == "error"
    assert "ghost_tool" in result["output"]


def test_executor_tool_load_error_surfaces_on_every_tool_step():
    stage_by_name = {"lookup": {"name": "lookup", "type": "tool", "tool": "whatever"}}
    executor = make_executor(
        stage_by_name,
        {},
        "test-model",
        provider=None,
        env=None,
        engine_ref={},
        tools_by_name={},
        tools_load_error="加载 tools/registry.py 失败: bad syntax",
    )
    result = executor({"step_id": "lookup", "context": {}})
    assert result["structured"]["route_key"] == "error"
    assert "bad syntax" in result["output"]


def test_executor_tool_single_route_calls_with_rendered_args():
    calls = []

    def weather_tool(args):
        calls.append(args)
        return {"temperature": 72}

    stage_by_name = {
        "lookup": {
            "name": "lookup",
            "type": "tool",
            "tool": "weather",
            "tool_args": {"city": "{{city}}"},
            "output_key": "weather_result",
            "next_on_success": "end",
        },
    }
    fake_engine = FakeEngine()
    executor = make_executor(
        stage_by_name,
        {"lookup": {"success": "end"}},
        "test-model",
        provider=None,
        env=None,
        engine_ref={"engine": fake_engine},
        tools_by_name={"weather": weather_tool},
    )
    result = executor({"step_id": "lookup", "context": {"city": "Boston"}})

    assert calls == [{"city": "Boston"}]
    assert result["structured"]["route_key"] == "success"
    assert fake_engine.written["weather_result"] == '{"temperature": 72}'
    assert fake_engine.written["temperature"] == 72


def test_executor_tool_multi_route_uses_returned_route_field():
    def risk_check(args):
        return {"route": "reject", "risk_score": 0.9}

    stage_by_name = {
        "check": {
            "name": "check",
            "type": "tool",
            "tool": "risk_check",
            "next_on_approve": "end",
            "next_on_reject": "manual",
        },
    }
    executor = make_executor(
        stage_by_name,
        {"check": {"approve": "end", "reject": "manual"}},
        "test-model",
        provider=None,
        env=None,
        engine_ref={},
        tools_by_name={"risk_check": risk_check},
    )
    result = executor({"step_id": "check", "context": {}})
    assert result["structured"]["route_key"] == "reject"


def test_executor_tool_multi_route_invalid_route_is_error():
    def bad_tool(args):
        return {"route": "not_a_real_route"}

    stage_by_name = {
        "check": {
            "name": "check",
            "type": "tool",
            "tool": "bad",
            "next_on_approve": "end",
            "next_on_reject": "manual",
        },
    }
    executor = make_executor(
        stage_by_name,
        {"check": {"approve": "end", "reject": "manual"}},
        "test-model",
        provider=None,
        env=None,
        engine_ref={},
        tools_by_name={"bad": bad_tool},
    )
    result = executor({"step_id": "check", "context": {}})
    assert result["structured"]["route_key"] == "error"


def test_executor_tool_string_return_is_used_as_output():
    stage_by_name = {"lookup": {"name": "lookup", "type": "tool", "tool": "echo"}}
    executor = make_executor(
        stage_by_name,
        {},
        "test-model",
        provider=None,
        env=None,
        engine_ref={},
        tools_by_name={"echo": lambda args: "plain text result"},
    )
    result = executor({"step_id": "lookup", "context": {}})
    assert result["output"] == "plain text result"
    assert result["structured"]["route_key"] == "success"


def test_executor_tool_exception_is_clean_error_not_crash():
    def broken(args):
        raise ValueError("boom")

    stage_by_name = {"lookup": {"name": "lookup", "type": "tool", "tool": "broken"}}
    executor = make_executor(
        stage_by_name,
        {},
        "test-model",
        provider=None,
        env=None,
        engine_ref={},
        tools_by_name={"broken": broken},
    )
    result = executor({"step_id": "lookup", "context": {}})
    assert result["structured"]["route_key"] == "error"
    assert "boom" in result["output"]


def test_executor_tool_receives_ctx_with_step_id():
    seen_ctx = {}

    def cb(args, ctx):
        seen_ctx.update(ctx)
        return "ok"

    stage_by_name = {"lookup": {"name": "lookup", "type": "tool", "tool": "cb"}}
    executor = make_executor(
        stage_by_name,
        {},
        "test-model",
        provider=None,
        env=None,
        engine_ref={},
        tools_by_name={"cb": cb},
    )
    executor({"step_id": "lookup", "context": {}})
    assert seen_ctx["step_id"] == "lookup"
