# Plan 4: Studio Server

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the axum web server with REST routes, WebSocket handlers, AppState, and static file serving.

**Architecture:** `studio-server` crate depends on `studio-core`. REST routes handle project CRUD, file operations, conversation, generation, and run management. Two WebSocket endpoints handle real-time streaming: `/ws/converse/:projectId` (meta-agent streaming) and `/ws/run/:projectId` (user agent run events + stdin input). AppState holds `ProjectManager`, `Runner`, and meta-agent config.

**Tech Stack:** Rust 2024, axum, tokio, tower-http, serde_json.

## Global Constraints

(See `00-overview.md`)

---

## File Structure

```
crates/studio-server/
├── Cargo.toml
├── src/
│   ├── lib.rs            # Server builder + AppState
│   ├── state.rs          # AppState struct
│   ├── routes/
│   │   ├── mod.rs
│   │   ├── projects.rs   # Project CRUD + file operations
│   │   ├── converse.rs   # POST /converse → triggers Converser
│   │   ├── generate.rs   # POST /generate + /generate-diff
│   │   ├── run.rs        # POST /run, GET /runs, GET /runs/:id/events
│   │   └── examples.rs   # GET /examples, POST /from-example
│   └── ws/
│       ├── mod.rs
│       ├── converse.rs   # WS /ws/converse/:projectId
│       └── run.rs        # WS /ws/run/:projectId
```

---

### Task 1: Scaffold studio-server Crate

**Files:**
- Create: `crates/studio-server/Cargo.toml`
- Create: `crates/studio-server/src/lib.rs`
- Create: `crates/studio-server/src/state.rs`
- Modify: `Cargo.toml` (workspace root — add member)

**Interfaces:**
- Produces: `studio-server` crate with `AppState`, `build_app()`, `run_server()`

- [ ] **Step 1: Add workspace member**

Modify workspace `Cargo.toml`:
```toml
[workspace]
members = [
    "crates/studio-core",
    "crates/studio-server",
]
```

Add to `[workspace.dependencies]`:
```toml
axum        = { version = "0.8", features = ["ws"] }
tower-http  = { version = "0.6", features = ["fs", "cors"] }
```

- [ ] **Step 2: Create Cargo.toml**

```toml
[package]
name = "studio-server"
edition.workspace = true
version.workspace = true
license.workspace = true

[dependencies]
studio-core = { path = "../studio-core" }
llm-harness-types  = { workspace = true }
llm-harness-agent  = { workspace = true }
llm-harness-loop   = { workspace = true }
llm-harness-runtime = { workspace = true }
llm-harness-runtime-sandbox-os = { workspace = true }
axum        = { workspace = true }
tower-http  = { workspace = true }
tokio       = { workspace = true }
serde       = { workspace = true }
serde_json  = { workspace = true }
futures     = { workspace = true }
uuid        = { workspace = true }
chrono      = { workspace = true }
tracing     = { workspace = true }
anyhow      = { workspace = true }

[dev-dependencies]
tempfile = { workspace = true }
```

- [ ] **Step 3: Create state.rs**

```rust
use std::path::PathBuf;
use std::sync::Arc;
use studio_core::project::ProjectManager;
use studio_core::runner::Runner;

pub struct AppState {
    pub project_manager: ProjectManager,
    pub runner: Arc<Runner>,
    pub studio_api_key: String,
    pub studio_model: String,
    pub studio_base_url: Option<String>,
}

impl AppState {
    pub fn new(
        projects_root: PathBuf,
        api_key: String,
        model: String,
        base_url: Option<String>,
    ) -> Self {
        Self {
            project_manager: ProjectManager::new(projects_root),
            runner: Arc::new(Runner::new()),
            studio_api_key: api_key,
            studio_model: model,
            studio_base_url: base_url,
        }
    }
}
```

- [ ] **Step 4: Create lib.rs**

