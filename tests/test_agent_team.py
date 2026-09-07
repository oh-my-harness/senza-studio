"""Agent Team runtime proxy tests."""
from __future__ import annotations

import json
import asyncio
import os
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import websockets
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from studio_backend import agent_team
from studio_backend.app import _reset_state, create_app
from studio_backend.config import StudioConfig


RUNTIME_TOKEN = "runtime-token-0123456789abcdef"


class RecordingHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def do_PUT(self) -> None:
        self._handle()

    def do_PATCH(self) -> None:
        self._handle()

    def do_DELETE(self) -> None:
        self._handle()

    def _handle(self) -> None:
        parsed = urlsplit(self.path)
        content_length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(content_length) if content_length else b""
        self.server.requests.append(
            {
                "method": self.command,
                "path": parsed.path,
                "query": parsed.query,
                "authorization": self.headers.get("authorization"),
                "content_type": self.headers.get("content-type"),
                "body": body.decode("utf-8"),
            }
        )

        if parsed.path == "/api/team/redirect":
            self.send_response(302)
            self.send_header("location", "http://127.0.0.1:9/private")
            self.end_headers()
            return
        if parsed.path == "/api/team/conflict":
            self._send(409, {"ok": False, "error": "team already exists"})
            return

        self._send(
            200,
            {
                "ok": True,
                "method": self.command,
                "path": parsed.path,
                "query": parsed.query,
                "authorization": self.headers.get("authorization"),
                "content_type": self.headers.get("content-type"),
                "body": body.decode("utf-8"),
                "token": RUNTIME_TOKEN,
            },
        )

    def _send(self, status_code: int, payload: dict) -> None:
        content = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: object) -> None:
        return


class RecordingServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int]) -> None:
        super().__init__(address, RecordingHandler)
        self.requests = []


@contextmanager
def runtime_server():
    server = RecordingServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@contextmanager
def runtime_event_server():
    loop = asyncio.new_event_loop()
    started = threading.Event()
    holder = {}
    paths = []

    def run_loop() -> None:
        asyncio.set_event_loop(loop)

        async def main() -> None:
            stop = asyncio.Event()

            async def handler(connection) -> None:
                paths.append(connection.request.path)
                await connection.send(
                    json.dumps({"type": "replay", "token": RUNTIME_TOKEN})
                )
                await connection.send(json.dumps({"type": "live", "value": 1}))
                await stop.wait()

            server = await websockets.serve(handler, "127.0.0.1", 0)
            holder["port"] = server.sockets[0].getsockname()[1]
            holder["stop"] = stop
            started.set()
            await stop.wait()
            server.close()
            await server.wait_closed()

        loop.run_until_complete(main())

    thread = threading.Thread(target=run_loop, daemon=True)
    thread.start()
    try:
        assert started.wait(timeout=5)
        yield holder["port"], paths
    finally:
        if started.is_set():
            loop.call_soon_threadsafe(holder["stop"].set)
        thread.join(timeout=5)
        loop.close()


def write_descriptor(path: Path, port: int, mode: int = 0o600) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "llm-harness.studio.panel-descriptor.v1",
                "url": f"http://127.0.0.1:{port}/app/team.html#token={RUNTIME_TOKEN}",
            }
        ),
        encoding="utf-8",
    )
    os.chmod(path, mode)


def make_client(descriptor: str, home: Path) -> TestClient:
    config = StudioConfig(
        home_dir=str(home / ".senza-studio"),
        model="test-model",
        api_key="test-key",
        api_base="",
        agent_team_descriptor=descriptor,
    )
    return TestClient(create_app(config))


def test_proxy_forwards_requests_and_strips_token(tmp_path):
    _reset_state()
    with runtime_server() as server:
        descriptor = tmp_path / "panel.json"
        write_descriptor(descriptor, server.server_address[1])
        with make_client(str(descriptor), tmp_path) as client:
            response = client.get(
                "/api/team/projects?project=p1&token=must-not-forward"
            )

        assert response.status_code == 200
        request = server.requests[0]
        assert request["method"] == "GET"
        assert request["path"] == "/api/team/projects"
        assert request["query"] == "project=p1"
        assert request["authorization"] == f"Bearer {RUNTIME_TOKEN}"
        assert response.json()["ok"] is True
        assert response.json()["token"] == "[redacted]"
        assert response.json()["authorization"] == "Bearer [redacted]"
        assert RUNTIME_TOKEN not in response.text
    _reset_state()


