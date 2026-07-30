# Senza Studio

A web application that helps developers customize AI agents via natural-language conversation, an example library, or direct code editing.

Built on [`llm-harness-runtime`](https://github.com/hhl/llm-harness-runtime) (Rust) and [Senza](https://github.com/hhl/Senza) (Python SDK). The output artifact is a runnable Senza Python project — not a config file.

## Prerequisites

- **Rust** (toolchain with edition 2024 support)
- **Node.js** ≥ 20 + npm
- **Python 3** (for running generated agent projects)
- **Senza SDK**: `pip install senza`

The `llm-harness-runtime` repo must exist as a sibling directory:

```
oh-my-harness/
├── llm-harness-runtime/   # Rust runtime crates
└── senza-studio/          # this repo
```

## Quick Start

### 1. Build the frontend

```bash
cd frontend
npm install
npm run build
cd ..
```

### 2. Build and run the server

```bash
cargo run --bin studio-server
```

Open `http://localhost:3000` in your browser.

### 3. Configure API keys

On first launch, click **Settings** in the top bar to configure:

- **Meta-Agent API Key** — LLM API key for the Converser and Coding Agent
- **Model** — e.g. `gpt-4o`
- **Base URL** — optional, for OpenAI-compatible providers
- **User Agent API Key / Base URL** — optional, for generated projects (falls back to meta-agent key)

Settings are persisted to `settings.json` (configurable via `SENZA_STUDIO_SETTINGS_PATH`).

Server-level environment variables (all optional):

| Variable | Default | Purpose |
|---|---|---|
| `SENZA_STUDIO_ADDR` | `0.0.0.0:3000` | Server listen address |
| `SENZA_STUDIO_PROJECTS_DIR` | `./projects` | Where project files are stored |
| `SENZA_STUDIO_SETTINGS_PATH` | `./settings.json` | Path to settings JSON file |
| `SENZA_STUDIO_FRONTEND_DIR` | `./frontend/dist` | Path to built frontend assets |

### Development mode (two terminals)

Terminal 1 — Rust server:

```bash
cargo run --bin studio-server
```

Terminal 2 — Vite dev server (hot reload):

```bash
cd frontend && npm run dev
```

Open `http://localhost:5173` (Vite proxies `/api` and `/ws` to the Rust server on :3000).

## Usage

1. **Configure** — Open Settings, enter your API key and model.
2. **Create a project** — Click "New" or pick an example from the library.
3. **Converse** — Describe the agent you want. The Converser meta-agent refines your description into a spec.
4. **Generate** — The Coding meta-agent writes Senza Python code from the spec.
5. **Run** — Run the generated agent in Studio mode (with live event streaming) or standalone mode (`python main.py`).
6. **Inspect** — View the DAG (for workflow agents), trace events, and edit code directly in the Code tab.

## Development

```bash
# Run all tests (deterministic, no LLM calls)
cargo test

# Run E2E HTTP tests
cargo test -p studio-server

# Typecheck frontend
cd frontend && npx tsc --noEmit

# Build frontend for production
cd frontend && npm run build
```

## Architecture

```
senza-studio/
├── crates/
│   ├── studio-core/          # Core library
│   │   ├── error.rs          # Error types
│   │   ├── spec.rs           # Spec data structures (agent, workflow, tools)
│   │   ├── project.rs        # Project file management
│   │   ├── frame.rs          # fd 3 frame protocol parser
│   │   ├── events.rs         # Event types + JSONL parser
│   │   ├── runner.rs         # Python subprocess runner
│   │   ├── agents/           # Meta-agents (run on Rust runtime)
│   │   │   ├── studio_tool.rs    # Tool trait helper
│   │   │   ├── diff_engine.rs    # Spec diff → affected files
│   │   │   ├── converser.rs      # Conversation → Spec
│   │   │   └── coding_agent.rs   # Spec → Python code
│   │   └── examples/         # 8 built-in example projects
│   └── studio-server/        # HTTP server
│       ├── routes/           # REST API (projects, examples, converse, generate, run, settings)
│       ├── ws/               # WebSocket handlers (converse, run)
│       ├── settings_store.rs # Persistent JSON settings (API keys, model, base URL)
│       └── state.rs          # AppState
├── frontend/                 # React + Vite + Tailwind
│   └── src/
│       ├── store/            # Zustand state
│       ├── hooks/            # WebSocket hooks
│       ├── lib/              # API client + WS client
│       └── components/       # 5 tabs + Settings page
└── docs/
    └── design.md             # Full design document (v5.3)
```

See `docs/design.md` for the full design document.