```rust
pub mod state;
pub mod routes;
pub mod ws;

use std::sync::Arc;
use axum::Router;
use state::AppState;

pub fn build_app(state: Arc<AppState>) -> Router {
    Router::new()
        .merge(routes::projects::router())
        .merge(routes::converse::router())
        .merge(routes::generate::router())
        .merge(routes::run::router())
        .merge(routes::examples::router())
        .merge(ws::converse::router())
        .merge(ws::run::router())
        .with_state(state)
}

pub async fn run_server(state: Arc<AppState>, addr: &str) -> anyhow::Result<()> {
    let app = build_app(state);
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}
```

- [ ] **Step 5: Create route module stubs**

Create `routes/mod.rs`, `routes/projects.rs`, `routes/converse.rs`, `routes/generate.rs`, `routes/run.rs`, `routes/examples.rs`, `ws/mod.rs`, `ws/converse.rs`, `ws/run.rs` — each with a minimal `pub fn router() -> Router<Arc<AppState>>` that returns an empty router.

- [ ] **Step 6: Verify compilation**

Run: `cargo check`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: scaffold studio-server crate with AppState"
```

---

### Task 2: Project REST Routes (routes/projects.rs)

**Files:**
- Create: `crates/studio-server/src/routes/projects.rs`
- Test: inline

**Design doc reference:** §5 REST API table

- [ ] **Step 1: Write the failing tests**

```rust
#[cfg(test)]
mod tests {
    // Tests use axum's TestServer or direct handler calls.
    // POST /api/projects → create project
    // GET /api/projects → list projects
    // GET /api/projects/:id → get project meta
    // GET /api/projects/:id/files → list files
    // GET /api/projects/:id/files/:path → read file
    // PUT /api/projects/:id/files/:path → write file
}
```

- [ ] **Step 2: Implement routes**

```rust
use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::Json;
use axum::routing::{get, post, put};
use axum::Router;
use serde::{Deserialize, Serialize};
use std::sync::Arc;

use crate::state::AppState;

#[derive(Deserialize)]
pub struct CreateProjectRequest {
    pub name: String,
}

#[derive(Serialize)]
pub struct ProjectResponse {
    pub id: String,
    pub name: String,
    pub dir: String,
    pub created_at: String,
}

pub fn router() -> Router<Arc<AppState>> {
    Router::new()
        .route("/api/projects", post(create_project).get(list_projects))
        .route("/api/projects/:id", get(get_project))
        .route("/api/projects/:id/files", get(list_files))
        .route("/api/projects/:id/files/*path", get(get_file).put(put_file))
}

async fn create_project(
    State(state): State<Arc<AppState>>,
    Json(req): Json<CreateProjectRequest>,
) -> Result<Json<ProjectResponse>, (StatusCode, String)> {
    let project = state.project_manager
        .create_project(&req.name)
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    Ok(Json(ProjectResponse {
        id: project.id,
        name: project.name,
        dir: project.dir.to_string_lossy().into_owned(),
        created_at: project.created_at.to_rfc3339(),
    }))
}

async fn list_projects(
    State(state): State<Arc<AppState>>,
) -> Result<Json<Vec<ProjectResponse>>, (StatusCode, String)> {
    let projects = state.project_manager
        .list_projects()
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    Ok(Json(projects.into_iter().map(|p| ProjectResponse {
        id: p.id,
        name: p.name,
        dir: p.dir.to_string_lossy().into_owned(),
        created_at: p.created_at.to_rfc3339(),
    }).collect()))
}

async fn get_project(
    State(state): State<Arc<AppState>>,
    Path(id): Path<String>,
) -> Result<Json<ProjectResponse>, (StatusCode, String)> {
    let project = state.project_manager
        .open_project(&id)
        .map_err(|e| (StatusCode::NOT_FOUND, e.to_string()))?;
    Ok(Json(ProjectResponse {
        id: project.id,
        name: project.name,
        dir: project.dir.to_string_lossy().into_owned(),
        created_at: project.created_at.to_rfc3339(),
    }))
}

async fn list_files(
    State(state): State<Arc<AppState>>,
    Path(id): Path<String>,
) -> Result<Json<Vec<String>>, (StatusCode, String)> {
    let files = state.project_manager
        .list_files(&id)
        .map_err(|e| (StatusCode::NOT_FOUND, e.to_string()))?;
    Ok(Json(files))
}

