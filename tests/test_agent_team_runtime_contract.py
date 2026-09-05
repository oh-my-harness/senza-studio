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
        )
        with TestClient(create_app(config)) as client:
            startup = client.get("/api/team/startup")
            projects = client.get("/api/team/projects")
            templates = client.get("/api/team/templates")
            with client.websocket_connect("/ws/team"):
                pass

        assert startup.status_code == 200
        assert startup.json()["recovery"]["status"] == "healthy"
        assert projects.status_code == 200
        assert projects.json() == {"projects": []}
        assert templates.status_code == 200
        template_ids = {template["id"] for template in templates.json()["templates"]}
        assert "coding-team" in template_ids
        assert token not in startup.text
        assert token not in projects.text
        assert token not in templates.text
    _reset_state()
