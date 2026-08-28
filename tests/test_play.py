"""Play executor/judge 回调测试（不依赖真实 LLM 调用）。

与 test_tools.py 同一模式：直接调用 make_executor/make_judge 产出的回调
闭包，而不经过 senza.create_executor/create_judge 包装（不暴露 .callback）。
"""
from studio_backend.play import build_route_maps, make_executor, make_judge


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
    executor = make_executor({}, "test-model", provider=None, env=None)
    result = executor({"step_id": "ghost"})
    assert result["structured"]["route_key"] == "error"
    assert "ghost" in result["output"]


def test_executor_rejects_unsupported_type():
    stage_by_name = {"check1": {"name": "check1", "type": "checker"}}
    executor = make_executor(stage_by_name, "test-model", provider=None, env=None)
    result = executor({"step_id": "check1"})
    assert result["structured"]["route_key"] == "error"
    assert "checker" in result["output"]
    assert "Phase 3" in result["output"]