async fn get_file(
    State(state): State<Arc<AppState>>,
    Path((id, path)): Path<(String, String)>,
) -> Result<String, (StatusCode, String)> {
    state.project_manager
        .read_file(&id, &path)
        .map_err(|e| (StatusCode::NOT_FOUND, e.to_string()))
}

#[derive(Deserialize)]
pub struct WriteFileRequest {
    pub content: String,
}

async fn put_file(
    State(state): State<Arc<AppState>>,
    Path((id, path)): Path<(String, String)>,
    Json(req): Json<WriteFileRequest>,
) -> Result<StatusCode, (StatusCode, String)> {
    state.project_manager
        .write_file(&id, &path, &req.content)
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    Ok(StatusCode::OK)
}
```

- [ ] **Step 3: Run tests, verify pass, commit**

```bash
cargo test --lib projects
git add -A && git commit -m "feat: add project REST routes"
```

---

### Task 3: Examples REST Routes (routes/examples.rs)

**Files:**
- Create: `crates/studio-server/src/routes/examples.rs`

**Design doc reference:** §5 示例库入口

- [ ] **Step 1: Implement routes**

```rust
use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::Json;
use axum::routing::{get, post};
use axum::Router;
use serde::{Deserialize, Serialize};
use std::sync::Arc;

use crate::state::AppState;

#[derive(Serialize)]
pub struct ExampleResponse {
    pub id: String,
    pub name: String,
    pub description: String,
    pub tags: Vec<String>,
}

pub fn router() -> Router<Arc<AppState>> {
    Router::new()
        .route("/api/examples", get(list_examples))
        .route("/api/examples/:id", get(get_example))
        .route("/api/projects/from-example", post(create_from_example))
}

async fn list_examples() -> Json<Vec<ExampleResponse>> {
    let examples = studio_core::examples::list_examples();
    Json(examples.into_iter().map(|e| ExampleResponse {
        id: e.id.into(),
        name: e.name.into(),
        description: e.description.into(),
        tags: e.tags.iter().map(|t| t.to_string()).collect(),
    }).collect())
}

async fn get_example(Path(id): Path<String>) -> Result<Json<serde_json::Value>, (StatusCode, String)> {
    let example = studio_core::examples::get_example(&id)
        .ok_or((StatusCode::NOT_FOUND, "example not found".into()))?;
    Ok(Json(serde_json::json!({
        "id": example.id,
        "name": example.name,
        "description": example.description,
        "tags": example.tags,
        "files": example.files.iter().map(|(p, c)| {
            serde_json::json!({"path": p, "content": c})
        }).collect::<Vec<_>>(),
    })))
}

#[derive(Deserialize)]
pub struct CreateFromExampleRequest {
    pub example_id: String,
    pub project_name: String,
}

async fn create_from_example(
    State(state): State<Arc<AppState>>,
    Json(req): Json<CreateFromExampleRequest>,
) -> Result<Json<serde_json::Value>, (StatusCode, String)> {
    let example = studio_core::examples::get_example(&req.example_id)
        .ok_or((StatusCode::NOT_FOUND, "example not found".into()))?;
    let project = state.project_manager
        .create_project(&req.project_name)
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    // Copy all example files into the project
    for (path, content) in &example.files {
        state.project_manager
            .write_file(&project.id, path, content)
            .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    }
    Ok(Json(serde_json::json!({
        "project_id": project.id,
        "name": project.name,
        "files_copied": example.files.len(),
    })))
}
```

- [ ] **Step 2: Commit**

```bash
git add -A && git commit -m "feat: add examples REST routes"
```

---

### Task 4: Converse REST Route (routes/converse.rs)

**Files:**
- Create: `crates/studio-server/src/routes/converse.rs`

**Design doc reference:** §5 POST /converse

- [ ] **Step 1: Implement route**

```rust
use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::Json;
use axum::routing::post;
use axum::Router;
use serde::{Deserialize, Serialize};
use std::sync::Arc;

