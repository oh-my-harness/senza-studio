"""全局设置（settings.json）测试。"""
import json
import os
import stat

import pytest

from studio_backend.config import StudioConfig
from studio_backend.settings import (
    SECRET_PLACEHOLDER,
    apply_to_environ,
    load_settings,
    masked_values,
    save_settings,
    settings_path,
)


@pytest.fixture
def tmp_config(tmp_path):
    return StudioConfig(
        home_dir=str(tmp_path / ".senza-studio"),
        model="test-model",
        api_key="test-key",
        api_base="",
    )


# ── load / save ──────────────────────────────────────────


def test_load_settings_missing_file_is_empty(tmp_config):
    assert load_settings(tmp_config) == {}


def test_save_then_load_roundtrip(tmp_config):
    save_settings(tmp_config, {"SENZA_SMTP_HOST": "smtp.example.com"})
    assert load_settings(tmp_config)["SENZA_SMTP_HOST"] == "smtp.example.com"


def test_save_merges_into_existing(tmp_config):
    save_settings(tmp_config, {"SENZA_SMTP_HOST": "smtp.example.com"})
    save_settings(tmp_config, {"SENZA_SMTP_USER": "me@example.com"})
    values = load_settings(tmp_config)
    assert values["SENZA_SMTP_HOST"] == "smtp.example.com"
    assert values["SENZA_SMTP_USER"] == "me@example.com"


def test_save_ignores_unknown_keys(tmp_config):
    """别让任意内容写进这个文件——只接受 schema 里声明过的 key。"""
    save_settings(tmp_config, {"EVIL_KEY": "x", "SENZA_SMTP_HOST": "ok"})
    values = load_settings(tmp_config)
    assert "EVIL_KEY" not in values
    assert values["SENZA_SMTP_HOST"] == "ok"


def test_save_empty_string_clears_value(tmp_config):
    save_settings(tmp_config, {"SENZA_SMTP_HOST": "smtp.example.com"})
    save_settings(tmp_config, {"SENZA_SMTP_HOST": ""})
    assert load_settings(tmp_config)["SENZA_SMTP_HOST"] == ""


def test_save_placeholder_keeps_existing_secret(tmp_config):
    """前端拿不到明文密钥，回传的是哨兵——不该因此把已存的密码清空。"""
    save_settings(tmp_config, {"SENZA_SMTP_PASSWORD": "real-secret"})
    save_settings(
        tmp_config,
        {"SENZA_SMTP_PASSWORD": SECRET_PLACEHOLDER, "SENZA_SMTP_HOST": "h"},
    )
    values = load_settings(tmp_config)
    assert values["SENZA_SMTP_PASSWORD"] == "real-secret"
    assert values["SENZA_SMTP_HOST"] == "h"


def test_save_can_replace_secret_with_new_value(tmp_config):
    save_settings(tmp_config, {"SENZA_SMTP_PASSWORD": "old"})
    save_settings(tmp_config, {"SENZA_SMTP_PASSWORD": "new"})
    assert load_settings(tmp_config)["SENZA_SMTP_PASSWORD"] == "new"


def test_settings_file_is_owner_only_readable(tmp_config):
    """含密钥，不该让同机器其它用户读到。"""
    save_settings(tmp_config, {"SENZA_SMTP_PASSWORD": "secret"})
    mode = settings_path(tmp_config).stat().st_mode
    assert not (mode & stat.S_IRGRP), "group should not be able to read"
    assert not (mode & stat.S_IROTH), "others should not be able to read"


def test_load_corrupt_file_is_empty_not_crash(tmp_config):
    path = settings_path(tmp_config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ this is not json", encoding="utf-8")
    assert load_settings(tmp_config) == {}


def test_load_non_dict_json_is_empty(tmp_config):
    path = settings_path(tmp_config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(["a", "list"]), encoding="utf-8")
    assert load_settings(tmp_config) == {}


# ── masking ──────────────────────────────────────────────


def test_masked_values_hides_secrets_only():
    masked = masked_values(
        {"SENZA_SMTP_PASSWORD": "hunter2", "SENZA_SMTP_HOST": "smtp.example.com"}
    )
    assert masked["SENZA_SMTP_PASSWORD"] == SECRET_PLACEHOLDER
    assert masked["SENZA_SMTP_HOST"] == "smtp.example.com"


def test_masked_values_leaves_empty_secret_empty():
    """没设过的密钥不该显示成"已设置"。"""
    assert masked_values({"SENZA_SMTP_PASSWORD": ""})["SENZA_SMTP_PASSWORD"] == ""


# ── environ injection ────────────────────────────────────


def test_apply_to_environ_sets_values(monkeypatch):
    monkeypatch.delenv("SENZA_SMTP_HOST", raising=False)
    apply_to_environ({"SENZA_SMTP_HOST": "smtp.example.com"})
    assert os.environ["SENZA_SMTP_HOST"] == "smtp.example.com"


def test_apply_to_environ_does_not_override_explicit_env_by_default(monkeypatch):
    """显式 export 的环境变量优先——CI/脚本里的配置不该被 GUI 写的文件
    悄悄覆盖。"""
    monkeypatch.setenv("SENZA_SMTP_HOST", "from-shell")
    apply_to_environ({"SENZA_SMTP_HOST": "from-settings-file"})
    assert os.environ["SENZA_SMTP_HOST"] == "from-shell"


def test_apply_to_environ_override_wins_after_explicit_save(monkeypatch):
    """用户刚在设置面板点了保存，就该立刻生效。"""
    monkeypatch.setenv("SENZA_SMTP_HOST", "from-shell")
    apply_to_environ({"SENZA_SMTP_HOST": "just-saved"}, override=True)
    assert os.environ["SENZA_SMTP_HOST"] == "just-saved"


def test_apply_to_environ_skips_empty_values(monkeypatch):
    monkeypatch.delenv("SENZA_SMTP_HOST", raising=False)
    apply_to_environ({"SENZA_SMTP_HOST": ""})
    assert "SENZA_SMTP_HOST" not in os.environ