def test_proxy_forwards_method_body_and_content_type(tmp_path):
    _reset_state()
    with runtime_server() as server:
        descriptor = tmp_path / "panel.json"
        write_descriptor(descriptor, server.server_address[1])
        with make_client(str(descriptor), tmp_path) as client:
            response = client.post(
                "/api/team/projects",
                json={"template": "coding-team"},
            )

        assert response.status_code == 200
        request = server.requests[0]
        assert request["method"] == "POST"
        assert request["content_type"] == "application/json"
        assert json.loads(request["body"]) == {"template": "coding-team"}
    _reset_state()


def test_proxy_preserves_runtime_error_response(tmp_path):
    _reset_state()
    with runtime_server() as server:
        descriptor = tmp_path / "panel.json"
        write_descriptor(descriptor, server.server_address[1])
        with make_client(str(descriptor), tmp_path) as client:
            response = client.get("/api/team/conflict")

        assert response.status_code == 409
        assert response.json() == {"ok": False, "error": "team already exists"}
    _reset_state()


def test_proxy_rejects_runtime_redirect(tmp_path):
    _reset_state()
    with runtime_server() as server:
        descriptor = tmp_path / "panel.json"
        write_descriptor(descriptor, server.server_address[1])
        with make_client(str(descriptor), tmp_path) as client:
            response = client.get("/api/team/redirect")

        assert response.status_code == 502
        assert response.json() == {
            "ok": False,
            "error": "Agent Team runtime redirect rejected",
        }
    _reset_state()


def test_limited_request_body_reader_rejects_chunked_oversize(monkeypatch):
    monkeypatch.setattr(agent_team, "MAX_REQUEST_BYTES", 4)

    class StreamingRequest:
        async def stream(self):
            yield b"1234"
            yield b"5"

    with pytest.raises(agent_team.AgentTeamProxyError) as error:
        asyncio.run(agent_team.read_limited_request_body(StreamingRequest()))

    assert error.value.status_code == 413
    assert error.value.message == "Request body is too large"


def test_proxy_requires_private_descriptor(tmp_path):
    _reset_state()
    with runtime_server() as server:
        descriptor = tmp_path / "panel.json"
        write_descriptor(descriptor, server.server_address[1], mode=0o644)
        with make_client(str(descriptor), tmp_path) as client:
            response = client.get("/api/team/projects")

        assert response.status_code == 503
        assert response.json() == {
            "ok": False,
            "error": "Agent Team runtime descriptor is not private",
        }
        assert server.requests == []
    _reset_state()


def test_proxy_rejects_oversized_request(tmp_path, monkeypatch):
    _reset_state()
    monkeypatch.setattr(agent_team, "MAX_REQUEST_BYTES", 4)
    with runtime_server() as server:
        descriptor = tmp_path / "panel.json"
        write_descriptor(descriptor, server.server_address[1])
        with make_client(str(descriptor), tmp_path) as client:
            response = client.post(
                "/api/team/projects",
                content=b"12345",
                headers={"content-type": "text/plain"},
            )

        assert response.status_code == 413
        assert response.json() == {
            "ok": False,
            "error": "Request body is too large",
        }
        assert server.requests == []
    _reset_state()


def test_proxy_rejects_descriptor_symlink(tmp_path):
    _reset_state()
    real_descriptor = tmp_path / "real-panel.json"
    write_descriptor(real_descriptor, 12345)
    descriptor = tmp_path / "panel.json"
    os.symlink(real_descriptor, descriptor)
    with make_client(str(descriptor), tmp_path) as client:
        response = client.get("/api/team/projects")

    assert response.status_code == 503
    assert response.json() == {
        "ok": False,
        "error": "Agent Team runtime is unavailable",
    }
    _reset_state()


def test_proxy_rejects_non_loopback_descriptor(tmp_path):
    _reset_state()