use crate::state::AppState;

#[derive(Deserialize)]
pub struct ConverseRequest {
    pub message: String,
}

#[derive(Serialize)]
pub struct ConverseResponse {
    pub run_id: String,
    pub ws_url: String,
}

pub fn router() -> Router<Arc<AppState>> {
    Router::new()
        .route("/api/projects/:id/converse", post(converse))
}

async fn converse(
    State(state): State<Arc<AppState>>,
    Path(project_id): Path<String>,
    Json(req): Json<ConverseRequest>,
) -> Result<Json<ConverseResponse>, (StatusCode, String)> {
    let project = state.project_manager
        .open_project(&project_id)
        .map_err(|e| (StatusCode::NOT_FOUND, e.to_string()))?;
    let run_id = uuid::Uuid::now_v7().to_string();
    Ok(Json(ConverseResponse {
        run_id: run_id.clone(),
        ws_url: format!("/ws/converse/{project_id}"),
    }))
}
```

Note: The actual converser agent interaction happens via WebSocket (Plan 4 Task 6). The REST endpoint just initiates the session.

- [ ] **Step 2: Commit**

```bash
git add -A && git commit -m "feat: add converse REST route"
```

---

### Task 5: Generate REST Routes (routes/generate.rs)

**Files:**
- Create: `crates/studio-server/src/routes/generate.rs`

**Design doc reference:** §5 POST /generate, POST /generate-diff

- [ ] **Step 1: Implement routes**

```rust
use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::Json;
use axum::routing::post;
use axum::Router;
use serde::{Deserialize, Serialize};
use std::sync::Arc;

use crate::state::AppState;

#[derive(Serialize)]
pub struct GenerateResponse {
    pub files: Vec<String>,
}

pub fn router() -> Router<Arc<AppState>> {
    Router::new()
        .route("/api/projects/:id/generate", post(generate))
        .route("/api/projects/:id/generate-diff", post(generate_diff))
}

async fn generate(
    State(state): State<Arc<AppState>>,
    Path(project_id): Path<String>,
) -> Result<Json<GenerateResponse>, (StatusCode, String)> {
    let project = state.project_manager
        .open_project(&project_id)
        .map_err(|e| (StatusCode::NOT_FOUND, e.to_string()))?;
    // Build and run the coding agent
    let harness = studio_core::agents::build_coding_agent(
        &state.studio_api_key,
        &state.studio_model,
        state.studio_base_url.as_deref(),
        &project.dir,
        None, // no file restrictions for full generation
    )
    .await
    .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    harness
        .prompt("Read the spec using read_spec(), then generate all project files. Write main.py (and tools.py, workflow.py, server.py as needed based on the spec). Run ast_check on each file after writing.")
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    let files = state.project_manager
        .list_files(&project_id)
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    Ok(Json(GenerateResponse { files }))
}

#[derive(Deserialize)]
pub struct GenerateDiffRequest {
    pub diff: studio_core::spec::SpecDiff,
}

async fn generate_diff(
    State(state): State<Arc<AppState>>,
    Path(project_id): Path<String>,
    Json(req): Json<GenerateDiffRequest>,
) -> Result<Json<GenerateResponse>, (StatusCode, String)> {
    let project = state.project_manager
        .open_project(&project_id)
        .map_err(|e| (StatusCode::NOT_FOUND, e.to_string()))?;

    let spec = state.project_manager
        .load_current_spec(&project_id)
        .map_err(|e| (StatusCode::NOT_FOUND, e.to_string()))?;

    let affected_files = studio_core::agents::compute_affected_files(&req.diff, &spec);

    let harness = studio_core::agents::build_coding_agent(
        &state.studio_api_key,
        &state.studio_model,
        state.studio_base_url.as_deref(),
        &project.dir,
        Some(affected_files.clone()), // restrict to affected files
    )
    .await
    .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    let prompt = format!(
        "Read the spec using read_spec(). Apply the following incremental diff to the spec, then modify only these files: {:?}. \
        The diff is: {}",
        affected_files,
        serde_json::to_string(&req.diff).unwrap_or_default()
    );
    harness
        .prompt(&prompt)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    Ok(Json(GenerateResponse { files: affected_files }))
}
```

- [ ] **Step 2: Commit**

```bash
git add -A && git commit -m "feat: add generate and generate-diff REST routes"
```

---

### Task 6: Run REST Routes (routes/run.rs)

**Files:**
- Create: `crates/studio-server/src/routes/run.rs`

**Design doc reference:** §5 POST /run, GET /runs, GET /runs/:id/events

- [ ] **Step 1: Implement routes**

```rust
use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::Json;
use axum::routing::{get, post};
use axum::Router;
use serde::{Deserialize, Serialize};
use std::sync::Arc;

