# Senza Studio — Implementation Plans Overview

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement these plans task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Senza Studio — a web application that helps developers customize AI agents via natural-language conversation, an example library, or direct code editing, producing runnable Senza Python project scaffolds with run/trace/iterate capabilities.

**Architecture:** Rust backend (`llm-harness-runtime` based) hosts 2 meta-agents (Converser + Senza Coding Agent) as `AgentHarness` instances with `Tool` trait implementations. A React frontend communicates via REST + WebSocket. User agents run as Python subprocesses with fd 3 frame protocol for real-time event streaming.

**Tech Stack:** Rust (axum, tokio, serde), React (Vite, Tailwind, shadcn/ui, Zustand, React Flow), Python (Senza SDK), `llm-harness-runtime` crates.

## Design Document

The authoritative spec is `docs/design.md` (v5.3, ~1235 lines). All plans below reference section numbers from that document.

## Plan Split

This project spans 6 independent subsystems. Each plan produces working, testable software on its own:

| # | Plan File | Subsystem | Depends On |
|---|-----------|-----------|------------|
| 1 | `01-studio-core-foundation.md` | Cargo workspace, studio-core crate, spec/project/error types, examples library | None |
| 2 | `02-runner.md` | Python subprocess runner, fd 3 frame protocol, events.jsonl parsing | Plan 1 |
| 3 | `03-meta-agents.md` | Converser agent (4 tools) + Senza coding agent (5 tools) + StudioTool helper + diff rule engine | Plan 1 |
| 4 | `04-studio-server.md` | axum REST routes + WebSocket handlers + AppState + static file serving | Plans 1-3 |
| 5 | `05-frontend.md` | React app: 5 tabs, split run views (chat + execution), Zustand store, WebSocket client | Plan 4 |
| 6 | `06-examples-and-e2e.md` | Convert Senza examples to Studio example library + end-to-end integration tests | Plans 1-5 |

## Global Constraints

- **Language**: Rust edition 2024, workspace version 0.3.0 (matching `llm-harness-runtime`)
- **Crate dependency path**: `../../llm-harness-runtime/crates/<name>` (sibling repo, relative path)
- **No mocks**: All tests use real LLM calls; LLM tests tagged `#[ignore]`, run via `cargo test -- --ignored`
- **TDD**: Write failing test → verify fail → implement → verify pass → commit
- **No templates**: Coding agent writes Python code directly via LLM, not a template engine
- **Dual-mode run**: Generated `main.py` supports Studio mode (fd 3 + stdin) and standalone mode (`python main.py`)
- **Environment variables**: `STUDIO_API_KEY`, `STUDIO_MODEL`, `STUDIO_BASE_URL` (meta agents); `SENZA_STUDIO_RUN_ID`, `SENZA_STUDIO_TRACE_DIR` (user agent Studio mode)
- **Provider**: `base_url: null` in spec → generated code reads from env (`OPENAI_API_BASE` / `ANTHROPIC_API_BASE`)
- **Deploy modes**: `deploy: "cli" | "api"` — `api` additionally generates `server.py` (FastAPI + minimal chat page)
- **2 meta agents**: Converser (gpt-4o, 4 tools) + Senza coding agent (5 tools) = 9 tools total
- **Stop mechanism**: Kill subprocess (SIGTERM → SIGKILL); no steering/abort in MVP
- **Crash recovery**: NOT in MVP; examples library retains `crash_recovery/` for reference only
- **Terminology**: "示例库" (example library), NOT "模板库" (template library)

## Execution Order

```
Plan 1 (Foundation) ──→ Plan 2 (Runner) ──┐
                     ──→ Plan 3 (Agents) ──┤
                                          ├──→ Plan 4 (Server) ──→ Plan 5 (Frontend) ──→ Plan 6 (Examples + E2E)
```

Plans 1, 2, 3 can partially overlap (2 and 3 both depend on 1 but not each other). Plans 4-6 are strictly sequential.
