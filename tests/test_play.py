"""Play executor/judge 回调测试（不依赖真实 LLM 调用）。

与 test_tools.py 同一模式：直接调用 make_executor/make_judge 产出的回调
闭包，而不经过 senza.create_executor/create_judge 包装（不暴露 .callback）。
"""

import json
import threading
import time

import pytest

# 实现搬到了 senza_studio_runtime（Phase 7）。这个别名只用来 monkeypatch
# 模块内部符号（senza / _run_agent_step / _load_prefab_tools），所以要指到
# 实现真正所在的模块——studio_backend.play 现在只是转发层，patch 它不会
# 影响运行时内部的全局查找。下面 from studio_backend.play import ... 的
# 公开 API 照旧走 Studio 那一层（PlaySession 在那里翻译 Project/Config）。
import senza_studio_runtime.play as play
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
    PlaySession,
)
from studio_backend.project import Project
from studio_backend.spec import Spec


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
    spec_dict = {
        "stages": [{"name": "intake", "type": "agent", "prompt_template": "hi"}]
    }
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
    template = (
        'Respond as JSON: {"classification": "a" | "b"}. Message: {{customer_message}}'
    )
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
    result = judge({"step_id": "review", "structured": {"route_key": PENDING_APPROVAL}})
    assert result.startswith("pause:")
    assert "review" in result


# ── make_executor ────────────────────────────────────────


def test_executor_rejects_unknown_step():
    executor = make_executor(
        {}, {}, "test-model", provider=None, env=None, engine_ref={}
    )
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

# 嵌套 JSON 回归（evaluate_results 的 route + candidates 形状）：
# 提取器必须取最后一个**完整顶层**对象，而不是最深处的内层对象。


def test_extract_json_fields_nested_candidates_multi_route():
    output = (
        "Kept 4 strong candidates.\n"
        '{"route": "sufficient", "candidates": ['
        '{"title": "AllRecipes", "url": "https://a", "price": null},'
        '{"title": "EatThis", "url": "https://b", "price": "$120"}]}'
    )
    fields, clean = _extract_json_fields(output)
    assert fields["route"] == "sufficient"
    assert len(fields["candidates"]) == 2
    assert fields["candidates"][0]["title"] == "AllRecipes"
    assert clean == "Kept 4 strong candidates."


def test_extract_json_fields_nested_single_route_reaches_context():
    output = (
        "Summarized.\n"
        '{"candidates": [{"title": "A", "relevance": 8}, {"title": "B", "relevance": 9}],'
        ' "data_quality": "good"}'
    )
    fields, clean = _extract_json_fields(output)
    assert fields == {
        "candidates": [{"title": "A", "relevance": 8}, {"title": "B", "relevance": 9}],
        "data_quality": "good",
    }
    assert clean == "Summarized."


def test_extract_json_fields_nested_surrounding_prose():
    output = (
        'Here is my analysis.\n'
        'The candidates look strong.\n'
        '{"route": "sufficient", "candidates": [{"title": "K2", "note": "hot swap"}]}'
    )
    fields, clean = _extract_json_fields(output)
    assert fields["route"] == "sufficient"
    assert fields["candidates"] == [{"title": "K2", "note": "hot swap"}]
    assert clean == "Here is my analysis.\nThe candidates look strong."


def test_extract_json_fields_braces_inside_strings():
    output = '{"text": "example { not structure }", "route": "ok"}'
    fields, clean = _extract_json_fields(output)
    assert fields == {"text": "example { not structure }", "route": "ok"}
    assert clean == ""


def test_extract_json_fields_nested_braces_inside_strings():
    output = (
        '{"route": "sufficient", "candidates": ['
        '{"title": "brace { in title", "note": "and } here"}]}'
    )
    fields, clean = _extract_json_fields(output)
    assert fields["route"] == "sufficient"
    assert fields["candidates"] == [{"title": "brace { in title", "note": "and } here"}]
    assert clean == ""


def test_extract_json_fields_escaped_quotes_and_backslashes():
    output = r'{"text": "she said \"hi\"", "path": "C:\\tmp", "route": "ok"}'
    fields, clean = _extract_json_fields(output)
    assert fields == {
        "text": 'she said "hi"',
        "path": "C:\\tmp",
        "route": "ok",
    }
    assert clean == ""


def test_extract_json_fields_last_top_level_object_wins_nested():
    output = (
        '{"route": "insufficient", "candidates": [{"title": "old"}]}\n'
        'On reflection there is enough data.\n'
        '{"route": "sufficient", "candidates": [{"title": "new"}]}'
    )
    fields, clean = _extract_json_fields(output)
    assert fields["route"] == "sufficient"
    assert fields["candidates"] == [{"title": "new"}]
    assert clean == (
        '{"route": "insufficient", "candidates": [{"title": "old"}]}\n'
        "On reflection there is enough data."
    )


def test_extract_json_fields_incomplete_trailing_object_fails_safe():
    # 截断的嵌套对象：安全契约是 fields={} + 原文返回（纯文本 fallback）。
    output = 'Working on it.\n{"route": "sufficient", "candidates": [{"title": "A"}'
    fields, clean = _extract_json_fields(output)
    assert fields == {}
    assert clean == output


def test_extract_json_fields_deep_nesting():
    output = '{"route": "ok", "data": {"items": [[1, {"x": 2}], {"y": {"z": 3}}]}}'
    fields, clean = _extract_json_fields(output)
    assert fields == {"route": "ok", "data": {"items": [[1, {"x": 2}], {"y": {"z": 3}}]}}
    assert clean == ""



def test_extract_json_fields_prose_quote_before_valid_json():
    """回归：散文里的未闭合引号不得干扰后面的 JSON 发现。"""
    output = 'The size is 12".\n{"route":"sufficient"}'
    fields, clean = _extract_json_fields(output)
    assert fields == {"route": "sufficient"}
    assert clean == "The size is 12\"."


def test_extract_json_fields_prose_quote_between_two_routes():
    """回归：前一个有效 route + 散文引号 + 后一个有效 route——后者必须胜出。"""
    output = '{"route":"insufficient"}\nThe size is 12".\n{"route":"sufficient"}'
    fields, clean = _extract_json_fields(output)
    assert fields == {"route": "sufficient"}
    assert clean == '{"route":"insufficient"}\nThe size is 12".'


def test_extract_json_fields_stray_prose_brace_before_valid_json():
    """回归：散文里未闭合的 ``{`` 不得吞掉后面的完整对象。"""
    output = 'The token starts with {.\n{"route":"sufficient"}'
    fields, clean = _extract_json_fields(output)
    assert fields == {"route": "sufficient"}
    assert clean == "The token starts with {."


def test_extract_json_fields_backslash_parity_before_closing_quote():
    """回归：闭合引号前的反斜杠奇偶性——``\\\\`` 是转义反斜杠（字符串在此
    闭合），``\\"`` 是转义引号（字符串继续）。扫描器必须与 json.loads 一致。"""
    output = r'{"a": "ends with \\", "b": "has \" inside", "route": "ok"}'
    fields, clean = _extract_json_fields(output)
    assert fields["a"] == "ends with \\"
    assert fields["b"] == 'has " inside'
    assert fields["route"] == "ok"
    assert clean == ""


def test_extract_json_fields_markdown_code_fence():
    output = "```json\n{\"route\": \"sufficient\"}\n```"
    fields, clean = _extract_json_fields(output)
    assert fields == {"route": "sufficient"}
    # JSON 被摘走后围栏骨架仍在（保留换行）——展示文本不为空即可。
    assert clean == "```json\n\n```"


def test_extract_json_fields_trailing_prose_after_json():
    output = '{"route": "sufficient"}\nThat is my final answer.'
    fields, clean = _extract_json_fields(output)
    assert fields == {"route": "sufficient"}
    assert clean == "That is my final answer."


