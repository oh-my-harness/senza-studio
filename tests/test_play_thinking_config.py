"""Focused regression: per-stage thinking_level / max_tokens wiring.

Local capture server only — no external LLM call. Drives the REAL
play.make_executor + play.create_provider so the assertions cover the actual
production request-builder, not a mock.
"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import senza
import senza_studio_runtime.play as play

SSE_OK = (
    b'data: {"choices":[{"index":0,"delta":{"role":"assistant"}}]}\n\n'
    b'data: {"choices":[{"index":0,"delta":{"content":"ok"}}]}\n\n'
    b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
    b'data: [DONE]\n\n'
)
SSE_ROUTE = (
    b'data: {"choices":[{"index":0,"delta":{"role":"assistant"}}]}\n\n'
    b'data: {"choices":[{"index":0,"delta":{"content":"{\\"route\\": \\"OUTCOME_PROPOSAL\\"}"}}]}\n\n'
    b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
    b'data: [DONE]\n\n'
)
ERR_400 = (b'{"error": {"message": "invalid request: response_format is not '
           b'supported by this endpoint"}}')


class _Capture:
    def __init__(self, fail_first=False):
        self.bodies = []
        self.fail_first = fail_first

    def make_handler(self):
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                outer.bodies.append(json.loads(self.rfile.read(n)))
                if outer.fail_first and len(outer.bodies) == 1:
                    code, ctype, payload = 400, "application/json", ERR_400
                else:
                    code, ctype, payload = 200, "text/event-stream", SSE_OK
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *a):
                pass
        return H


class _Emit:
    def text_delta(self, text): pass
    def turn_start(self, index): pass
    def turn_end(self, index): pass
    def compaction_start(self): pass
    def compaction_end(self): pass
    def tool_call_start(self, uid, name): pass
    def tool_call_end(self, uid, args): pass
    def tool_execution_start(self, uid, name): pass
    def tool_execution_end(self, uid, ok, error=None): pass


@pytest.fixture
def capture():
    # Reqwest (senza 的 Rust 传输层) 读取 HTTP_PROXY/HTTPS_PROXY 环境变量；
    # 本机的 NO_PROXY 通配条目（如 127.*）reqwest 识别不了，会把回环地址
    # 的请求转进代理，代理失败 → provider "server error"。测试环境必须
    # 显式禁代理，保证请求真的打到这里起的 capture server。
    proxy_vars = [k for k in os.environ
                  if k.lower() in ("http_proxy", "https_proxy", "all_proxy")]
    saved = {k: os.environ.pop(k) for k in proxy_vars}
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    try:
        cap = _Capture()
        srv = HTTPServer(("127.0.0.1", 0), cap.make_handler())
        cap.base_url = f"http://127.0.0.1:{srv.server_address[1]}"
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        yield cap
        srv.shutdown()
    finally:
        os.environ.pop("NO_PROXY", None)
        for key, value in saved.items():
            os.environ[key] = value


def _make_executor(capture, stage_extra, routes=None, stage_name="gm",
                   model="capture-model"):
    stage = {"name": stage_name, "type": "agent",
             "prompt_template": "Reply with the route JSON only."}
    stage.update(stage_extra)
    provider = play.create_provider("local-only", capture.base_url)
    return play.make_executor({stage_name: stage},
                              {stage_name: routes or {"DONE": "t"}},
                              model, provider, senza.create_os_env(),
                              {"engine": None}, None, None, [])


def _drive(executor, step_id="gm", timeout=45):
    result = {}

    def run():
        try:
            result["ret"] = executor({"step_id": step_id, "context": {},
                                      "emit": _Emit()})
        except Exception as e:  # noqa: BLE001
            result["err"] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    return result


def test_stage_without_thinking_props_request_unchanged(capture):
    result = _drive(_make_executor(capture, {}))
    assert "err" not in result, result.get("err")
    body = capture.bodies[0]
    assert "reasoning_effort" not in body
    assert body["max_tokens"] == 8192           # harness default, unchanged
    assert "response_format" not in body        # single route: no json_object


def test_stage_with_thinking_level_low(capture):
    result = _drive(_make_executor(capture, {"thinking_level": "low"}))
    assert "err" not in result, result.get("err")
    assert capture.bodies[0].get("reasoning_effort") == "low"


def test_stage_with_max_tokens_2048(capture):
    result = _drive(_make_executor(capture, {"max_tokens": 2048}))
    assert "err" not in result, result.get("err")
    assert capture.bodies[0]["max_tokens"] == 2048


def test_structured_stage_keeps_response_format(capture):
    result = _drive(_make_executor(capture, {"json_mode": True},
                                   routes={"OUTCOME_PROPOSAL": "t", "ERROR": "e"}))
    assert "err" not in result, result.get("err")
    assert capture.bodies[0].get("response_format") == {"type": "json_object"}


def test_structured_stage_defaults_to_no_response_format(capture):
    """默认契约是"叙事 + 末尾 route JSON"，不是 JSON-only；json_object 会
    与它冲突（DeepSeek 下会吐占位对象或漏 route）。"""
    result = _drive(_make_executor(capture, {},
                                   routes={"OUTCOME_PROPOSAL": "t", "ERROR": "e"}))
    assert "err" not in result, result.get("err")
    assert "response_format" not in capture.bodies[0]


def test_format_fallback_rebuild_preserves_thinking_settings(capture, monkeypatch):
    """response_format 400 兜底：重建的 harness 必须保留 thinking_level/max_tokens。

    真实网关对 {"type":"json_object"} 的 400 不会以异常形态穿过本地桩（SDK 把
    它吞成空输出），所以按仓库既有测试的惯例在 _run_agent_step 缝隙上模拟
    "第一次尝试抛出 format 拒绝"，用 HarnessBuilder 间谍验证两次构建的差异，
    并用真实第二次请求验证 wire 上参数齐全。
    """
    real_builder = senza.HarnessBuilder
    records = []

    class SpyBuilder:
        def __init__(self, model):
            self._b = real_builder(model)
            self.log = []
            records.append(self.log)

        def _wrap(self, name):
            def method(*a, **k):
                self.log.append((name,) + a)
                out = getattr(self._b, name)(*a, **k)
                return self if out is self._b else out
            return method

        def __getattr__(self, name):
            if name in ("provider", "env", "plugin", "response_format",
                        "thinking_level", "max_tokens", "model_info",
                        "temperature", "stream_options", "retry", "hooks",
                        "mcp_server", "skill", "skills", "budget", "usage_ledger"):
                return self._wrap(name)
            return getattr(self._b, name)

        def build(self):
            return self._b.build()

    monkeypatch.setattr(senza, "HarnessBuilder", SpyBuilder)
    real_run = play._run_agent_step
    calls = []

    def fake_run(harness, prompt, emit):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("provider error: invalid request: "
                               "response_format json_object rejected")
        return real_run(harness, prompt, emit)

    monkeypatch.setattr(play, "_run_agent_step", fake_run)

    result = _drive(_make_executor(
        capture, {"thinking_level": "low", "max_tokens": 2048, "json_mode": True},
        routes={"OUTCOME_PROPOSAL": "t", "ERROR": "e"}))
    assert "err" not in result, result.get("err")
    assert len(calls) == 2, f"expected exactly one fallback, got {len(calls)}"
    assert len(records) == 2

    def names(log):
        return [entry[0] for entry in log]

    assert "response_format" in names(records[0])       # attempt 1: json_object set
    assert "response_format" not in names(records[1])   # fallback dropped it
    assert ("thinking_level", "low") in records[0]
    assert ("thinking_level", "low") in records[1]
    assert ("max_tokens", 2048) in records[0]
    assert ("max_tokens", 2048) in records[1]
    # 真实第二趟 wire：参数仍在
    assert len(capture.bodies) == 1
    second = capture.bodies[0]
    assert second.get("reasoning_effort") == "low"
    assert second["max_tokens"] == 2048
    assert "response_format" not in second


def test_sibling_stage_without_props_not_affected(capture):
    stage_by_name = {
        "gm": {"name": "gm", "type": "agent",
               "prompt_template": "Reply with the route JSON only.",
               "thinking_level": "low", "max_tokens": 2048},
        "other": {"name": "other", "type": "agent",
                  "prompt_template": "Say hi."},
    }
    provider = play.create_provider("local-only", capture.base_url)
    executor = play.make_executor(
        stage_by_name,
        {"gm": {"OUTCOME_PROPOSAL": "t", "ERROR": "e"}, "other": {"DONE": "t"}},
        "capture-model", provider, senza.create_os_env(), {"engine": None},
        None, None, [])
    result = _drive(executor, step_id="other")
    assert "err" not in result, result.get("err")
    assert len(capture.bodies) == 1
    assert "reasoning_effort" not in capture.bodies[0]
    result2 = _drive(executor, step_id="gm")
    assert "err" not in result2, result2.get("err")
    assert capture.bodies[1].get("reasoning_effort") == "low"
    assert capture.bodies[1]["max_tokens"] == 2048