use crate::state::AppState;
use studio_core::runner::RunConfig;

#[derive(Deserialize)]
pub struct RunRequest {
    pub mode: String, // "studio" | "standalone"
}

#[derive(Serialize)]
pub struct RunResponse {
    pub run_id: String,
    pub ws_url: String,
}

pub fn router() -> Router<Arc<AppState>> {
    Router::new()
        .route("/api/projects/:id/run", post(run_project))
        .route("/api/projects/:id/runs", get(list_runs))
        .route("/api/projects/:id/runs/:run_id/events", get(get_run_events))
        .route("/api/projects/:id/runs/:run_id/stop", post(stop_run))
}

async fn run_project(
    State(state): State<Arc<AppState>>,
    Path(project_id): Path<String>,
    Json(req): Json<RunRequest>,
) -> Result<Json<RunResponse>, (StatusCode, String)> {
    let project = state.project_manager
        .open_project(&project_id)
        .map_err(|e| (StatusCode::NOT_FOUND, e.to_string()))?;

    let main_script = project.dir.join("main.py");
    if !main_script.exists() {
        return Err((StatusCode::BAD_REQUEST, "main.py not found. Generate code first.".into()));
    }

    let run_id = uuid::Uuid::now_v7().to_string();
    let config = RunConfig {
        project_dir: project.dir.clone(),
        main_script,
        run_id: run_id.clone(),
        timeout_secs: 300,
    };

    state.runner
        .start(config)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    Ok(Json(RunResponse {
        run_id: run_id.clone(),
        ws_url: format!("/ws/run/{project_id}"),
    }))
}

async fn list_runs(
    State(state): State<Arc<AppState>>,
    Path(project_id): Path<String>,
) -> Result<Json<Vec<String>>, (StatusCode, String)> {
    let project = state.project_manager
        .open_project(&project_id)
        .map_err(|e| (StatusCode::NOT_FOUND, e.to_string()))?;
    let runs = studio_core::runner::Runner::list_runs(&project.dir)
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    Ok(Json(runs))
}

async fn get_run_events(
    State(state): State<Arc<AppState>>,
    Path((project_id, run_id)): Path<(String, String)>,
) -> Result<Json<Vec<serde_json::Value>>, (StatusCode, String)> {
    let project = state.project_manager
        .open_project(&project_id)
        .map_err(|e| (StatusCode::NOT_FOUND, e.to_string()))?;
    let events = state.runner
        .read_events(&project.dir, &run_id)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    Ok(Json(events))
}

async fn stop_run(
    State(state): State<Arc<AppState>>,
    Path((project_id, run_id)): Path<(String, String)>,
) -> Result<StatusCode, (StatusCode, String)> {
    state.runner
        .stop(&run_id)
        .await
        .map_err(|e| (StatusCode::NOT_FOUND, e.to_string()))?;
    Ok(StatusCode::OK)
}
```

- [ ] **Step 2: Commit**

```bash
git add -A && git commit -m "feat: add run REST routes"
```

---

### Task 7: WebSocket Handlers (ws/converse.rs, ws/run.rs)

**Files:**
- Create: `crates/studio-server/src/ws/converse.rs`
- Create: `crates/studio-server/src/ws/run.rs`

**Design doc reference:** §5 WebSocket table

- [ ] **Step 1: Implement ws/converse.rs**

```rust
use axum::extract::{Path, State, WebSocketUpgrade, WebSocket};
use axum::response::IntoResponse;
use axum::routing::get;
use axum::Router;
use std::sync::Arc;

