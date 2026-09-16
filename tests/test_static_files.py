from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from studio_backend.app import create_app
from studio_backend.config import StudioConfig


API_TOKEN = "studio-test-token-0123456789abcdef"


def make_client(tmp_path: Path, static_dir: Path | None = None) -> TestClient:
    config = StudioConfig(
        home_dir=str(tmp_path / "home"),
        model="test-model",
        api_key="test-key",
        api_base="",
        api_token=API_TOKEN,
        static_dir=str(static_dir) if static_dir else "",
    )
    return TestClient(
        create_app(config),
        headers={"Authorization": f"Bearer {API_TOKEN}"},
    )


def test_static_files_serve_index_and_immutable_assets(tmp_path):
    static_dir = tmp_path / "dist"
    assets = static_dir / "assets"
    assets.mkdir(parents=True)
    (static_dir / "index.html").write_text("<html>studio</html>", encoding="utf-8")
    (assets / "app-abc123.js").write_text("console.log('ok')", encoding="utf-8")

    with make_client(tmp_path, static_dir) as client:
        index = client.get("/")
        asset = client.get("/assets/app-abc123.js")
        missing = client.get("/missing.js")

    assert index.status_code == 200
    assert index.text == "<html>studio</html>"
    assert index.headers["content-type"].startswith("text/html")
    assert index.headers["cache-control"] == "no-store"
    assert asset.status_code == 200
    assert asset.headers["content-type"].startswith(
        ("application/javascript", "text/javascript")
    )
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert missing.status_code == 404


def test_static_files_require_authentication(tmp_path):
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html>studio</html>", encoding="utf-8")
    config = StudioConfig(
        home_dir=str(tmp_path / "home"),
        model="test-model",
        api_key="test-key",
        api_base="",
        api_token=API_TOKEN,
        static_dir=str(static_dir),
    )

    with TestClient(create_app(config)) as client:
        response = client.get("/")

    assert response.status_code == 401


def test_static_files_open_when_nonblock_flag_is_unavailable(
    monkeypatch, tmp_path
):
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text(
        "<html>studio</html>", encoding="utf-8"
    )
    monkeypatch.delattr(os, "O_NONBLOCK", raising=False)

    with make_client(tmp_path, static_dir) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.text == "<html>studio</html>"


def test_static_files_reject_unsafe_paths_and_non_regular_files(tmp_path):
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    internal = static_dir / "internal.txt"
    internal.write_text("internal", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (static_dir / "index.html").write_text("<html>studio</html>", encoding="utf-8")
    os.symlink(outside, static_dir / "linked.txt")
    os.symlink(internal, static_dir / "internal-link.txt")
    fifo = static_dir / "fifo"
    os.mkfifo(fifo)

    with make_client(tmp_path, static_dir) as client:
        traversal = client.get("/../outside.txt")
        empty_segment = client.get("/assets//app.js")
        linked = client.get("/linked.txt")
        internal_link = client.get("/internal-link.txt")

    assert traversal.status_code == 404
    assert empty_segment.status_code == 404
    assert linked.status_code == 404
    assert internal_link.status_code == 404
    assert stat.S_ISFIFO(fifo.stat().st_mode)


def test_create_app_rejects_invalid_static_directory(tmp_path):
    config = StudioConfig(
        home_dir=str(tmp_path / "home"),
        model="test-model",
        api_key="test-key",
        api_base="",
        api_token=API_TOKEN,
        static_dir=str(tmp_path / "missing"),
    )
    with pytest.raises(FileNotFoundError):
        create_app(config)


def test_config_reads_static_directory(monkeypatch, tmp_path):
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    monkeypatch.setenv("SENZA_STUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SENZA_STUDIO_API_TOKEN", API_TOKEN)
    monkeypatch.setenv("SENZA_STUDIO_STATIC_DIR", str(static_dir))

    assert StudioConfig.from_env().static_dir == str(static_dir)
