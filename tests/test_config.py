"""Studio configuration regression tests."""

from __future__ import annotations

import os
from pathlib import Path

from studio_backend.config import _read_api_token_file


def test_api_token_file_opens_when_nonblock_flag_is_unavailable(
    monkeypatch, tmp_path: Path
):
    token_file = tmp_path / "api-token"
    token_file.write_text("studio-test-token-0123456789abcdef", encoding="utf-8")
    os.chmod(token_file, 0o600)
    monkeypatch.delattr(os, "O_NONBLOCK", raising=False)

    assert (
        _read_api_token_file(str(token_file))
        == "studio-test-token-0123456789abcdef"
    )
