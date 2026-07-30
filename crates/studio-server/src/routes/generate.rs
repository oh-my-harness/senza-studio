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
    let project = state
        .project_manager
        .open_project(&project_id)
        .map_err(|e| (StatusCode::NOT_FOUND, e.to_string()))?;
    let harness = studio_core::agents::build_coding_agent(
        &state.studio_api_key,
        &state.studio_model,
        state.studio_base_url.as_deref(),
        &project.dir,
        None,
    )
    .await
    .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    harness
        .prompt("Read the spec using read_spec(), then generate all project files. Write main.py (and tools.py, workflow.py, server.py as needed based on the spec). Run ast_check on each file after writing.")
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    let files = state
        .project_manager
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
    let project = state
        .project_manager
        .open_project(&project_id)
        .map_err(|e| (StatusCode::NOT_FOUND, e.to_string()))?;

    let spec = state
        .project_manager
        .load_current_spec(&project_id)
        .map_err(|e| (StatusCode::NOT_FOUND, e.to_string()))?;

    let affected_files = studio_core::agents::compute_affected_files(&req.diff, &spec);

    let harness = studio_core::agents::build_coding_agent(
        &state.studio_api_key,
        &state.studio_model,
        state.studio_base_url.as_deref(),
        &project.dir,
        Some(affected_files.clone()),
    )
    .await
    .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    let prompt = format!(
        "Read the spec using read_spec(). Apply the following incremental diff to the spec, then modify only these files: {:?}. The diff is: {}",
        affected_files,
        serde_json::to_string(&req.diff).unwrap_or_default()
    );
    harness
        .prompt(&prompt)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    Ok(Json(GenerateResponse {
        files: affected_files,
    }))
}
