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
    pub mode: String,
}

#[derive(Serialize)]
pub struct RunResponse {
    pub run_id: String,
    pub ws_url: String,
}

pub fn router() -> Router<Arc<AppState>> {
    Router::new()
        .route("/api/projects/{id}/run", post(run_project))
        .route("/api/projects/{id}/runs", get(list_runs))
        .route("/api/projects/{id}/runs/{run_id}/events", get(get_run_events))
        .route("/api/projects/{id}/runs/{run_id}/stop", post(stop_run))
}

async fn run_project(
    State(state): State<Arc<AppState>>,
    Path(project_id): Path<String>,
    Json(_req): Json<RunRequest>,
) -> Result<Json<RunResponse>, (StatusCode, String)> {
    let project = state
        .project_manager
        .open_project(&project_id)
        .map_err(|e| (StatusCode::NOT_FOUND, e.to_string()))?;

    let main_script = project.dir.join("main.py");
    if !main_script.exists() {
        return Err((
            StatusCode::BAD_REQUEST,
            "main.py not found. Generate code first.".into(),
        ));
    }

    let run_id = uuid::Uuid::now_v7().to_string();
    let config = RunConfig {
        project_dir: project.dir.clone(),
        main_script,
        run_id: run_id.clone(),
        timeout_secs: 300,
        env_vars: state.user_env_vars.clone(),
    };

    state
        .runner
        .start(config)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    Ok(Json(RunResponse {
        run_id,
        ws_url: format!("/ws/run/{project_id}"),
    }))
}

async fn list_runs(
    State(state): State<Arc<AppState>>,
    Path(project_id): Path<String>,
) -> Result<Json<Vec<String>>, (StatusCode, String)> {
    let project = state
        .project_manager
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
    let project = state
        .project_manager
        .open_project(&project_id)
        .map_err(|e| (StatusCode::NOT_FOUND, e.to_string()))?;
    let events = state
        .runner
        .read_events(&project.dir, &run_id)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    Ok(Json(events))
}

async fn stop_run(
    State(state): State<Arc<AppState>>,
    Path((_project_id, run_id)): Path<(String, String)>,
) -> Result<StatusCode, (StatusCode, String)> {
    state
        .runner
        .stop(&run_id)
        .await
        .map_err(|e| (StatusCode::NOT_FOUND, e.to_string()))?;
    Ok(StatusCode::OK)
}
