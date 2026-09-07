"""send_email — real smtplib implementation.

Configuration comes from environment variables. In Senza Studio these are
normally set through the settings panel (which writes ~/.senza-studio/
settings.json and injects it into the environment), but plain `export`
also works and takes precedence.

  SENZA_SMTP_HOST      (required)
  SENZA_SMTP_PORT      (default: 587)
  SENZA_SMTP_USER      (optional — see auth note below)
  SENZA_SMTP_PASSWORD  (optional — see auth note below)
  SENZA_SMTP_FROM      (default: SENZA_SMTP_USER)
  SENZA_SMTP_USE_TLS   (default: "1" — set to "0" to disable STARTTLS)

Auth is optional on purpose: plenty of SMTP servers don't support the AUTH
extension at all — local debug servers, and internal/corporate relays that
authorize by source IP rather than credentials. Calling login() against
those fails with "SMTP AUTH extension not supported by server" (hit exactly
this against a real local relay while testing). So login() only runs when a
password is actually configured.

Not tested against a hosted provider like Gmail/SES from this repo — only
against a local relay. Providers requiring app-specific passwords (Gmail
etc.) will reject a normal account password.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


class SendEmailError(RuntimeError):
    pass


def run(args: dict) -> dict:
    """args: {"to": str, "subject": str, "body": str}. Returns {"sent": True, "to": ...}."""
    to = args.get("to")
    subject = args.get("subject", "")
    body = args.get("body", "")
    if not to:
        raise SendEmailError("to is required")

    host = os.environ.get("SENZA_SMTP_HOST")
    if not host:
        raise SendEmailError(
            "missing required setting SENZA_SMTP_HOST "
            "(set it in Studio's settings panel, or export it)"
        )
    try:
        port = int(os.environ.get("SENZA_SMTP_PORT") or "587")
    except ValueError as exc:
        raise SendEmailError(f"SENZA_SMTP_PORT must be a number: {exc}") from exc

    user = os.environ.get("SENZA_SMTP_USER") or ""
    password = os.environ.get("SENZA_SMTP_PASSWORD") or ""
    from_addr = os.environ.get("SENZA_SMTP_FROM") or user
    if not from_addr:
        raise SendEmailError(
            "no sender address — set SENZA_SMTP_FROM (or SENZA_SMTP_USER)"
        )
    use_tls = os.environ.get("SENZA_SMTP_USE_TLS", "1") != "0"

    message = EmailMessage()
    message["From"] = from_addr
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            if use_tls:
                smtp.starttls()
            # 只有真的配了密码才登录——不支持 AUTH 扩展的服务器（本地
            # relay、按 IP 授权的内网邮件网关）上无条件 login() 会直接报
            # "SMTP AUTH extension not supported by server"。
            if password:
                if not user:
                    raise SendEmailError(
                        "SENZA_SMTP_PASSWORD is set but SENZA_SMTP_USER is missing"
                    )
                smtp.login(user, password)
            smtp.send_message(message)
    except SendEmailError:
        raise
    except smtplib.SMTPException as exc:
        raise SendEmailError(f"SMTP error: {exc}") from exc
    except OSError as exc:
        raise SendEmailError(f"could not connect to {host}:{port}: {exc}") from exc

    return {"sent": True, "to": to}