def test_proxy_rejects_invalid_bearer_token_syntax(tmp_path):
    _reset_state()
    descriptor = tmp_path / "panel.json"
    descriptor.write_text(
        json.dumps(
            {
                "schema": "llm-harness.studio.panel-descriptor.v1",
                "url": "http://127.0.0.1:12345/app/team.html#token=invalid token value",
            }
        ),
        encoding="utf-8",
    )
    os.chmod(descriptor, 0o600)
    with make_client(str(descriptor), tmp_path) as client:
        response = client.get("/api/team/projects")

    assert response.status_code == 503
    assert response.json() == {
        "ok": False,
        "error": "Agent Team runtime descriptor is invalid",
    }
    _reset_state()
    descriptor = tmp_path / "panel.json"
    descriptor.write_text(
        json.dumps(
            {
                "schema": "llm-harness.studio.panel-descriptor.v1",
                "url": f"http://example.com/app/team.html#token={RUNTIME_TOKEN}",
            }
        ),
        encoding="utf-8",
    )
    os.chmod(descriptor, 0o600)
    with make_client(str(descriptor), tmp_path) as client:
        response = client.get("/api/team/projects")

    assert response.status_code == 503
    assert response.json() == {
        "ok": False,
        "error": "Agent Team runtime descriptor is invalid",
    }
    _reset_state()


def test_proxy_reports_unconfigured_runtime(tmp_path):
    _reset_state()
    with make_client("", tmp_path) as client:
        response = client.get("/api/team/projects")

    assert response.status_code == 503
    assert response.json() == {
        "ok": False,
        "error": "Agent Team runtime is not configured",
    }
    _reset_state()


def test_proxy_reports_unavailable_runtime(tmp_path):
    _reset_state()
    with runtime_server() as server:
        port = server.server_address[1]
    descriptor = tmp_path / "panel.json"
    write_descriptor(descriptor, port)
    with make_client(str(descriptor), tmp_path) as client:
        response = client.get("/api/team/projects")

    assert response.status_code == 502
    assert response.json() == {
        "ok": False,
        "error": "Agent Team runtime unavailable",
    }
    _reset_state()


def test_proxy_rejects_foreign_origin(tmp_path):
    _reset_state()
    with runtime_server() as server:
        descriptor = tmp_path / "panel.json"
        write_descriptor(descriptor, server.server_address[1])
        with make_client(str(descriptor), tmp_path) as client:
            response = client.get(
                "/api/team/projects",
                headers={"origin": "https://evil.example"},
            )

        assert response.status_code == 403
        assert server.requests == []
    _reset_state()


def test_event_proxy_connects_forwards_events_and_strips_token(tmp_path):
    _reset_state()
    with runtime_event_server() as (port, paths):
        descriptor = tmp_path / "panel.json"
        write_descriptor(descriptor, port)
        with make_client(str(descriptor), tmp_path) as client:
            with client.websocket_connect("/ws/team") as events:
                replay = events.receive_json()
                live = events.receive_json()

        assert paths == [f"/api/team/events?token={RUNTIME_TOKEN}"]
        assert replay == {"type": "replay", "token": "[redacted]"}
        assert live == {"type": "live", "value": 1}
    _reset_state()


def test_event_proxy_rejects_foreign_origin(tmp_path):
    _reset_state()
    with runtime_event_server() as (port, _):
        descriptor = tmp_path / "panel.json"
        write_descriptor(descriptor, port)
        with make_client(str(descriptor), tmp_path) as client:
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(
                    "/ws/team",
                    headers={"origin": "https://evil.example"},
                ):
                    pass
    _reset_state()


def test_event_proxy_reports_invalid_descriptor(tmp_path):
    _reset_state()
    descriptor = tmp_path / "panel.json"
    descriptor.write_text("{}", encoding="utf-8")
    os.chmod(descriptor, 0o600)
    with make_client(str(descriptor), tmp_path) as client:
        with client.websocket_connect("/ws/team") as events:
            assert events.receive_json() == {
                "ok": False,
                "error": "Agent Team runtime descriptor is invalid",
            }
            with pytest.raises(WebSocketDisconnect):
                events.receive_json()
    _reset_state()
