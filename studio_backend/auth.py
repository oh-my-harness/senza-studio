"""Authentication helpers for the local Senza Studio API."""
from __future__ import annotations

import hmac
import string
from typing import Any


API_COOKIE_NAME = "senza_studio_api"
WEBSOCKET_TOKEN_PROTOCOL_PREFIX = "senza-studio-bearer-"
MIN_API_TOKEN_LENGTH = 32
MAX_API_TOKEN_LENGTH = 256
API_TOKEN_CHARACTERS = frozenset(
    string.ascii_letters + string.digits + "!#$%&'*+-.^_`|~"
)


def is_valid_api_token(token: str) -> bool:
    return (
        MIN_API_TOKEN_LENGTH <= len(token) <= MAX_API_TOKEN_LENGTH
        and all(character in API_TOKEN_CHARACTERS for character in token)
    )


def token_matches(provided: str, expected: str) -> bool:
    return hmac.compare_digest(
        provided.encode("utf-8"),
        expected.encode("utf-8"),
    )


def bearer_token(authorization: str | None) -> str:
    if authorization is None:
        return ""
    scheme, separator, credential = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer":
        return ""
    return credential


def http_request_is_authenticated(request: Any, expected_token: str) -> bool:
    credentials: list[str] = []
    authorization_token = bearer_token(request.headers.get("authorization"))
    if authorization_token:
        credentials.append(authorization_token)
    cookie_token = request.cookies.get(API_COOKIE_NAME, "")
    if cookie_token:
        credentials.append(cookie_token)
    if not credentials:
        return False
    return all(token_matches(token, expected_token) for token in credentials)


def websocket_token(websocket: Any) -> str:
    credentials: list[str] = []
    authorization_token = bearer_token(websocket.headers.get("authorization"))
    if authorization_token:
        credentials.append(authorization_token)
    cookie_token = websocket.cookies.get(API_COOKIE_NAME, "")
    if cookie_token:
        credentials.append(cookie_token)

    offered_protocols = websocket.headers.get("sec-websocket-protocol", "")
    credentials.extend(
        protocol.strip()
        for protocol in offered_protocols.split(",")
        if protocol.strip().startswith(WEBSOCKET_TOKEN_PROTOCOL_PREFIX)
    )
    if len(credentials) != 1:
        return ""
    credential = credentials[0]
    if credential.startswith(WEBSOCKET_TOKEN_PROTOCOL_PREFIX):
        credential = credential[len(WEBSOCKET_TOKEN_PROTOCOL_PREFIX) :]
    return credential


def websocket_is_authenticated(websocket: Any, expected_token: str) -> bool:
    credential = websocket_token(websocket)
    return bool(credential) and token_matches(credential, expected_token)
