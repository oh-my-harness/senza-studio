"""Play executor/judge 回调测试（不依赖真实 LLM 调用）。

与 test_tools.py 同一模式：直接调用 make_executor/make_judge 产出的回调
闭包，而不经过 senza.create_executor/create_judge 包装（不暴露 .callback）。
"""
import studio_backend.play as play
from studio_backend.play import (
    PENDING_APPROVAL,
    _append_routing_instruction,
    _extract_json_fields,
    build_route_maps,
    decision_context_key,
    get_entry_inputs,
    make_executor,
    make_judge,
    render_prompt_template,
)


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
    stage_by_name = {"tool1": {"name": "tool1", "type": "tool"}}
    executor = make_executor(
        stage_by_name, {}, "test-model", provider=None, env=None, engine_ref={}
    )
    result = executor({"step_id": "tool1"})
    assert result["structured"]["route_key"] == "error"
    assert "tool" in result["output"]
    assert "Phase 3" in result["output"]


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
        lambda harness, prompt, emit: 'This is a complaint.\n{"route": "complaint"}',
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
            'Some reasoning here.\n{"route": "complaint", "summary": "customer is upset"}'
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
        play, "_run_agent_step", lambda harness, prompt, emit: "Dear customer, sorry..."
    )

    fake_engine = FakeEngine()
    engine_ref = {"engine": fake_engine}
    executor = make_executor(
        stage_by_name, routes_by_name, "test-model", provider=None, env=None, engine_ref=engine_ref
    )
    result = executor({"step_id": "draft", "context": {}, "emit": None})

    assert fake_engine.written["draft_reply"] == "Dear customer, sorry..."
    assert result["structured"]["route_key"] == "success"


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
    monkeypatch.setattr(play, "_run_agent_step", lambda harness, prompt, emit: "ok")

    executor = make_executor(
        stage_by_name, {}, "test-model", provider=None, env=None, engine_ref={}
    )
    result = executor({"step_id": "draft", "context": {}, "emit": None})
    assert result["output"] == "ok"
