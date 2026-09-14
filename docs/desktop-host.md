# Senza Studio desktop host

The Electron main process is the desktop host. It starts the Agent Team runtime,
starts the Python Studio backend, waits for both to become ready, and loads the
frontend.

## Runtime lifecycle

The host launches `agent-studio` with:

- `STUDIO_DATA_ROOT=<Electron user data>/agent-team`
- `STUDIO_PORT=0`

It accepts only the readiness line:

```text
STUDIO_PANEL_DESCRIPTOR=<data-root>/panel.json
```

Before the runtime is considered ready, the host verifies that the reported
path is exactly `<data-root>/panel.json`, that the descriptor is a regular file
of at most 64 KiB, and that its schema is
`llm-harness.studio.panel-descriptor.v1`. Electron does not inspect or log the
descriptor URL or runtime token.

If a ready runtime exits unexpectedly, the supervisor restarts it with capped
backoff. Five rapid failures stop further restarts. A runtime that stays ready
for at least 30 seconds resets the rapid-failure counter. Shutdown sends
`SIGTERM` to the Unix process group, waits up to 10 seconds, and then force
kills the group. Windows uses process termination followed by `taskkill /T /F`
after the grace period.

The runtime environment is scrubbed of Studio API tokens, descriptor paths, and
provider credentials. The runtime persists its own configuration under its data
root.

The Python backend and development Vite server use bounded shutdown: SIGTERM to
the Unix process group, a 10-second grace period, then process-tree force kill.
Windows uses `taskkill /T /F` after the grace period. Unexpected backend or Vite
exits request application shutdown instead of leaving the UI silently dead.

## Desktop diagnostics

The Electron host writes lifecycle and process events to:

```text
<Electron user data>/logs/desktop.jsonl
```

Each line uses schema `llm-harness.studio.desktop-lifecycle.v1` and contains an
event id, microsecond timestamp, Electron process id, application version,
event source (`host`, `agent-team`, `backend`, or `vite`), and normalized event
data. Text is redacted with the same rules as host output and capped at 16 KiB;
deep or large structures are truncated, and a serialized event larger than 64
KiB is replaced by a bounded truncation marker. The host fails startup if the
private diagnostics stream cannot be opened.

The log file rotates at 1 MiB and retains ten rotated files. Unix directories
and files are created with 0700/0600 permissions; the logs directory must be a
real directory and the active log file cannot be a symlink. Diagnostics are
flushed and closed after all child processes stop during application shutdown.

## Backend and frontend

Development mode uses the repository Python environment, Vite, and the debug
runtime binary. Packaged mode expects these resources outside the Electron
asar archive:

- `resources/agent-studio[.exe]`
- `resources/senza-studio-backend/`
- `resources/python/`
- `resources/studio_frontend/dist/`

The backend receives `SENZA_STUDIO_AGENT_TEAM_DESCRIPTOR` and
`SENZA_STUDIO_STATIC_DIR`. Static serving accepts only regular files under the
configured root, rejects traversal and symlinked files, serves `index.html`
only at `/`, and gives Vite content-hashed assets immutable cache headers.

The overrides `SENZA_STUDIO_AGENT_TEAM_BIN` and `SENZA_STUDIO_PYTHON` are
intended for development and staged packaging tests; packaged builds should use
the resource layout above.

## Current packaging boundary

The host lifecycle and resource contracts are implemented, but installer
production work remains: an Electron packaging recipe, bundled Python runtime,
platform binaries, code signing/notarization, and packaged end-to-end tests.
These are required before calling the desktop distribution production-ready.
