# Senza Studio local API authentication

Senza Studio's backend binds to loopback, but loopback binding alone does not
authenticate the local API. Every endpoint except `/api/health` and
`/auth/bootstrap` requires a per-process API token.

## Configuration

Provide exactly one token source:

```bash
export SENZA_STUDIO_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
```

Alternatively, point `SENZA_STUDIO_API_TOKEN_FILE` to a regular, private file
containing the token. On Unix the file must have mode `0600`; the backend opens
it without following symlinks. Tokens must contain at least 32 ASCII bearer-token
characters. Startup fails closed when no valid token is configured.

## Client authentication

Non-browser clients send:

```http
Authorization: Bearer <senza-studio-api-token>
```

The browser flow exchanges a development token through `POST /auth/bootstrap`
and receives an `HttpOnly`, `SameSite=Strict` session cookie. Electron sets the
same cookie directly in its session before loading the UI. HTTP requests use
the cookie, and WebSocket handshakes accept either the cookie, a Bearer header,
or the `senza-studio-bearer-<token>` WebSocket subprotocol.

The runtime Agent Team token is separate. It remains behind the Studio backend
proxy and is never exposed to the frontend.

## Security boundary

`SENZA_STUDIO_ALLOWED_ORIGINS` still restricts browser origins, and CORS is
limited to those exact origins with credentials. `/api/health` is public only
for readiness checks. API documentation endpoints are disabled.

This boundary rejects unauthenticated local callers and cross-origin browser
requests. It does not defend against malicious software already running as the
same operating-system user; such software may be able to read process
environment variables or cookie storage. That stronger threat model requires
OS-level sandboxing or a platform keyring and remains outside this API layer.