use crate::state::AppState;

pub fn router() -> Router<Arc<AppState>> {
    Router::new()
        .route("/ws/converse/:project_id", get(ws_converse_handler))
}

async fn ws_converse_handler(
    ws: WebSocketUpgrade,
    State(state): State<Arc<AppState>>,
    Path(project_id): Path<String>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_converse_ws(socket, state, project_id))
}

async fn handle_converse_ws(mut socket: WebSocket, state: Arc<AppState>, project_id: String) {
    let project = match state.project_manager.open_project(&project_id) {
        Ok(p) => p,
        Err(e) => {
            let _ = socket.send(axum::extract::ws::Message::Text(
                serde_json::json!({"type": "error", "message": e.to_string()}).to_string().into()
            )).await;
            return;
        }
    };

    let harness = match studio_core::agents::build_converser(
        &state.studio_api_key,
        &state.studio_model,
        state.studio_base_url.as_deref(),
        &project.dir,
    ).await {
        Ok(h) => h,
        Err(e) => {
            let _ = socket.send(axum::extract::ws::Message::Text(
                serde_json::json!({"type": "error", "message": e.to_string()}).to_string().into()
            )).await;
            return;
        }
    };

    // Subscribe to harness events
    let mut rx = harness.subscribe();

    loop {
        tokio::select! {
            // Receive user message from WebSocket
            msg = socket.recv() => {
                match msg {
                    Some(Ok(axum::extract::ws::Message::Text(text))) => {
                        let text_str = text.to_string();
                        // Send to converser agent
                        if let Err(e) = harness.prompt(&text_str).await {
                            let _ = socket.send(axum::extract::ws::Message::Text(
                                serde_json::json!({"type": "error", "message": e.to_string()}).to_string().into()
                            )).await;
                        }
                    }
                    _ => break,
                }
            }
            // Receive events from harness
            event = rx.recv() => {
                match event {
                    Ok(ev) => {
                        let event_json = serde_json::to_string(&format_harness_event(&ev)).unwrap_or_default();
                        if socket.send(axum::extract::ws::Message::Text(event_json.into())).await.is_err() {
                            break;
                        }
                    }
                    Err(_) => break,
                }
            }
        }
    }
}

fn format_harness_event(ev: &llm_harness_agent::AgentHarnessEvent) -> serde_json::Value {
    use llm_harness_agent::AgentHarnessEvent;
    match ev {
        AgentHarnessEvent::Agent(agent_ev) => {
            // Serialize the inner AgentEvent
            serde_json::to_value(agent_ev).unwrap_or(serde_json::json!({"type": "unknown"}))
        }
        AgentHarnessEvent::Settled => serde_json::json!({"type": "settled"}),
        AgentHarnessEvent::Aborted => serde_json::json!({"type": "aborted"}),
        AgentHarnessEvent::ToolCallStart { tool_use_id, tool_name, args } => serde_json::json!({
            "type": "tool_call_start",
            "tool_use_id": tool_use_id,
            "tool_name": tool_name,
            "args": args,
        }),
        AgentHarnessEvent::ToolCallEnd { tool_use_id, tool_name, result } => serde_json::json!({
            "type": "tool_execution_end",
            "tool_use_id": tool_use_id,
            "tool_name": tool_name,
            "result": {"details": result.details, "is_error": result.is_error},
        }),
        _ => serde_json::json!({"type": "harness_event"}),
    }
}
```

- [ ] **Step 2: Implement ws/run.rs**

```rust
use axum::extract::{Path, State, WebSocketUpgrade, WebSocket};
use axum::response::IntoResponse;
use axum::routing::get;
use axum::Router;
use std::sync::Arc;

use crate::state::AppState;

pub fn router() -> Router<Arc<AppState>> {
    Router::new()
        .route("/ws/run/:project_id", get(ws_run_handler))
}

