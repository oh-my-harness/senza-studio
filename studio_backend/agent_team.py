"""Secure proxy between Senza Studio and the Agent Team runtime."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import stat
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

import httpx
import websockets
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response


DESCRIPTOR_SCHEMA = "llm-harness.studio.panel-descriptor.v1"
MAX_DESCRIPTOR_BYTES = 64 * 1024
MAX_REQUEST_BYTES = 16 * 1024 * 1024
MIN_TOKEN_LENGTH = 16
PROXY_TIMEOUT_SECONDS = 15.0
WEBSOCKET_OPEN_TIMEOUT_SECONDS = 5.0
WEBSOCKET_CLOSE_TIMEOUT_SECONDS = 5.0
MAX_EVENT_BYTES = 4 * 1024 * 1024
ALLOWED_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
BEARER_TOKEN_CHARACTERS = frozenset(
    string.ascii_letters + string.digits + "!#$%&'*+-.^_`|~"
)


@dataclass(frozen=True)
class AgentTeamRuntime:
    base_url: str
    token: str


class AgentTeamProxyError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def load_agent_team_runtime(descriptor_path: str | Path) -> AgentTeamRuntime:
    descriptor_text = str(descriptor_path).strip()
    if not descriptor_text:
        raise AgentTeamProxyError(
            503,
            "Agent Team runtime is not configured",
        )
    path = Path(descriptor_text)
    try:
        file_descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError:
        raise AgentTeamProxyError(
            503,
            "Agent Team runtime is unavailable",
        ) from None

    try:
        metadata = os.fstat(file_descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise AgentTeamProxyError(
                503,
                "Agent Team runtime descriptor is invalid",
            )
        if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
            raise AgentTeamProxyError(
                503,
                "Agent Team runtime descriptor is not private",
            )
        if metadata.st_size > MAX_DESCRIPTOR_BYTES:
            raise AgentTeamProxyError(
                503,
                "Agent Team runtime descriptor is invalid",
            )

        descriptor_file = os.fdopen(file_descriptor, "r", encoding="utf-8")
        file_descriptor = -1
        with descriptor_file:
            descriptor_content = descriptor_file.read(MAX_DESCRIPTOR_BYTES + 1)
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)

    try:
        descriptor = json.loads(descriptor_content)
        url = descriptor["url"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
        raise AgentTeamProxyError(
            503,
            "Agent Team runtime descriptor is invalid",
        ) from None

    if (
        not isinstance(descriptor, dict)
        or descriptor.get("schema") != DESCRIPTOR_SCHEMA
        or not isinstance(url, str)
    ):
        raise AgentTeamProxyError(
            503,
            "Agent Team runtime descriptor is invalid",
        )

    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise AgentTeamProxyError(
            503,
            "Agent Team runtime descriptor is invalid",
        ) from None

    token_values = parse_qs(parsed.fragment).get("token", [])
    token = token_values[0] if token_values else ""
    host = parsed.hostname
    try:
        loopback = host is not None and ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False

    if (
        parsed.scheme != "http"
        or parsed.username is not None
        or parsed.password is not None
        or not loopback
        or port is None
        or port <= 0
        or not is_valid_bearer_token(token)
    ):
        raise AgentTeamProxyError(
            503,
            "Agent Team runtime descriptor is invalid",
        )

    return AgentTeamRuntime(base_url=f"http://{parsed.netloc}", token=token)


def is_safe_proxy_path(path: str) -> bool:
    if not path or "\\" in path:
        return False
    for segment in path.split("/"):
        if segment in ("", ".", ".."):
            return False
        if any(ord(character) < 32 or ord(character) == 127 for character in segment):
            return False
    return True


def is_valid_bearer_token(token: str) -> bool:
    return (
        MIN_TOKEN_LENGTH <= len(token) <= 256
        and all(character in BEARER_TOKEN_CHARACTERS for character in token)
    )


async def read_limited_request_body(request: Request) -> bytes:
    chunks: list[bytes] = []
    total_size = 0
    async for chunk in request.stream():
        if not chunk:
            continue
        total_size += len(chunk)
        if total_size > MAX_REQUEST_BYTES:
            raise AgentTeamProxyError(
                413,
                "Request body is too large",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _redact_token(value: Any, token: str) -> Any:
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact_token(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _redact_token(item, token) for key, item in value.items()}
    return value


def _proxy_response(response: httpx.Response, token: str) -> Response:
    content = response.content
    content_type = response.headers.get("content-type", "")
    if "json" in content_type.lower():
        try:
            decoded = json.loads(content)
            content = json.dumps(
                _redact_token(decoded, token),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (UnicodeDecodeError, json.JSONDecodeError):
            content = content.replace(token.encode("utf-8"), b"[redacted]")
    else:
        content = content.replace(token.encode("utf-8"), b"[redacted]")

    headers = {"content-type": content_type} if content_type else {}
    return Response(content=content, status_code=response.status_code, headers=headers)


def _query_params(request: Request) -> httpx.QueryParams:
    params = httpx.QueryParams()
    for key, value in request.query_params.multi_items():
        if key.lower() != "token":
            params = params.add(key, value)
    return params


def _error_response(error: AgentTeamProxyError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={"ok": False, "error": error.message},
    )


def install_agent_team_proxy(
    app: FastAPI,
    descriptor_path: str,
    allowed_origins: tuple[str, ...],
) -> None:
    @app.api_route(
        "/api/team/{proxy_path:path}",
        methods=list(ALLOWED_METHODS),
    )
    async def proxy_agent_team(proxy_path: str, request: Request) -> Response:
        if not is_safe_proxy_path(proxy_path):
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": "Invalid Agent Team path"},
            )
        try:
            runtime = load_agent_team_runtime(descriptor_path)
        except AgentTeamProxyError as error:
            return _error_response(error)

        try:
            body = await read_limited_request_body(request)
        except AgentTeamProxyError as error:
            return _error_response(error)
        headers = {"Authorization": f"Bearer {runtime.token}"}
        if "content-type" in request.headers:
            headers["content-type"] = request.headers["content-type"]
        if "accept" in request.headers:
            headers["accept"] = request.headers["accept"]

        client = getattr(app.state, "agent_team_client", None)
        try:
            if client is None:
                async with httpx.AsyncClient(
                    timeout=PROXY_TIMEOUT_SECONDS,
                    follow_redirects=False,
                    trust_env=False,
                ) as request_client:
                    response = await request_client.request(
                        request.method,
                        f"{runtime.base_url}/api/team/{proxy_path}",
                        params=_query_params(request),
                        headers=headers,
                        content=body,
                    )
            else:
                response = await client.request(
                    request.method,
                    f"{runtime.base_url}/api/team/{proxy_path}",
                    params=_query_params(request),
                    headers=headers,
                    content=body,
                )
        except httpx.HTTPError:
            return JSONResponse(
                status_code=502,
                content={"ok": False, "error": "Agent Team runtime unavailable"},
            )

        if 300 <= response.status_code < 400:
            return JSONResponse(
                status_code=502,
                content={"ok": False, "error": "Agent Team runtime redirect rejected"},
            )
        return _proxy_response(response, runtime.token)

    @app.websocket("/ws/team")
    async def proxy_agent_team_events(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin")
        if origin is not None and origin not in allowed_origins:
            await websocket.close(code=1008)
            return

        await websocket.accept()
        try:
            runtime = load_agent_team_runtime(descriptor_path)
        except AgentTeamProxyError as error:
            await websocket.send_json({"ok": False, "error": error.message})
            await websocket.close(code=1011)
            return

        upstream_url = (
            runtime.base_url.replace("http://", "ws://", 1)
            + f"/api/team/events?token={quote(runtime.token, safe='')}"
        )
        try:
            async with websockets.connect(
                upstream_url,
                open_timeout=WEBSOCKET_OPEN_TIMEOUT_SECONDS,
                close_timeout=WEBSOCKET_CLOSE_TIMEOUT_SECONDS,
                ping_interval=20,
                ping_timeout=20,
                max_size=MAX_EVENT_BYTES,
                proxy=None,
            ) as upstream:

                async def relay_events() -> None:
                    async for message in upstream:
                        if isinstance(message, str):
                            await websocket.send_text(
                                message.replace(runtime.token, "[redacted]")
                            )
                        else:
                            await websocket.send_bytes(
                                message.replace(
                                    runtime.token.encode("utf-8"),
                                    b"[redacted]",
                                )
                            )

                async def drain_client() -> None:
                    while True:
                        message = await websocket.receive()
                        if message["type"] == "websocket.disconnect":
                            return
                        await websocket.close(
                            code=1003,
                            reason="Agent Team events are read-only",
                        )
                        return

                relay_task = asyncio.create_task(relay_events())
                drain_task = asyncio.create_task(drain_client())
                _, pending = await asyncio.wait(
                    {relay_task, drain_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

                relay_error = relay_task.exception()
                if relay_error is None:
                    try:
                        await websocket.close(
                            code=1011,
                            reason="Agent Team runtime disconnected",
                        )
                    except (RuntimeError, WebSocketDisconnect):
                        return
                elif isinstance(relay_error, WebSocketDisconnect):
                    return
                else:
                    try:
                        await websocket.close(
                            code=1011,
                            reason="Agent Team runtime unavailable",
                        )
                    except (RuntimeError, WebSocketDisconnect):
                        return
        except (OSError, asyncio.TimeoutError, websockets.WebSocketException):
            try:
                await websocket.send_json(
                    {"ok": False, "error": "Agent Team runtime unavailable"}
                )
                await websocket.close(code=1011)
            except (RuntimeError, WebSocketDisconnect):
                return
