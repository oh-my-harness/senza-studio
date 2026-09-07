# Agent Team runtime contract for Senza Studio

> Status: draft for issue #1
> Runtime source: `llm-harness-runtime` `agent-team-studio`
> Consumers: Senza Studio desktop/web frontend

## 1. Boundary

Senza Studio owns product UX, desktop integration, navigation, and packaging. The
Agent Team runtime owns team assembly, agent execution, persistence, workspace
authorization, authentication, diagnostics, and the local service boundary.

The frontend must not import Rust crate types or reimplement Agent Team
orchestration. It consumes only the HTTP and WebSocket contract below.

## 2. Service discovery and authentication

The runtime binds to loopback and allocates an ephemeral port unless a developer
explicitly configures a fixed port. It writes a private panel descriptor under
its data root:

```json
{
  "schema": "llm-harness.studio.panel-descriptor.v1",
  "url": "http://127.0.0.1:0/app/team.html#token=..."
}
```

The descriptor currently embeds the token in the legacy panel URL. That URL is
for the runtime's development panel and is not the long-term Senza Studio
handoff. Senza Studio should treat the descriptor as the source of the runtime
base URL and token, but must not copy the token into logs, command lines, or
permanent browser storage.

### Recommended connection mode

Use a Senza Studio backend proxy:

```text
React frontend -> Senza Studio backend -> Agent Team runtime
```

This keeps the runtime token server-side, avoids browser CORS assumptions, and
lets the desktop host own process lifecycle. Direct browser access to the
runtime is reserved for the runtime's development panel.

The proxy must:

- read the runtime descriptor from a configured private path;
- retain the token only in process memory;
- forward requests with `Authorization: Bearer <token>`;
- strip runtime tokens from errors, logs, and responses;
- preserve runtime status codes and JSON error bodies;
- reject redirects to non-loopback upstreams.

Senza Studio's backend mounts the runtime HTTP API at `/api/team/{path}` and
the event stream at `/ws/team`. The frontend never receives the runtime token.
The descriptor path is configured with `SENZA_STUDIO_AGENT_TEAM_DESCRIPTOR`.
Browser origins are restricted to the local Studio origins by default and can
be overridden with `SENZA_STUDIO_ALLOWED_ORIGINS`.

## 3. Common response shape

Successful operation responses are endpoint-specific JSON objects. Mutating
operations commonly return:

```json
{ "ok": true }
```

Errors use:

```json
{ "ok": false, "error": "human-readable message" }
```

Status codes currently used by the runtime include `200`, `201`, `202`, `400`,
`401`, `403`, `404`, `409`, and `500`. Senza Studio must render the `error`
field and must not use status text alone as the user-facing message.

## 4. HTTP endpoints

All paths are relative to the runtime base URL. Proxied Senza Studio paths
should preserve the `/api/team/` prefix unless a later API version explicitly
introduces a new mount point.

### 4.1 Lifecycle and recovery

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/team/startup` | Return startup recovery status. |

Response:

```json
{
  "recovery": {
    "status": "healthy | degraded",
    "persisted_teams": 0,
    "restored_teams": 0,
    "failed_teams": [
      {
        "team_id": "example",
        "reason": "invalid_spec | workspace_unauthorized | workspace_check | team_create",
        "detail": "..."
      }
    ]
  }
}
```

### 4.2 Teams

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/team/projects` | List active teams. |
| `POST` | `/api/team/projects` | Create a team from a template or blank team. |
| `DELETE` | `/api/team/projects?id={id}` | Stop and unpersist a team. |
| `POST` | `/api/team/projects/restart?id={id}` | Stop and rebuild a persisted team. |

List response:

```json
{
  "projects": [
    { "id": "example", "repo_path": "/absolute/path" }
  ]
}
```

Create request:

```json
{
  "id": "example",
  "name": "Example team",
  "template_id": "coding-team",
  "repo_path": "/absolute/granted/path"
}
```

Only `id` is required. A workspace path must already be granted. Creation
returns `201`; accepted mutation conflicts and invalid requests use `409` and
`400` respectively.

### 4.3 Team chat and control

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/team/chat` | Submit operator text to one member. |
| `POST` | `/api/team/agent/inject?project={id}&agent={id}` | Steer a member's current or next turn. |
| `POST` | `/api/team/agent/abort?project={id}&agent={id}` | Abort a member's current run. |

Chat request:

```json
{
  "project": "example",
  "target": "planner",
  "text": "operator message"
}
```

Chat returns `202` after enqueueing the message. It does not wait for model
completion. Injection has the same body shape without `project` and `target`,
and returns `{ "ok": true }`.

### 4.4 Issues

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/team/issues?project={id}` | List issues for a team. |
| `POST` | `/api/team/issue/{id}/confirm` | Confirm an issue and trigger handoff. |
| `POST` | `/api/team/issue/{id}/reject` | Reject an issue. |

List response:

```json
{
  "issues": [
    {
      "id": "issue-id",
      "status": "pending | confirmed | rejected",
      "source": "...",
      "created": "...",
      "title": "..."
    }
  ]
}
```