def test_extract_json_fields_complete_then_truncated_object():
    """契约固定：完整对象在前、截断对象在后——截断对象不产生有效 span，
    因此最后有效对象仍是前面的完整对象（"最后完整对象胜出"语义）。
    截断对象自身（"trailing 截断" 用例）才走 failsafe 返回 {}。"""
    output = '{"route": "sufficient"}\n{"summary": "partial", "candidates": [{"title"'
    fields, clean = _extract_json_fields(output)
    assert fields == {"route": "sufficient"}
    assert clean == '{"summary": "partial", "candidates": [{"title"'



def test_extract_json_fields_truncated_outer_does_not_leak_inner_route():
    """回归（blocker）：截断的外层对象不得把内层对象提升为路由对象。"""
    output = '{"wrapper":{"route":"sufficient"}'
    fields, clean = _extract_json_fields(output)
    assert fields == {}
    assert clean == output


def test_extract_json_fields_deep_truncated_nesting_no_inner_route():
    """回归：更深的嵌套同理——每层内层对象都不能逃逸截断的外层。"""
    output = '{"a":{"b":{"route":"sufficient"}'
    fields, clean = _extract_json_fields(output)
    assert fields == {}
    assert clean == output
    output3 = '{"a":{"b":{"c":{"route":"sufficient"}'
    fields, clean = _extract_json_fields(output)
    assert fields == {}


def test_extract_json_fields_truncated_candidates_array_still_safe():
    """既有契约：截断的 candidates 数组不得泄漏内层对象，failsafe 返回 {}。"""
    output = 'Working on it.\n{"route": "sufficient", "candidates": [{"title": "A"}'
    fields, clean = _extract_json_fields(output)
    assert fields == {}
    assert clean == output


def test_extract_json_fields_nested_route_with_complete_outer():
    """完整的外层对象里的合法嵌套照常提取——截断修复不影响合法嵌套。"""
    output = '{"wrapper":{"route":"sufficient"}}'
    fields, clean = _extract_json_fields(output)
    assert fields == {"wrapper": {"route": "sufficient"}}
    assert clean == ""


def test_extract_json_fields_earlier_complete_route_beats_later_truncated_outer():
    """契约固定：前面完整 route + 后面截断外层（内层 route 不可提升）——
    "最后完整对象胜出"：前面的完整对象保留，截断外层不泄漏任何 route。"""
    output = '{"route":"insufficient"}\n{"wrapper":{"route":"sufficient"}'
    fields, clean = _extract_json_fields(output)
    assert fields == {"route": "insufficient"}
    assert clean == '{"wrapper":{"route":"sufficient"}'


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
        stage_by_name,
        routes_by_name,
        "test-model",
        provider=None,
        env=None,
        engine_ref={},
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
        stage_by_name,
        routes_by_name,
        "test-model",
        provider=None,
        env=None,
        engine_ref=engine_ref,
    )
    executor({"step_id": "classify", "context": {}, "emit": None})

    assert fake_engine.written["summary"] == "customer is upset"
    assert "route" not in fake_engine.written  # route 只用来路由，不污染 context


