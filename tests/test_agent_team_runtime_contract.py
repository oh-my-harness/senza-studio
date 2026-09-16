"""Agent Team contract tests against the real runtime binary."""
from __future__ import annotations

import json
import os
import select
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from studio_backend.app import _reset_state, create_app
from studio_backend.config import StudioConfig


RUNTIME_BIN = Path(
    os.environ.get(
        "SENZA_STUDIO_AGENT_TEAM_BIN",
        Path(__file__).parents[2]
        / "llm-harness-runtime"
        / "target"
        / "debug"
        / "agent-studio",
    )
)
STUDIO_TOKEN = "studio-test-token-0123456789abcdef"


@contextmanager
def real_runtime(tmp_path):
    if not RUNTIME_BIN.is_file():
        pytest.skip(f"Agent Team runtime binary not found: {RUNTIME_BIN}")
    if sys.platform == "win32":
        pytest.skip("The current runtime host is Unix-only")

    data_root = tmp_path / "runtime"
    data_root.mkdir()
    environment = os.environ.copy()
    environment.update(
        {
            "STUDIO_DATA_ROOT": str(data_root),
            "STUDIO_PORT": "0",
            "RUST_LOG": "error",
        }
    )
    process = subprocess.Popen(
        [str(RUNTIME_BIN)],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        ready, _, _ = select.select([process.stdout], [], [], 10)
        if not ready:
            raise AssertionError("Agent Team runtime did not report readiness")
        descriptor_line = process.stdout.readline().strip()
        if not descriptor_line.startswith("STUDIO_PANEL_DESCRIPTOR="):
            raise AssertionError(
                f"Unexpected Agent Team readiness output: {descriptor_line}"
            )
        descriptor_path = Path(
            descriptor_line.removeprefix("STUDIO_PANEL_DESCRIPTOR=")
        )
        if descriptor_path != data_root / "panel.json":
            raise AssertionError("Agent Team descriptor path is unexpected")
        yield descriptor_path
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def test_real_runtime_http_and_event_contract(tmp_path):
    _reset_state()
    with real_runtime(tmp_path) as descriptor_path:
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        parsed = urlsplit(descriptor["url"])
        token = parsed.fragment.removeprefix("token=")
        base_url = f"http://{parsed.netloc}"

        unauthenticated = httpx.get(
            f"{base_url}/api/team/startup",
            trust_env=False,
            timeout=5,
        )
        assert unauthenticated.status_code == 401

        config = StudioConfig(
            home_dir=str(tmp_path / "studio-home"),
            model="test-model",
            api_key="test-key",
            api_base="",
            agent_team_descriptor=str(descriptor_path),
            api_token=STUDIO_TOKEN,
        )
        with TestClient(
            create_app(config),
            headers={"Authorization": f"Bearer {STUDIO_TOKEN}"},
        ) as client:
            startup = client.get("/api/team/startup")
            projects = client.get("/api/team/projects")
            templates = client.get("/api/team/templates")
            settings_configured = client.post(
                "/api/team/settings",
                json={
                    "strong": "contract-model",
                    "main": "contract-model",
                    "cheap": "contract-model",
                    "scout_interval_secs": 0,
                    "base_url": "http://127.0.0.1:9",
                    "api_key": "runtime-contract-key",
                },
            )
            created = client.post(
                "/api/team/projects",
                json={"id": "ui-contract", "name": "UI contract"},
            )
            team_list = client.get("/api/team/projects")
            pulse = client.get("/api/team/pulse?project=ui-contract")
            chat = client.post(
                "/api/team/chat",
                json={
                    "project": "ui-contract",
                    "target": "planner",
                    "text": "runtime contract smoke",
                },
            )
            restarted = client.post("/api/team/projects/restart?id=ui-contract")
            deleted = client.delete("/api/team/projects?id=ui-contract")
            final_projects = client.get("/api/team/projects")
            with client.websocket_connect("/ws/team"):
                pass

        assert startup.status_code == 200
        assert startup.json()["recovery"]["status"] == "healthy"
        assert projects.status_code == 200
        assert projects.json() == {"projects": []}
        assert templates.status_code == 200
        template_ids = {template["id"] for template in templates.json()["templates"]}
        assert "coding-team" in template_ids
        assert settings_configured.status_code == 200
        assert settings_configured.json()["ok"] is True
        assert created.status_code == 201, created.text
        assert created.json() == {"ok": True}
        assert team_list.status_code == 200
        assert [project["id"] for project in team_list.json()["projects"]] == [
            "ui-contract"
        ]
        assert pulse.status_code == 200
        pulse_agents = pulse.json()["agents"]
        assert "planner" in {agent["id"] for agent in pulse_agents}
        assert chat.status_code == 202
        assert chat.json() == {"ok": True}
        assert restarted.status_code == 200
        assert restarted.json() == {"ok": True}
        assert deleted.status_code == 200
        assert deleted.json() == {"ok": True}
        assert final_projects.json() == {"projects": []}
        assert token not in startup.text
        assert token not in projects.text
        assert token not in templates.text
    _reset_state()
