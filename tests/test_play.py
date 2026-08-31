"""Play executor/judge 回调测试（不依赖真实 LLM 调用）。

与 test_tools.py 同一模式：直接调用 make_executor/make_judge 产出的回调
闭包，而不经过 senza.create_executor/create_judge 包装（不暴露 .callback）。
"""
import studio_backend.play as play
from studio_backend.play import (
    _append_routing_instruction,
    _extract_route,
    build_route_maps,
    make_executor,
    make_judge,
)


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


# ── make_executor ────────────────────────────────────────


def test_executor_rejects_unknown_step():
    executor = make_executor({}, {}, "test-model", provider=None, env=None)
    result = executor({"step_id": "ghost"})
    assert result["structured"]["route_key"] == "error"
    assert "ghost" in result["output"]


def test_executor_rejects_unsupported_type():
    stage_by_name = {"check1": {"name": "check1", "type": "checker"}}
    executor = make_executor(stage_by_name, {}, "test-model", provider=None, env=None)
    result = executor({"step_id": "check1"})
    assert result["structured"]["route_key"] == "error"
    assert "checker" in result["output"]
    assert "Phase 3" in result["output"]


# ── _extract_route (agent-step structured routing) ────────


def test_extract_route_finds_trailing_marker():
    output = 'This looks like a complaint.\n{"route": "complaint"}'
    route, clean = _extract_route(output, ["complaint", "question"])
    assert route == "complaint"
    assert clean == "This looks like a complaint."


def test_extract_route_missing_marker_is_error():
    route, clean = _extract_route("just a plain answer", ["complaint", "question"])
    assert route == "error"
    assert clean == "just a plain answer"


def test_extract_route_unknown_label_is_error():
    output = 'ok\n{"route": "not_a_real_route"}'
    route, clean = _extract_route(output, ["complaint", "question"])
    assert route == "error"
    assert clean == "ok"


def test_extract_route_uses_last_marker_if_multiple():
    output = '{"route": "complaint"} intermediate text {"route": "question"}'
    route, _ = _extract_route(output, ["complaint", "question"])
    assert route == "question"


def test_append_routing_instruction_mentions_all_routes():
    prompt = _append_routing_instruction("classify this", ["complaint", "question"])
    assert prompt.startswith("classify this")
    assert '"complaint"' in prompt
    assert '"question"' in prompt


def test_executor_multi_route_extracts_from_llm_output(monkeypatch):
    """端到端验证 play_executor 的多路由分支实际调用了 _extract_route——
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
        stage_by_name, routes_by_name, "test-model", provider=None, env=None
    )
    result = executor({"step_id": "classify", "context": {}, "emit": None})

    assert result["structured"]["route_key"] == "complaint"
    assert result["output"] == "This is a complaint."
