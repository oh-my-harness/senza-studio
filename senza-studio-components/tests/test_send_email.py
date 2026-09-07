import smtplib

import pytest

from senza_studio_components.tools import send_email


class FakeSMTP:
    instances = []
    raise_on_login = None

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.calls = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        if FakeSMTP.raise_on_login:
            raise FakeSMTP.raise_on_login
        self.calls.append(("login", user, password))

    def send_message(self, message):
        self.calls.append(("send_message", message["To"], message["Subject"], message["From"]))


@pytest.fixture(autouse=True)
def _reset_fake_smtp(monkeypatch):
    FakeSMTP.instances = []
    FakeSMTP.raise_on_login = None
    # 每个测试从干净的环境开始——否则本机真实配的 SMTP 环境变量会串进来。
    for key in (
        "SENZA_SMTP_HOST", "SENZA_SMTP_PORT", "SENZA_SMTP_USER",
        "SENZA_SMTP_PASSWORD", "SENZA_SMTP_FROM", "SENZA_SMTP_USE_TLS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(send_email.smtplib, "SMTP", FakeSMTP)
    yield
    FakeSMTP.instances = []
    FakeSMTP.raise_on_login = None


@pytest.fixture
def smtp_env(monkeypatch):
    monkeypatch.setenv("SENZA_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SENZA_SMTP_USER", "bot@example.com")
    monkeypatch.setenv("SENZA_SMTP_PASSWORD", "secret")


def test_run_sends_email_with_configured_credentials(smtp_env):
    result = send_email.run({"to": "user@example.com", "subject": "Hi", "body": "hello"})
    assert result == {"sent": True, "to": "user@example.com"}

    smtp = FakeSMTP.instances[0]
    assert smtp.host == "smtp.example.com"
    assert smtp.port == 587
    assert "starttls" in smtp.calls
    assert ("login", "bot@example.com", "secret") in smtp.calls


def test_run_respects_custom_port(smtp_env, monkeypatch):
    monkeypatch.setenv("SENZA_SMTP_PORT", "2525")
    send_email.run({"to": "user@example.com", "subject": "Hi", "body": "hello"})
    assert FakeSMTP.instances[0].port == 2525


def test_run_uses_smtp_from_over_user(smtp_env, monkeypatch):
    monkeypatch.setenv("SENZA_SMTP_FROM", "noreply@example.com")
    send_email.run({"to": "user@example.com", "subject": "Hi", "body": "hello"})
    sent = [c for c in FakeSMTP.instances[0].calls if c[0] == "send_message"][0]
    assert sent[3] == "noreply@example.com"


def test_run_skips_starttls_when_disabled(smtp_env, monkeypatch):
    monkeypatch.setenv("SENZA_SMTP_USE_TLS", "0")
    send_email.run({"to": "user@example.com", "subject": "Hi", "body": "hello"})
    assert "starttls" not in FakeSMTP.instances[0].calls


# ── auth is optional ─────────────────────────────────────


def test_run_skips_login_when_no_password_configured(monkeypatch):
    """回归测试：不支持 AUTH 扩展的服务器（本地 relay、按 IP 授权的内网
    邮件网关）上无条件 login() 会直接报 "SMTP AUTH extension not supported
    by server"——实测在本地 relay 上踩到过。没配密码就不该登录。"""
    monkeypatch.setenv("SENZA_SMTP_HOST", "localhost")
    monkeypatch.setenv("SENZA_SMTP_FROM", "studio@example.com")

    result = send_email.run({"to": "user@example.com", "subject": "Hi", "body": "hello"})

    assert result["sent"] is True
    assert not any(c[0] == "login" for c in FakeSMTP.instances[0].calls if isinstance(c, tuple))


def test_run_errors_when_password_set_but_user_missing(monkeypatch):
    monkeypatch.setenv("SENZA_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SENZA_SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SENZA_SMTP_FROM", "x@example.com")
    with pytest.raises(send_email.SendEmailError, match="SENZA_SMTP_USER"):
        send_email.run({"to": "user@example.com", "subject": "Hi", "body": "hello"})


# ── validation / error surfaces ──────────────────────────


def test_run_requires_to(smtp_env):
    with pytest.raises(send_email.SendEmailError, match="to"):
        send_email.run({"subject": "Hi", "body": "hello"})


def test_run_missing_host_raises_clear_error():
    with pytest.raises(send_email.SendEmailError, match="SENZA_SMTP_HOST"):
        send_email.run({"to": "user@example.com", "subject": "Hi", "body": "hello"})


def test_run_missing_sender_address_raises_clear_error(monkeypatch):
    monkeypatch.setenv("SENZA_SMTP_HOST", "smtp.example.com")
    with pytest.raises(send_email.SendEmailError, match="sender address"):
        send_email.run({"to": "user@example.com", "subject": "Hi", "body": "hello"})


def test_run_non_numeric_port_raises_clear_error(smtp_env, monkeypatch):
    monkeypatch.setenv("SENZA_SMTP_PORT", "not-a-number")
    with pytest.raises(send_email.SendEmailError, match="must be a number"):
        send_email.run({"to": "user@example.com", "subject": "Hi", "body": "hello"})


def test_run_wraps_smtp_errors_with_context(smtp_env):
    FakeSMTP.raise_on_login = smtplib.SMTPAuthenticationError(535, b"bad creds")
    with pytest.raises(send_email.SendEmailError, match="SMTP error"):
        send_email.run({"to": "user@example.com", "subject": "Hi", "body": "hello"})


def test_run_wraps_connection_errors_with_host_and_port(smtp_env, monkeypatch):
    def boom(host, port, timeout=None):
        raise ConnectionRefusedError("connection refused")

    monkeypatch.setattr(send_email.smtplib, "SMTP", boom)
    with pytest.raises(send_email.SendEmailError, match="could not connect to smtp.example.com:587"):
        send_email.run({"to": "user@example.com", "subject": "Hi", "body": "hello"})
