import pytest

from studio_backend.server import backend_port


def test_backend_port_defaults_to_7878(monkeypatch):
    monkeypatch.delenv("SENZA_STUDIO_PORT", raising=False)

    assert backend_port() == 7878


def test_backend_port_accepts_valid_port(monkeypatch):
    monkeypatch.setenv("SENZA_STUDIO_PORT", "9000")

    assert backend_port() == 9000


@pytest.mark.parametrize("value", ["7878.1", "0", "65536"])
def test_backend_port_rejects_invalid_port(monkeypatch, value):
    monkeypatch.setenv("SENZA_STUDIO_PORT", value)

    with pytest.raises(ValueError):
        backend_port()