Confirm can return `409` when the status transition is invalid or the declared
handoff fails. In that case the response may still describe a partial status
change and must be surfaced to the operator.

### 4.5 Runtime settings

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/team/settings` | Read global model and provider settings. |
| `POST` | `/api/team/settings` | Update global model and provider settings. |
| `POST` | `/api/team/apikey` | Replace the global API key. |

Settings response:

```json
{
  "models": {
    "strong": "model-id",
    "main": "model-id",
    "cheap": "model-id"
  },
  "scout_interval_secs": 900,
  "base_url": "https://provider.example",
  "api_key_set": true
}
```

The API key is never returned. `api_key_set` is the only key-state field.
Model changes apply to newly created or restarted teams; existing teams keep
their current harnesses until restarted.

### 4.6 Workspace grants and directory browsing

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/team/fs/grants` | List authorized workspace roots. |
| `POST` | `/api/team/fs/grants` | Grant a workspace root. |
| `DELETE` | `/api/team/fs/grants?id={id}` | Revoke an unused workspace root. |
| `GET` | `/api/team/fs?path={path}` | List directories inside a grant. |

Grant request:

```json
{ "path": "/absolute/path", "label": "Repository" }
```

Directory response:

```json
{
  "path": "/canonical/path",
  "is_repo": true,
  "dirs": [{ "name": "subdirectory" }],
  "grant_roots": ["/canonical/root"]
}
```

Browsing is read-only, exposes directories only, skips hidden entries, and
rejects paths outside granted roots or symlink escapes. Senza Studio must not
bypass this endpoint with native file APIs when the selected path is intended
for runtime execution.

### 4.7 Pulse and sessions

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/team/pulse?project={id}` | Return team/member status snapshot. |
| `GET` | `/api/team/agent/session?project={id}&agent={id}` | Return active session message history. |
| `GET` | `/api/team/agent/config?project={id}&agent={id}` | Return member config projection. |
| `PUT` | `/api/team/agent/config` | Update member config. |

Pulse includes `agents`, pending traffic, pending timers, and issue counts. The
exact agent fields are runtime observability data and may gain additive fields;
the frontend must ignore unknown fields.

Agent config response:

```json
{
  "model": "model-id",
  "system_prompt": "...",
  "tools": ["tool-name"],
  "thinking_level": "...",
  "temperature": 0.2,
  "override": {
    "model": null,
    "base_url": null,
    "api_key_set": false
  }
}
```

Member config update request:

```json
{
  "project": "example",
  "agent": "planner",
  "persona": "...",
  "toolkits": ["fs"],
  "model": "main",
  "base_url": "https://provider.example",
  "api_key": "secret"
}
```

All fields except `project` and `agent` are optional. The API key is write-only.
Persona and role label changes can hot-apply; model, provider, toolkit, or key
changes rebuild the member. The response includes:

```json
{ "ok": true, "rebuilt": true }
```

### 4.8 Templates and upgrades

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/team/templates` | List built-in and user templates. |
| `POST` | `/api/team/upgrade-check` | Determine which members can follow a template upgrade. |
| `POST` | `/api/team/upgrade-apply` | Apply a template upgrade to non-overridden members. |

Template response:

```json
{
  "templates": [
    {
      "id": "coding-team",
      "version": "1",
      "name": "Coding Team",
      "member_ids": ["planner"]
    }
  ]
}
```

Upgrade check/apply request:

```json
{ "project": "example" }
```

Upgrade decisions use the creation-time template baseline. Locally overridden
members are preserved.

## 5. Event WebSocket

Runtime endpoint:

```text
GET /api/team/events?token=<runtime-token>
```

The runtime token is accepted as a query parameter for WebSocket handshakes.
This is compatible with the current development panel. For Senza Studio, the
backend proxy should perform the authenticated upstream connection and expose
its own frontend WebSocket without forwarding the runtime token.

The protocol sends one JSON object per text frame and first replays recent
events before streaming live events. Unknown event types must be ignored.
Current event families include operator messages, issue changes, and agent
errors; producers may add new types or additive fields.

## 6. Compatibility policy

- This is a draft contract extracted from the current runtime implementation.
- Additive response fields are allowed.
- Removal or semantic changes require a runtime API version decision.
- Frontend code must not depend on Rust enum debug strings except where this
  contract explicitly lists them.
- Contract tests must run against a real runtime service, not only mocked
  handlers, before Senza Studio depends on this interface.

## 7. Required contract tests

Before the UI migration is considered production-ready, Senza Studio needs
tests for:

1. descriptor loading and runtime bearer-token forwarding;
2. unauthenticated upstream requests being rejected;
3. startup healthy and degraded recovery responses;
4. team list, create, restart, and delete;
5. workspace grant add/list/remove and unauthorized path denial;
6. directory browsing and symlink escape denial;
7. chat enqueue and member not-found errors;
8. pulse and session projections;
9. settings redaction and member API-key redaction;
10. event replay and live forwarding;
11. desktop launch, backend exit, and clean shutdown.