def test_integrated_nested_output_executor_context_judge(monkeypatch):
    """集成回归：嵌套模型输出 -> make_executor -> 共享 context -> route_key
    -> make_judge。

    用例覆盖两个回归的端到端影响：嵌套模型输出（route + candidates 数组）
    夹在含散文引号和散文花括号的输出里：
    - "sufficient" 被选中（不是被散文引号破坏、也不是取到旧 route）
    - transition 是 to:compare_candidates
    - 嵌套 candidates 进入共享 context
    - route 本身不写入共享 context
    """
    stage_by_name = {
        "evaluate_results": {
            "name": "evaluate_results",
            "type": "agent",
            "prompt_template": "evaluate the results",
        },
    }
    routes_by_name = {
        "evaluate_results": {"sufficient": "compare_candidates", "insufficient": "refine"}
    }

    class FakeBuilder:
        def provider(self, *a, **k):
            return self

        def env(self, *a, **k):
            return self

        def build(self):
            return "fake-harness"

    # 模型原始输出：散文引号 + 散文花括号 + 前一个 insufficient + 最终嵌套 JSON。
    raw_output = (
        'The size is 12". The token starts with {.\n'
        '{"route": "insufficient"}\n'
        "On reflection there is enough data.\n"
        '{"route": "sufficient", "candidates": ['
        '{"title": "K2", "relevance": 9}, {"title": "Annapurna", "relevance": 7}]}'
    )
    monkeypatch.setattr(play.senza, "HarnessBuilder", lambda model: FakeBuilder())
    monkeypatch.setattr(
        play, "_run_agent_step", lambda harness, prompt, emit: (raw_output, 0)
    )

    stage_by_name = {
        "evaluate_results": {
            "name": "evaluate_results",
            "type": "agent",
            "prompt_template": "evaluate",
        },
    }
    routes_by_name = {"evaluate_results": {"sufficient": "compare_candidates", "insufficient": "refine"}}

    fake_engine = FakeEngine()
    engine_ref = {"engine": fake_engine}
    executor = make_executor(
        stage_by_name,
        routes_by_name,
        "test-model",
        provider=None,
        env=None,
        engine_ref=engine_ref,
    )
    result = executor({"step_id": "evaluate_results", "context": {}, "emit": None})

    # 1. sufficient 被选中。
    assert result["structured"]["route_key"] == "sufficient"
    # 2. 嵌套 candidates 进入共享 context。
    assert fake_engine.written["candidates"] == [
        {"title": "K2", "relevance": 9},
        {"title": "Annapurna", "relevance": 7},
    ]
    # 3. route 本身不写入共享 context。
    assert "route" not in fake_engine.written

    # 4. make_judge 把 route_key 翻成 to:compare_candidates。
    judge = make_judge(routes_by_name)
    transition = judge(
        {
            "step_id": "evaluate_results",
            "structured": result["structured"],
            "output": result["output"],
        }
    )
    assert transition == "to:compare_candidates"


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
        play,
        "_run_agent_step",
        lambda harness, prompt, emit: ("Dear customer, sorry...", 0),
    )

    fake_engine = FakeEngine()
    engine_ref = {"engine": fake_engine}
    executor = make_executor(
        stage_by_name,
        routes_by_name,
        "test-model",
        provider=None,
        env=None,
        engine_ref=engine_ref,
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
    stage_by_name = {
        "draft": {"name": "draft", "type": "agent", "prompt_template": "x"}
    }

    class FakeBuilder:
        def provider(self, *a, **k):
            return self

        def env(self, *a, **k):
            return self

        def build(self):
            return "fake-harness-with-no-usage-method"

    monkeypatch.setattr(play.senza, "HarnessBuilder", lambda model: FakeBuilder())
    monkeypatch.setattr(
        play, "_run_agent_step", lambda harness, prompt, emit: ("ok", 0)
    )

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

    assert result["structured"]["_debug"] == {
        "tool": "echo",
        "args": {"city": "Boston"},
    }


# ── make_executor: GameView table/chart "fields" payload ────


def test_executor_agent_structured_includes_fields_for_table_chart(monkeypatch):
    stage_by_name = {
        "classify": {
            "name": "classify",
            "type": "agent",
            "prompt_template": "classify this",
        },
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
        "draft": {
            "name": "draft",
            "type": "agent",
            "prompt_template": "x",
            "output_key": "k",
        }
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
        play, "_run_agent_step", lambda harness, prompt, emit: ("ok", 0)
    )

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


def test_load_tool_registry_starter_file_returns_empty_no_error(
    tmp_config, monkeypatch
):
    """Project.create() 写的起始文件 get_tools() 返回 {}——新项目应该能
    干净地加载出一个空注册表，不报错。屏蔽预制件层，单独测项目文件本身
    的加载行为，不跟 senza_studio_components 装没装、里面有什么耦合。"""
    monkeypatch.setattr(play, "_load_prefab_tools", lambda: {})
    proj = Project.create(tmp_config, "测试项目")
    tools, error = load_tool_registry(proj)
    assert tools == {}
    assert error is None


def test_load_tool_registry_missing_file_returns_empty_no_error(
    tmp_config, monkeypatch
):
    monkeypatch.setattr(play, "_load_prefab_tools", lambda: {})
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


def test_load_tool_registry_syntax_error_reports_message_not_raise(
    tmp_config, monkeypatch
):
    monkeypatch.setattr(play, "_load_prefab_tools", lambda: {})
    proj = Project.create(tmp_config, "测试项目")
    (proj.path / "tools" / "registry.py").write_text(
        "def get_tools(:\n", encoding="utf-8"
    )
    tools, error = load_tool_registry(proj)
    assert tools == {}
    assert error is not None


def test_load_tool_registry_non_dict_return_reports_message(tmp_config, monkeypatch):
    monkeypatch.setattr(play, "_load_prefab_tools", lambda: {})
    proj = Project.create(tmp_config, "测试项目")
    (proj.path / "tools" / "registry.py").write_text(
        "def get_tools():\n    return ['not', 'a', 'dict']\n", encoding="utf-8"
    )
    tools, error = load_tool_registry(proj)
    assert tools == {}
    assert error is not None
    assert "dict" in error


def test_load_tool_registry_two_projects_do_not_leak_tools(tmp_config, monkeypatch):
    """两个不同项目各自的 registry.py 不能互相污染——回归测试固定模块名
    缓存 bug（sys.modules 复用会让后加载的项目读到前一个项目的工具）。"""
    monkeypatch.setattr(play, "_load_prefab_tools", lambda: {})
    proj_a = Project.create(tmp_config, "项目A")
    proj_b = Project.create(tmp_config, "项目B")
    (proj_a.path / "tools" / "registry.py").write_text(
        "def get_tools():\n    return {'only_in_a': lambda args: 'a'}\n",
        encoding="utf-8",
    )
    (proj_b.path / "tools" / "registry.py").write_text(
        "def get_tools():\n    return {'only_in_b': lambda args: 'b'}\n",
        encoding="utf-8",
    )
    tools_a, _ = load_tool_registry(proj_a)
    tools_b, _ = load_tool_registry(proj_b)
    assert "only_in_a" in tools_a and "only_in_b" not in tools_a
    assert "only_in_b" in tools_b and "only_in_a" not in tools_b


# ── load_tool_registry: prefab layer (Phase 4) ───────────────


def test_load_tool_registry_includes_real_prefab_tools(tmp_config):
    """Phase 4：senza_studio_components 装好了以后，即使项目自己什么工具
    都没写，也该能用预制件（db_query/lookup_topic/send_email）。"""
    proj = Project.create(tmp_config, "测试项目")
    tools, error = load_tool_registry(proj)
    assert error is None
    assert {"db_query", "lookup_topic", "send_email"} <= set(tools)


def test_load_tool_registry_project_tool_overrides_prefab_of_same_name(tmp_config):
    """项目自己的同名工具应该覆盖预制件——项目定制优先于通用默认值。"""
    proj = Project.create(tmp_config, "测试项目")
    (proj.path / "tools" / "registry.py").write_text(
        "def db_query(args):\n    return 'this is the PROJECT override, not the prefab'\n"
        "def get_tools():\n    return {'db_query': db_query}\n",
        encoding="utf-8",
    )
    tools, error = load_tool_registry(proj)
    assert error is None
    assert tools["db_query"]({}) == "this is the PROJECT override, not the prefab"


def test_load_tool_registry_prefab_available_even_if_project_registry_broken(
    tmp_config,
):
    """项目自己的 registry.py 语法错误——不该连预制件都用不了。"""
    proj = Project.create(tmp_config, "测试项目")
    (proj.path / "tools" / "registry.py").write_text(
        "def get_tools(:\n", encoding="utf-8"
    )
    tools, error = load_tool_registry(proj)
    assert error is not None
    assert "db_query" in tools  # 预制件层不受项目 registry.py 加载失败影响


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


def test_executor_tool_load_error_surfaces_when_tool_not_found():
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


def test_executor_tool_load_error_does_not_block_prefab_tool():
    """项目自己的 tools/registry.py 坏了，不该连预制件工具都用不了——
    Phase 4：预制件是独立加载的一层，跟项目 registry.py 的加载状态无关。"""
    stage_by_name = {"lookup": {"name": "lookup", "type": "tool", "tool": "db_query"}}
    executor = make_executor(
        stage_by_name,
        {},
        "test-model",
        provider=None,
        env=None,
        engine_ref={},
        tools_by_name={"db_query": lambda args: "ok (this is a prefab, still works)"},
        tools_load_error="加载 tools/registry.py 失败: bad syntax in project's own file",
    )
    result = executor({"step_id": "lookup", "context": {}})
    assert result["structured"]["route_key"] == "success"
    assert result["output"] == "ok (this is a prefab, still works)"


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


# ── PlaySession: pause / resume / step ───────────────────────


class FakeStatefulEngine:
    """假 WorkflowEngine——记录 pause()/resume() 调用顺序，state() 可手动
    切换，不碰真实 SDK（PlaySession.__init__ 本身不构造 engine，直接把
    _engine 换成这个假对象即可单测这三个方法）。"""

    def __init__(self, initial_state: str):
        self._state = initial_state
        self.calls: list[tuple] = []

    def state(self):
        return self._state

    def pause(self, reason):
        self.calls.append(("pause", reason))

    def resume(self):
        self.calls.append(("resume",))
        # 亲测行为：resume() 会把 pause_requested 标志清空——step() 依赖
        # 这个副作用的测试需要能观察到 resume 之后 state 仍是 "paused"
        # （亲测：Paused -> Running 的转换由 run() 自己做，不是 resume()）。

    def set_context_variable(self, key, value):
        self.calls.append(("set_context_variable", key, value))


def _make_session_with_fake_engine(initial_state: str):
    session = PlaySession(None, None, None)
    session._engine = FakeStatefulEngine(initial_state)
    return session


def test_request_pause_calls_engine_pause_when_running():
    session = _make_session_with_fake_engine("running")
    session.request_pause("test reason")
    assert session._engine.calls == [("pause", "test reason")]


def test_request_pause_noop_when_not_running():
    for state in ("idle", "paused", "succeeded"):
        session = _make_session_with_fake_engine(state)
        session.request_pause()
        assert session._engine.calls == []


def test_resume_run_calls_resume_then_start_when_paused(monkeypatch):
    session = _make_session_with_fake_engine("paused")
    started = []
    monkeypatch.setattr(session, "start", lambda: started.append(True))
    session.run_error = RuntimeError("stale")

    session.resume_run()

    assert session._engine.calls == [("resume",)]
    assert started == [True]
    assert session.run_error is None


def test_resume_run_noop_when_not_paused(monkeypatch):
    session = _make_session_with_fake_engine("running")
    started = []
    monkeypatch.setattr(session, "start", lambda: started.append(True))

    session.resume_run()

    assert session._engine.calls == []
    assert started == []


def test_step_calls_resume_before_pause_then_start(monkeypatch):
    """顺序很关键：resume() 会把 pause_requested 清空，先 pause() 后
    resume() 的话，pause() 刚设的标志就会被 resume() 自己清掉。"""
    session = _make_session_with_fake_engine("paused")
    started = []
    monkeypatch.setattr(session, "start", lambda: started.append(True))
    session.run_error = RuntimeError("stale")

    session.step("single-step")

    assert session._engine.calls == [("resume",), ("pause", "single-step")]
    assert started == [True]
    assert session.run_error is None


def test_step_noop_when_not_paused(monkeypatch):
    session = _make_session_with_fake_engine("running")
    started = []
    monkeypatch.setattr(session, "start", lambda: started.append(True))

    session.step()

    assert session._engine.calls == []
    assert started == []


# ── PlaySession: _step_mode interaction with submit_decision ─


def test_submit_decision_rearms_pause_when_in_step_mode(monkeypatch):
    """回归测试：Play Paused/Step 走到一个 checker，点 approve 之后不该
    一路跑到底——审批本身也是往前走了一步，应该跟其它 step 一样只跑这一
    步就再暂停（亲测复现过：不这么做的话，approve 之后会直接冲到终点，
    把"逐步执行"的节奏在 checker 这里打断）。"""
    session = _make_session_with_fake_engine("paused")
    session._step_mode = True
    started = []
    monkeypatch.setattr(session, "start", lambda: started.append(True))

    session.submit_decision("review", "approve")

    calls = session._engine.calls
    assert ("set_context_variable", decision_context_key("review"), "approve") in calls
    assert ("resume",) in calls
    assert ("pause", "single-step (after approval)") in calls
    # resume 必须在 pause 之前——resume() 会清空 pause_requested。
    assert calls.index(("resume",)) < calls.index(
        ("pause", "single-step (after approval)")
    )
    assert started == [True]


def test_submit_decision_does_not_pause_when_not_in_step_mode(monkeypatch):
    """默认（没在 Play Paused/Step 模式下）走到 checker，approve 之后应该
    照旧一路跑下去——这是这个功能加进来之前就有的行为，不该被破坏。"""
    session = _make_session_with_fake_engine("paused")
    assert session._step_mode is False
    started = []
    monkeypatch.setattr(session, "start", lambda: started.append(True))

    session.submit_decision("review", "approve")

    calls = session._engine.calls
    assert ("resume",) in calls
    assert not any(c[0] == "pause" for c in calls)
    assert started == [True]


def test_play_start_paused_sets_step_mode(monkeypatch, tmp_config):
    project = Project.create(tmp_config, "测试项目")
    spec = Spec({"stages": [{"name": "a", "type": "agent"}]})
    fake_engine = FakeStatefulEngineForPlay("idle")
    monkeypatch.setattr(
        play.senza,
        "providers",
        type("P", (), {"openai": staticmethod(lambda **k: object())}),
    )
    monkeypatch.setattr(play.senza, "create_os_env", lambda path: object())
    monkeypatch.setattr(play.senza, "WorkflowEngine", lambda *a, **k: fake_engine)
    monkeypatch.setattr(play.senza, "create_judge", lambda cb: cb)
    monkeypatch.setattr(play.senza, "create_executor", lambda cb: cb)

    session = PlaySession(tmp_config, project, spec)
    session.play(inputs={}, start_paused=True)
    assert session._step_mode is True

    session2 = PlaySession(tmp_config, project, spec)
    session2.play(inputs={}, start_paused=False)
    assert session2._step_mode is False


def test_resume_run_turns_off_step_mode(monkeypatch):
    session = _make_session_with_fake_engine("paused")
    session._step_mode = True
    monkeypatch.setattr(session, "start", lambda: None)

    session.resume_run()

    assert session._step_mode is False


def test_pause_resume_step_noop_when_engine_is_none():
    """PlaySession 还没调用 play() 构建 engine（_engine 是 None）时，三个
    方法都应该静默跳过，不报错——跟 stop() 的现有防御风格一致。"""
    session = PlaySession(None, None, None)
    session.request_pause()
    session.resume_run()
    session.step()


class FakeStatefulEngineForPlay(FakeStatefulEngine):
    """FakeStatefulEngine 加上 play() 需要的其它接口（with_max_steps/
    with_executor 等），全部原样返回 self 或什么都不做，只关心 pause()
    有没有被调用。"""

    def with_max_steps(self, max_steps):
        return self

    def with_executor(self, name, executor):
        return self

    def set_context_variable(self, key, value):
        pass


def test_play_start_paused_arms_pause_before_first_run(monkeypatch, tmp_config):
    project = Project.create(tmp_config, "测试项目")
    spec = Spec({"stages": [{"name": "a", "type": "agent"}]})

    fake_engine = FakeStatefulEngineForPlay("idle")
    monkeypatch.setattr(
        play.senza,
        "providers",
        type("P", (), {"openai": staticmethod(lambda **k: object())}),
    )
    monkeypatch.setattr(play.senza, "create_os_env", lambda path: object())
    monkeypatch.setattr(play.senza, "WorkflowEngine", lambda *a, **k: fake_engine)
    monkeypatch.setattr(play.senza, "create_judge", lambda cb: cb)
    monkeypatch.setattr(play.senza, "create_executor", lambda cb: cb)

    session = PlaySession(tmp_config, project, spec)
    session.play(inputs={}, start_paused=True)

    assert ("pause", "start paused") in fake_engine.calls


def test_play_without_start_paused_does_not_call_pause(monkeypatch, tmp_config):
    project = Project.create(tmp_config, "测试项目")
    spec = Spec({"stages": [{"name": "a", "type": "agent"}]})

    fake_engine = FakeStatefulEngineForPlay("idle")
    monkeypatch.setattr(
        play.senza,
        "providers",
        type("P", (), {"openai": staticmethod(lambda **k: object())}),
    )
    monkeypatch.setattr(play.senza, "create_os_env", lambda path: object())
    monkeypatch.setattr(play.senza, "WorkflowEngine", lambda *a, **k: fake_engine)
    monkeypatch.setattr(play.senza, "create_judge", lambda cb: cb)
    monkeypatch.setattr(play.senza, "create_executor", lambda cb: cb)

    session = PlaySession(tmp_config, project, spec)
    session.play(inputs={})

    assert fake_engine.calls == []


# ── 能力组件 → Play 集成 ─────────────────────────────────


def test_get_entry_inputs_expands_components_first():
    """spec 第一个 stage 是组件引用时，入口输入要从展开后的入口 step 上扫。
    不展开就扫的话，组件 step 本身没有 prompt_template，会漏报所有种子输入。"""
    spec_dict = {
        "stages": [
            {"name": "gate", "component": "approval_flow", "next_on_approve": "done"},
            {"name": "done", "type": "terminal"},
        ]
    }
    # approval_flow 展开出的 checker 没有 prompt_template => 空列表，
    # 关键是不崩、也不误报
    assert get_entry_inputs(spec_dict) == []


def test_build_route_maps_over_an_expanded_component_spec():
    """展开之后 build_route_maps 看到的就是普通 step，不需要懂组件语义。"""
    from studio_backend.preprocess import preprocess_spec

    spec_dict = preprocess_spec(
        {
            "stages": [
                {
                    "name": "gate",
                    "component": "approval_flow",
                    "params": {"title": "退货审批"},
                    "next_on_approve": "ok",
                    "next_on_reject": "no",
                },
                {"name": "ok", "type": "terminal"},
                {"name": "no", "type": "terminal"},
            ]
        }
    )
    stage_by_name, routes_by_name = build_route_maps(spec_dict)
    assert stage_by_name["gate_review"]["type"] == "checker"
    assert routes_by_name["gate_review"] == {"approve": "ok", "reject": "no"}


def test_checker_executor_surfaces_the_stage_message():
    """能力组件的 title 参数落在 step 的 message 上——审批人该看到"退货审批"
    而不是通用的"等待人工审批"。"""
    from studio_backend.preprocess import preprocess_spec

    spec_dict = preprocess_spec(
        {
            "stages": [
                {
                    "name": "gate",
                    "component": "approval_flow",
                    "params": {"title": "退货审批：金额超过 500"},
                    "next_on_approve": "ok",
                    "next_on_reject": "ok",
                },
                {"name": "ok", "type": "terminal"},
            ]
        }
    )
    stage_by_name, routes_by_name = build_route_maps(spec_dict)
    executor = make_executor(
        stage_by_name, routes_by_name, "test-model", None, None, {}, {}, None
    )
    result = executor({"step_id": "gate_review", "context": {}})
    assert result["output"] == "退货审批：金额超过 500"
    assert result["structured"]["route_key"] == PENDING_APPROVAL


def test_checker_without_message_keeps_the_default_wording():
    stage_by_name = {"gate": {"name": "gate", "type": "checker"}}
    executor = make_executor(
        stage_by_name, {"gate": {}}, "test-model", None, None, {}, {}, None
    )
    result = executor({"step_id": "gate", "context": {}})
    assert result["output"] == "等待人工审批…"


# ── tools/generated 与 tools/custom 自动发现（Phase 5） ──────


_TOOL_MODULE = """
def {fn}(args):
    return "{ret}"

TOOL = {{
    "name": "{name}",
    "description": "d",
    "parameters": {{"type": "object", "properties": {{}}}},
    "callback": {fn},
}}
"""


def _write_tool(proj, subdir, name, ret):
    path = proj.path / "tools" / subdir / f"{name}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_TOOL_MODULE.format(fn=name, name=name, ret=ret), encoding="utf-8")


def test_generated_tools_are_auto_discovered(tmp_config):
    """元 agent 生成的工具落盘即可用，不需要往 registry.py 里追加 import。"""
    proj = Project.create(tmp_config, "自动发现")
    _write_tool(proj, "generated", "gen_tool", "from-generated")
    tools, error = load_tool_registry(proj)
    assert error is None
    assert tools["gen_tool"]({}) == "from-generated"


def test_custom_tools_are_auto_discovered(tmp_config):
    """验收标准第 2 条：开发者在 tools/custom/ 手写工具 → Play 能加载。
    以前必须手动在 registry.py 里 import，这里补上。"""
    proj = Project.create(tmp_config, "手写工具")
    _write_tool(proj, "custom", "hand_tool", "from-custom")
    tools, error = load_tool_registry(proj)
    assert error is None
    assert tools["hand_tool"]({}) == "from-custom"


def test_custom_overrides_generated_for_the_same_name(tmp_config):
    """验收标准第 3 条：重新生成 generated/ 不该盖掉手写的实现。两个目录分开
    存 + custom 后加载，这条就是结构性成立的。"""
    proj = Project.create(tmp_config, "同名覆盖")
    _write_tool(proj, "generated", "shared", "from-generated")
    _write_tool(proj, "custom", "shared", "from-custom")
    tools, _ = load_tool_registry(proj)
    assert tools["shared"]({}) == "from-custom"


def test_registry_py_still_wins_over_both_directories(tmp_config):
    """registry.py 是最高优先级的手动出口——自动发现不该夺走它的控制权。"""
    proj = Project.create(tmp_config, "registry 优先")
    _write_tool(proj, "generated", "shared", "from-generated")
    _write_tool(proj, "custom", "shared", "from-custom")
    (proj.path / "tools" / "registry.py").write_text(
        'def get_tools():\n    return {"shared": lambda args: "from-registry"}\n',
        encoding="utf-8",
    )
    tools, _ = load_tool_registry(proj)
    assert tools["shared"]({}) == "from-registry"


def test_a_broken_generated_tool_is_reported_without_losing_the_others(tmp_config):
    proj = Project.create(tmp_config, "坏工具")
    _write_tool(proj, "generated", "good_tool", "ok")
    (proj.path / "tools" / "generated" / "bad_tool.py").write_text(
        "raise RuntimeError('boom')\n", encoding="utf-8"
    )
    tools, error = load_tool_registry(proj)
    assert "good_tool" in tools
    assert error is not None and "bad_tool.py" in error


def test_tool_module_without_TOOL_is_reported(tmp_config):
    proj = Project.create(tmp_config, "没有 TOOL")
    (proj.path / "tools" / "generated" / "nope.py").write_text(
        "X = 1\n", encoding="utf-8"
    )
    tools, error = load_tool_registry(proj)
    assert error is not None and "TOOL" in error


def test_readme_in_tool_dirs_is_not_loaded_as_a_tool(tmp_config):
    """新项目的 generated/ 和 custom/ 里各有一个 README.md，不该被当成工具。"""
    proj = Project.create(tmp_config, "README 不算工具")
    tools, error = load_tool_registry(proj)
    assert error is None


def test_generated_tools_reload_each_play(tmp_config):
    """改完工具代码下一次 Play 立刻生效，不用重启后端。"""
    proj = Project.create(tmp_config, "热更新")
    _write_tool(proj, "generated", "t", "v1")
    assert load_tool_registry(proj)[0]["t"]({}) == "v1"
    _write_tool(proj, "generated", "t", "v2")
    assert load_tool_registry(proj)[0]["t"]({}) == "v2"


def test_registry_py_reloads_after_a_same_size_edit(tmp_config):
    """回归：CPython 的 .pyc 缓存按 (mtime, size) 判新旧。同一秒内改成**长度
    相同**的另一份内容，两个 key 都没变，import 会直接用旧字节码——代码改了
    却完全不生效。这条以前是真的挂的（自 Phase 2 起），修法见
    _exec_module_fresh。"""
    proj = Project.create(tmp_config, "registry 热更新")
    registry = proj.path / "tools" / "registry.py"
    registry.write_text(
        'def get_tools():\n    return {"t": lambda args: "v1"}\n', encoding="utf-8"
    )
    assert load_tool_registry(proj)[0]["t"]({}) == "v1"
    registry.write_text(
        'def get_tools():\n    return {"t": lambda args: "v2"}\n', encoding="utf-8"
    )
    assert load_tool_registry(proj)[0]["t"]({}) == "v2"


# ── 平台级执行护栏（max_steps / 累计活跃时间）────────────────────────────


class FakeGuardEngine(FakeStatefulEngine):
    """FakeStatefulEngine + 护栏测试需要的 with_max_steps/subscribe/run：
    with_max_steps 记录调用；run() 阻塞在事件上直到测试放行（模拟长跑
    workflow），让计时器/超时路径可以确定性地触发。"""

    def __init__(self, initial_state: str, run_gate: "threading.Event | None" = None):
        super().__init__(initial_state)
        self.max_steps_calls: list[int] = []
        self.cancel_calls: list[str] = []
        # run_gate=None → run() 立即完成（测试短跑）；传 Event → 可控阻塞。
        self._run_gate = run_gate

    def with_max_steps(self, max_steps):
        self.max_steps_calls.append(max_steps)
        return self

    def with_executor(self, name, executor):
        return self

    def subscribe(self, timeout_ms=5000, max_consecutive_timeouts=999):
        # 一次性迭代器：立即耗尽（PlaySession.events() 的消费者在这里拿不到
        # 事件就退出；真实 broadcast 语义与本测试无关）。
        return iter(())

    def run(self):
        self.calls.append(("run",))
        gate = self._run_gate
        if gate is not None and not gate.is_set():
            # gate 在且未 set → 阻塞到测试放行（模拟长跑 workflow）；
            # gate 已 set 或 run_gate=None → 立即完成。
            self._run_gate.wait(timeout=10)
        self._state = "succeeded"

    def cancel(self, reason):
        self.calls.append(("cancel", reason))
        self._state = "cancelled"
        if self._run_gate is not None:
            self._run_gate.set()


def _make_guard_session(engine: FakeGuardEngine) -> PlaySession:
    session = PlaySession(None, None, None)
    session._engine = engine
    return session


def _patch_guard_constants(monkeypatch, max_active_seconds):
    monkeypatch.setattr(play, "PLAY_MAX_ACTIVE_SECONDS", max_active_seconds)


def test_play_applies_max_steps_75(tmp_config, monkeypatch):
    """play() 必须在构建 engine 时设置 with_max_steps(75)——run 之前。"""
    from studio_backend.play import PlaySession as StudioPlaySession

    project = Project.create(tmp_config, "护栏项目")
    spec = Spec(
        {
            "stages": [
                {"name": "a", "type": "agent"},
                {"name": "end", "type": "terminal"},
            ]
        }
    )
    recorded: list[tuple] = []

    class RecordingEngine:
        def __init__(self, *a, **k):
            self.chained = []

        def with_max_steps(self, n):
            self.chained.append(("with_max_steps", n))
            return self

        def with_executor(self, name, executor):
            self.chained.append(("with_executor", name))
            return self

        def set_context_variable(self, key, value):
            return self

    def fake_engine_factory(*a, **k):
        return RecordingEngine()

    monkeypatch.setattr(
        play.senza,
        "providers",
        type("P", (), {"openai": staticmethod(lambda **k: object())}),
    )
    monkeypatch.setattr(play.senza, "create_os_env", lambda path: object())
    monkeypatch.setattr(play.senza, "WorkflowEngine", fake_engine_factory)
    monkeypatch.setattr(play.senza, "create_judge", lambda cb: cb)
    monkeypatch.setattr(play.senza, "create_executor", lambda cb: cb)

    session = StudioPlaySession = PlaySession(tmp_config, project, spec)
    session.play(inputs={})

    engine = session._engine
    assert ("with_max_steps", play.PLAY_MAX_STEPS) in engine.chained
    assert play.PLAY_MAX_STEPS == 75
    assert ("with_executor", "eda_executor") in engine.chained
    # max_steps 在 with_executor 之前设置（顺序由链条记录顺序体现）
    assert engine.chained[0][0] == "with_max_steps"


def test_resume_does_not_reapply_max_steps(monkeypatch):
    """resume 走 start()，不重建 engine——with_max_steps 只在 play() 里调一次。"""
    _patch_guard_constants(monkeypatch, 60.0)
    gate = threading.Event()
    engine = FakeGuardEngine("paused", gate)
    session = _make_guard_session(engine)

    session.start()  # 模拟 resume 路径：state paused → start()
    gate.set()       # 放行 run()，让线程与计时器正常收尾
    session._thread.join(timeout=5)

    assert engine.max_steps_calls == []  # start() 不触碰 with_max_steps 链
    # 清理检查：线程结束、计时器解除、账本闭合——测试不留后台残留。
    assert not session._thread.is_alive()
    assert session._timeout_timer is None
    assert session._active_since is None


def test_timeout_cancels_active_workflow(monkeypatch):
    """预算到点 → stop(_TIMEOUT_REASON) → engine.cancel(原因)。"""
    gate = threading.Event()
    engine = FakeGuardEngine("running", gate)
    session = _make_guard_session(engine)
    session.play_calls = None
    _patch_guard_constants(monkeypatch, 0.05)
    session.start()
    # 等超时触发（预算 0.05s + 余量）
    deadline = time.monotonic() + 5
    while (
        "cancel",
        play._TIMEOUT_REASON,
    ) not in engine.calls and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ("cancel", play._TIMEOUT_REASON) in engine.calls
    assert session._timed_out is True
    gate.set()


def test_normal_completion_disarms_timer():
    """自然结束：_run_once finally 收账并解除计时器，不再有挂起回调。"""
    engine = FakeGuardEngine("running", None)  # run() 立即返回
    session = _make_guard_session(engine)
    monkeypatch_local = None
    session.start()
    session._thread.join(timeout=5)
    assert session._timeout_timer is None
    assert session._active_since is None
    assert session._active_accum > 0  # 活跃时间被记账
    assert engine.calls[-1] == ("run",)


def test_manual_stop_disarms_timer():
    """手动 Stop 收账并解除计时器——之后迟到的超时回调不再 cancel。"""
    gate = threading.Event()
    engine = FakeGuardEngine("running", gate)
    session = _make_guard_session(engine)
    session.stop("user stop")
    assert session._timeout_timer is None
    assert ("cancel", "user stop") in engine.calls
    gate.set()


def test_paused_time_does_not_consume_budget(monkeypatch):
    """暂停/HITL 期间预算不走：run() 线程退出即收账，暂停期间计时器解除。"""
    _patch_guard_constants(monkeypatch, 60.0)
    release = threading.Event()
    engine = FakeGuardEngine("running", release)
    session = _make_guard_session(engine)

    session.start()  # 开跑（run 阻塞在 gate 上）
    time.sleep(0.05)  # 活跃 ~0.05s
    session.request_pause()  # pause 请求（协作式，run 仍会走到 finally 收账）
    release.set()
    session._thread.join(timeout=5)

    accum_after_pause = session._active_accum
    assert accum_after_pause > 0
    assert session._active_since is None

    # 暂停期间 "消耗" 的墙钟时间远超预算也不影响账本
    time.sleep(0.1)
    assert session._active_accum == accum_after_pause
    # 恢复后预算按剩余值武装（不重置）
    session.resume_run()
    session._thread.join(timeout=5)
    assert session._active_accum >= accum_after_pause


def test_resume_preserves_cumulative_time(monkeypatch):
    _patch_guard_constants(monkeypatch, 10.0)
    gate = threading.Event()
    engine = FakeGuardEngine("running", gate)
    session = _make_guard_session(engine)

    session.start()
    time.sleep(0.05)
    engine._state = "paused"  # 模拟 pause 消费
    gate.set()
    session._thread.join(timeout=5)
    first = session._active_accum
    assert first > 0

    # resume：新计时器按剩余预算武装，账本继续累计。新 gate 让第二轮 run()
    # 真正跑一段时间——复用已 set 的 gate 会让第二轮瞬间结束、计不到时间。
    second_gate = threading.Event()
    engine._run_gate = second_gate
    engine._state = "paused"  # resume_run 守卫要求 paused；run() 结束时假引擎
    # 会把自己置成 succeeded，这里显式摆回 paused 模拟真实 pause 状态。
    session.resume_run()
    time.sleep(0.05)
    second_gate.set()
    session._thread.join(timeout=5)
    assert session._active_accum > first


def test_rapid_resume_before_old_finally_keeps_new_budget(monkeypatch):
    """Resume 与旧 run 线程 finally 交错时，旧线程不得关闭新执行段的账本。

    真实窗口：engine 已进入 Paused，但旧 run() 线程尚未执行 finally；
    用户立即 Resume。start() 会先结算旧段并开启新 epoch，旧 finally 与
    旧 timer 都必须只作用于旧 epoch。
    """
    _patch_guard_constants(monkeypatch, 60.0)

    class RapidResumeEngine:
        def __init__(self):
            self._state = "running"
            self.run_count = 0
            self.pause_seen = threading.Event()
            self.old_finally_gate = threading.Event()
            self.second_gate = threading.Event()

        def state(self):
            return self._state

        def resume(self):
            self._state = "running"

        def run(self):
            self.run_count += 1
            if self.run_count == 1:
                self._state = "paused"
                self.pause_seen.set()
                self.old_finally_gate.wait(timeout=5)
            else:
                self.second_gate.wait(timeout=5)
                self._state = "succeeded"

    engine = RapidResumeEngine()
    session = _make_guard_session(engine)
    session.start()
    assert engine.pause_seen.wait(timeout=5)
    old_thread = session._thread
    old_epoch = session._run_epoch

    session.resume_run()

    assert engine.run_count == 2
    assert session._thread is not old_thread
    assert session._timeout_timer is not None
    assert session._active_since is not None

    session._on_time_budget_expired(old_epoch)
    assert session._timeout_timer is not None
    assert session._active_since is not None
    assert session.state() == "running"

    engine.old_finally_gate.set()
    old_thread.join(timeout=5)
    assert not old_thread.is_alive()
    assert session._timeout_timer is not None
    assert session._active_since is not None
    assert session._thread.is_alive()

    time.sleep(0.05)
    engine.second_gate.set()
    session._thread.join(timeout=5)
    assert session._active_accum > 0.01
    assert session._timeout_timer is None
    assert session._active_since is None


def test_exhausted_budget_blocks_resume(monkeypatch):
    """预算耗尽后 resume/step/审批都不再启动执行，直接 cancel。"""
    _patch_guard_constants(monkeypatch, 0)
    engine = FakeGuardEngine("paused")
    session = _make_guard_session(engine)

    session.start()
    assert ("cancel", play._TIMEOUT_REASON) in engine.calls
    assert session._timed_out is True
    # 没有线程被启动（run 没被调用）
    assert ("run",) not in engine.calls


def test_step_mode_accumulates_budget_across_cycles(monkeypatch):
    """step 模式走真实 start()：每次执行段都计入累计活跃时间，预算不在
    step 之间重置，计时器只按剩余预算武装。两轮 step 循环。"""
    budget = 10.0
    _patch_guard_constants(monkeypatch, budget)
    engine = FakeGuardEngine("paused")
    session = _make_guard_session(engine)

    accum_after_steps = []
    for _ in range(2):
        engine._state = "paused"  # step() 守卫要求 paused
        run_gate = threading.Event()
        engine._run_gate = run_gate
        session.step()  # step → resume + pause + start()（真实 start 路径）
        time.sleep(0.05)  # 本段活跃 ~0.05s
        run_gate.set()  # 放行 run() 收尾（pause 后 run 返回，收账）
        session._thread.join(timeout=5)
        accum_after_steps.append(session._active_accum)

    # 累计增长（第二段比第一段长），未重置
    assert accum_after_steps[0] > 0
    assert accum_after_steps[1] > accum_after_steps[0]
    # 计时器解除、无残留
    assert session._timeout_timer is None
    assert session._active_since is None
    # 预算远未耗尽（每段 ~0.05s，总预算 10s），timed_out 未触发
    assert session._timed_out is False


def test_replay_play_resets_budget_through_public_path(tmp_config, monkeypatch):
    """同一 PlaySession 重放 play()（公共路径）是全新运行：预算清零、
    _timed_out 清除、旧计时器解除、新预算完整。"""
    project = Project.create(tmp_config, "重放项目")
    spec = Spec({"stages": [{"name": "a", "type": "agent"}, {"name": "end", "type": "terminal"}]})

    engines: list = []

    class RecordingEngine(FakeGuardEngine):
        def __init__(self):
            super().__init__("idle")

        def with_max_steps(self, n):
            return self

        def with_executor(self, name, executor):
            return self

        def set_context_variable(self, key, value):
            pass

        def subscribe(self, timeout_ms=5000, max_consecutive_timeouts=999):
            return iter(())

        def run(self):
            self.calls.append(("run",))
            self._state = "succeeded"

    def fake_engine_factory(*a, **k):
        eng = RecordingEngine("idle")
        engines.append(eng)
        return eng

    monkeypatch.setattr(play.senza, "providers", type("P", (), {"openai": staticmethod(lambda **k: object())}))
    monkeypatch.setattr(play.senza, "create_os_env", lambda path: object())
    monkeypatch.setattr(play.senza, "WorkflowEngine", lambda *a, **k: RecordingEngine.__new__(RecordingEngine))
    monkeypatch.setattr(play.senza, "create_judge", lambda cb: cb)
    monkeypatch.setattr(play.senza, "create_executor", lambda cb: cb)

    session = PlaySession(tmp_config, project, spec)
    session.play(inputs={})
    # 第一轮：污染预算状态，模拟一次跑过很久的 session
    session._active_accum = 123.0
    session._timed_out = True

    # 重放：走公开 play() 路径（会重建 engine 并调用 _reset_time_budget）
    session.play(inputs={})

    assert session._active_accum == 0.0
    assert session._timed_out is False
    assert session._timeout_timer is None
    assert session._active_since is None


def test_late_timeout_callback_does_not_overwrite_terminal_state(monkeypatch):
    """迟到的超时回调：state 已终态 → stop() 不做事，不覆盖真实结果。"""
    _patch_guard_constants(monkeypatch, 0.01)
    engine = FakeGuardEngine("succeeded")
    session = _make_guard_session(engine)

    session._on_time_budget_expired()

    # 终态（succeeded）不在 stop() 的守卫集合里 → 没有 cancel 调用
    assert ("cancel", play._TIMEOUT_REASON) not in engine.calls


def test_stop_and_run_once_cleanup_do_not_double_count():
    """stop() 与 _run_once 的 finally 竞争收账时只计一次。"""
    gate = threading.Event()
    engine = FakeGuardEngine("running", gate)
    session = _make_guard_session(engine)
    session._active_since = time.monotonic() - 1.0  # 模拟已跑 1s

    # stop 与 finally 先后都调用收账——锁保证第二次是 no-op
    session.stop("race")
    first = session._active_accum
    session._disarm_time_budget()
    assert session._active_accum == first
    assert session._active_since is None
    gate.set()


# ── 护栏边界与生命周期补充 ────────────────────────────────────────────────


def test_multiple_pause_resume_cycles_accumulate_budget(monkeypatch):
    """≥3 轮 run→pause→resume 循环：
    - 暂停时间不计入预算（循环间 sleep 不改变账本）
    - 活跃时间跨循环累计（只增不减，不重置）
    - 每轮计时器只按剩余预算武装（通过解除后账本连续性体现）"""
    _patch_guard_constants(monkeypatch, 60.0)
    engine = FakeGuardEngine("running")
    session = _make_guard_session(engine)

    accum_snapshots = []
    for cycle in range(3):
        # —— 活跃段：真实 start()，run 阻塞在 gate 上模拟长跑
        gate = threading.Event()
        engine._run_gate = gate
        engine._state = "running"
        session.start()
        time.sleep(0.02)  # 活跃 ~0.02s

        # —— 暂停：放行 run()（pause 是步边界协作式，run 返回即收账）
        engine._state = "paused"
        gate.set()
        session._thread.join(timeout=5)

        accum = session._active_accum
        assert accum > 0
        if accum_snapshots:
            assert accum > accum_snapshots[-1], f"cycle {cycle}: budget must accumulate"
        assert session._active_since is None, "paused: ledger must be closed"

        # —— 暂停等待：暂停期间预算冻结
        time.sleep(0.05)
        assert session._active_accum == accum, "paused time consumed budget"

        # —— resume 用的状态 + 下一轮 gate 由下一循环设置
        accum_snapshots.append(accum)
        session._step_mode = False

    # 单调递增，无重置
    assert accum_snapshots == sorted(accum_snapshots)
    assert all(a > 0 for a in accum_snapshots)
    assert session._timeout_timer is None


def test_multiple_step_mode_cycles_through_real_start(monkeypatch):
    """≥2 次 step() 循环走真实 start()：
    - 每段活跃时间都累计
    - 预算不在 step 之间重置
    - 每轮计时器按剩余预算武装（账本连续性）"""
    _patch_guard_constants(monkeypatch, 60.0)
    engine = FakeGuardEngine("paused")
    session = _make_guard_session(engine)

    for cycle in range(2):
        engine._state = "paused"
        gate = threading.Event()
        engine._run_gate = gate
        session.step()  # step → resume + pause("single-step") + start()
        assert session._step_mode is True
        time.sleep(0.02)
        gate.set()
        session._thread.join(timeout=5)

        assert session._active_accum > 0
        assert session._active_since is None
        assert session._timeout_timer is None  # 段结束即解除

    assert session._timed_out is False


def test_tiny_remaining_budget_cancels_cleanly(monkeypatch):
    """剩余预算 ~1ms：start() 正常武装 1ms 计时器；超时触发 cancel；
    run() 在已 Cancelled 的引擎上启动会失败，被 _run_once 捕获为 run_error，
    不挂起、不拿新预算、无残留计时器/线程。"""
    _patch_guard_constants(monkeypatch, 0.001)
    gate = threading.Event()
    engine = FakeGuardEngine("idle", gate)
    session = _make_guard_session(engine)

    session.start()  # 武装 1ms 计时器并启动线程
    # 等待超时路径完成（≤5s 上限，1ms 预算通常 <0.2s 触发）
    deadline = time.monotonic() + 5
    while session._timeout_timer is not None and time.monotonic() < deadline:
        time.sleep(0.005)
    gate.set()  # 无论如何放行，杜绝线程残留
    if session._thread is not None:
        session._thread.join(timeout=5)

    # 超时触发了 cancel（1ms 预算必然在 run 起飞前后到期）
    assert ("cancel", play._TIMEOUT_REASON) in engine.calls
    assert session._timed_out is True
    # 清理：无武装计时器、无线程、run 线程已结束
    assert session._timeout_timer is None
    assert session._active_since is None
    assert session._thread is None or not session._thread.is_alive()
    # 未获得新预算（timed_out 保持 True，stop 后 cancel 只有一次）
    assert engine.calls.count(("cancel", play._TIMEOUT_REASON)) == 1


def test_timeout_vs_natural_completion_neither_overwrites(monkeypatch):
    """超时与自然完成竞争（Studio 集成层）：引擎在预算边界附近自然完成时，
    两条合法结果都必须收敛且互斥——
    - 引擎先到终态（succeeded）→ stop() 守卫不 cancel，状态保持 succeeded
    - cancel 先拿到引擎（cancelled）→ 后续 run 收尾不得改回
    Runtime 终态保护已由 Runtime 测试覆盖；这里验证 Studio stop() 的守卫
    在两种交错下都不产生错误状态。"""
    _patch_guard_constants(monkeypatch, 0.02)
    gate = threading.Event()
    engine = FakeGuardEngine("running", gate)
    session = _make_guard_session(engine)

    session.start()
    # 竞争窗口：让 run() 自然完成与超时回调几乎同时发生。
    # 假引擎 run() 解除 gate 后立即置 succeeded；计时器在 0.02s 到期。
    gate.set()
    session._thread.join(timeout=5)

    # 无论超时回调是否已经/将要触发：终态一旦确立不得被改写。
    # 强制再触发一次超时回调（模拟"计时器在完成后到期"的迟到路径）。
    session._on_time_budget_expired()

    final_state = session.state()
    assert final_state in ("succeeded", "cancelled")
    if final_state == "succeeded":
        # 自然完成赢了：迟到回调被 stop() 守卫拦截
        assert ("cancel", play._TIMEOUT_REASON) not in engine.calls
    else:
        # 超时赢了：cancel 合法发生
        assert ("cancel", play._TIMEOUT_REASON) in engine.calls
    # 计时器收尾干净
    assert session._timeout_timer is None
    assert session._active_since is None


def test_timeout_during_pause_boundary_cancels_paused_workflow(monkeypatch):
    """pause 恰好在预算边界发生：计时器在 run() 收尾前到期 → stop() 看到的是
    running/paused → cancel 合法（预算确实耗尽）；pause 后迟到回调不得再次
    cancel（stop 幂等 + 状态守卫）。"""
    _patch_guard_constants(monkeypatch, 0.05)
    gate = threading.Event()
    engine = FakeGuardEngine("running", gate)
    session = _make_guard_session(engine)

    session.start()
    time.sleep(0.06)  # 越过预算边界（0.05s）
    engine._state = "paused"  # 模拟 pause 恰在此时发生
    gate.set()
    session._thread.join(timeout=5)

    # 此时预算已尽（活跃 ~0.06s ≥ 0.05s 预算）。竞争窗口内的两种合法结果：
    # (a) 计时器在 _run_once 收账解除前到期 → 回调看到 running/paused，
    #     stop() 合法 cancel（预算确实在活跃期内耗尽）→ 状态变为 cancelled；
    # (b) 收账先解除计时器 → 回调是迟到者，被 stop() 幂等/守卫拦截 →
    #     状态保持 paused。两种都合法；绝不出现 running 或二次翻转。
    state_before = session.state()
    assert state_before in ("paused", "cancelled")
    session._on_time_budget_expired()
    # 幂等：同一到期回调重复触发不得再次改变状态。
    if state_before == "cancelled":
        assert session.state() == "cancelled"
    else:
        assert session.state() in ("paused", "cancelled")
    assert session._timeout_timer is None
    assert session._active_since is None
    assert not (session._thread is not None and session._thread.is_alive())


# ── E1 回归：过期 HITL 决定（引擎已被终态化）必须无害 ─────────────────────


def test_submit_decision_after_cancelled_is_harmless():
    """回归 E1：15 分钟护栏在 HITL 等待期间到期 → 引擎 Cancelled → 用户
    提交过期决定。必须不 raise、状态保持 Cancelled、不重启、不写 context。"""
    engine = FakeGuardEngine("cancelled")
    session = _make_guard_session(engine)

    session.submit_decision("gate_review", "approve")  # 不得抛异常

    assert session.state() == "cancelled"
    # 无 resume、无 context 写入、无 start —— 决定被整体忽略。
    assert ("resume",) not in engine.calls
    assert not any(
        c[0] == "set_context_variable" and c[1].startswith("__decision_")
        for c in engine.calls
        if len(c) >= 2 and isinstance(c[1], str)
    )
    assert session._thread is None


def test_repeated_stale_decisions_after_cancelled_are_idempotent(monkeypatch):
    """过期决定重复提交同样无害（幂等）。"""
    _patch_guard_constants(monkeypatch, 60.0)
    engine = FakeGuardEngine("cancelled")
    session = _make_guard_session(engine)
    session._active_accum = 900.0  # 预算已耗尽的场景

    for _ in range(3):
        session.submit_decision("gate_review", "approve")

    assert session.state() == "cancelled"
    assert ("resume",) not in engine.calls
    assert session._active_accum == 900.0  # 预算也不被触碰


def test_submit_decision_while_running_is_ignored(monkeypatch):
    """引擎 running 时收到的决定是重复/过期消息（审批卡只应在 paused 出现）。
    旧行为会调 resume() → Runtime 对 Running 抛 InvalidStatus → WS 连接被打死。
    新守卫必须静默忽略。"""
    engine = FakeGuardEngine("running")
    session = _make_guard_session(engine)
    started = []
    monkeypatch.setattr(session, "start", lambda: started.append(True))

    session.submit_decision("gate_review", "approve")

    assert ("resume",) not in engine.calls
    assert started == []
    assert session.state() == "running"


def test_submit_decision_still_works_when_paused(monkeypatch):
    """正常 HITL 路径不受守卫影响：paused → 决定照常 resume + start。"""
    engine = FakeGuardEngine("paused")
    session = _make_guard_session(engine)
    started = []
    monkeypatch.setattr(session, "start", lambda: started.append(True))

    session.submit_decision("gate_review", "approve")

    assert ("set_context_variable", decision_context_key("gate_review"), "approve") in engine.calls
    assert ("resume",) in engine.calls
    assert started == [True]


def test_submit_decision_failed_still_resumes(monkeypatch):
    """Failed/HITL 语义保持：Runtime resume 显式支持 Failed → Paused 恢复，
    失败后的决定必须照常生效（不能被新守卫误拦）。"""
    engine = FakeGuardEngine("failed")
    session = _make_guard_session(engine)
    started = []
    monkeypatch.setattr(session, "start", lambda: started.append(True))

    session.submit_decision("gate_review", "reject")

    assert ("set_context_variable", decision_context_key("gate_review"), "reject") in engine.calls
    assert ("resume",) in engine.calls
    assert started == [True]


def test_submit_decision_vs_concurrent_cancel_does_not_raise(monkeypatch):
    """回归 E2（并发窗口）：submit_decision 的 state 守卫读到底后、resume()
   执行前，stop()（用户 Stop 或 15 分钟超时计时器线程）把引擎置为
   Cancelled——resume() 会抛 HarnessStateError。该异常发生在 WS 事件循环
   线程（app.py 的 submit_decision 分支无 try/except），会把整个 WebSocket
   连接打死。真实场景：预算在 HITL 等待中耗尽，用户恰在此时点批准。
   守卫只能缩小窗口，不能消除——resume 调用本身必须容忍终态竞争。"""
    engine = FakeGuardEngine("paused")
    session = _make_guard_session(engine)
    started = []
    monkeypatch.setattr(session, "start", lambda: started.append(True))

    # 构造竞争：守卫读到 paused 之后、resume 之前，引擎被终态化。
    # 用 set_context_variable 的回调时机触发——它恰好在守卫之后、resume
    # 之前被调用（submit_decision 的真实调用顺序）。
    original_set = engine.set_context_variable

    def set_then_cancel(key, value):
        original_set(key, value)
        engine._state = "cancelled"  # 模拟并发 cancel 已落定

    engine.set_context_variable = set_then_cancel
    # 真引擎 resume 对 Cancelled 抛 HarnessStateError——假引擎同样抛。
    def racy_resume():
        engine.calls.append(("resume",))
        if engine._state == "cancelled":
            raise play.senza.HarnessStateError(
                "run: task is not Idle/Paused/Running (status=Cancelled)"
            )

    engine.resume = racy_resume

    # 不得抛——决定被静默放弃，WS 连接存活。
    session.submit_decision("gate_review", "approve")

    assert session.state() == "cancelled"
    assert started == []  # 引擎已终态，绝不能重启