async fn ws_run_handler(
    ws: WebSocketUpgrade,
    State(state): State<Arc<AppState>>,
    Path(project_id): Path<String>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_run_ws(socket, state, project_id))
}

async fn handle_run_ws(mut socket: WebSocket, state: Arc<AppState>, project_id: String) {
    // Poll for events from the runner and push to WebSocket
    // Receive user input from WebSocket and send to runner stdin
    loop {
        tokio::select! {
            msg = socket.recv() => {
                match msg {
                    Some(Ok(axum::extract::ws::Message::Text(text))) => {
                        // User input → runner stdin
                        // The text is the user message; find the active run
                        // For simplicity, we use a "run_id" field in the message
                        if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&text) {
                            if let (Some(run_id), Some(input)) = (
                                parsed.get("run_id").and_then(|v| v.as_str()),
                                parsed.get("input").and_then(|v| v.as_str())
                            ) {
                                let _ = state.runner.send_input(run_id, input).await;
                            }
                        } else {
                            // Plain text — try to find any running run for this project
                            // For MVP, the run_id is sent in the initial POST /run response
                        }
                    }
                    _ => break,
                }
            }
            _ = tokio::time::sleep(std::time::Duration::from_millis(100)) => {
                // Poll for new events from active runs
                // This is simplified; a production version would use broadcast channels
            }
        }
    }
}
```

Note: The run WebSocket handler is simplified for MVP. A production version would use `tokio::sync::broadcast` channels between the Runner and the WebSocket handler. The Runner should be enhanced to broadcast events as they arrive from fd 3, and the WebSocket handler subscribes to this broadcast.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat: add WebSocket handlers for converse and run"
```

---

### Task 8: Server Binary + Static File Serving

**Files:**
- Create: `crates/studio-server/src/main.rs` (or a separate `studio-server-bin` crate)
- Modify: `lib.rs` to add static file serving

- [ ] **Step 1: Create main.rs**

```rust
use std::sync::Arc;
use studio_server::state::AppState;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt::init();

    let projects_root = std::env::var("SENZA_STUDIO_PROJECTS_DIR")
        .unwrap_or_else(|_| "./projects".into());
    let api_key = std::env::var("STUDIO_API_KEY")
        .expect("STUDIO_API_KEY required");
    let model = std::env::var("STUDIO_MODEL")
        .unwrap_or_else(|_| "gpt-4o".into());
    let base_url = std::env::var("STUDIO_BASE_URL").ok();
    let addr = std::env::var("SENZA_STUDIO_ADDR")
        .unwrap_or_else(|_| "0.0.0.0:3000".into());

    std::fs::create_dir_all(&projects_root)?;

    let state = Arc::new(AppState::new(
        projects_root.into(),
        api_key,
        model,
        base_url,
    ));

    eprintln!("Senza Studio server listening on {addr}");
    studio_server::run_server(state, &addr).await
}
```

- [ ] **Step 2: Add binary to Cargo.toml**

```toml
[[bin]]
name = "studio-server"
path = "src/main.rs"
```

Add `tracing-subscriber = { version = "0.3", features = ["fmt"] }` to dependencies.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat: add server binary entry point"
```

---

### Task 9: Integration Tests

**Files:**
- Create: `crates/studio-server/tests/api_test.rs`

- [ ] **Step 1: Write integration tests**

```rust
use studio_core::project::ProjectManager;
use studio_server::state::AppState;
use std::sync::Arc;

// These tests don't require LLM — they test the REST API surface
// for deterministic operations (project CRUD, file ops, examples).

#[tokio::test]
async fn test_create_and_get_project() {
    // Test: POST /api/projects → GET /api/projects/:id
    // Use axum's TestServer or manual router invocation
}

#[tokio::test]
async fn test_list_examples() {
    // Test: GET /api/examples returns 8 examples
}

#[tokio::test]
async fn test_create_from_example() {
    // Test: POST /api/projects/from-example → verify files exist
}
```

- [ ] **Step 2: Commit**

```bash
git add -A && git commit -m "test: add studio-server integration tests"
```
