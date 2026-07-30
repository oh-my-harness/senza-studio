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
    Router::new().route("/api/projects/{id}/converse", post(converse))
}

async fn converse(
    State(state): State<Arc<AppState>>,
    Path(project_id): Path<String>,
    Json(_req): Json<ConverseRequest>,
) -> Result<Json<ConverseResponse>, (StatusCode, String)> {
    let _project = state
        .project_manager
        .open_project(&project_id)
        .map_err(|e| (StatusCode::NOT_FOUND, e.to_string()))?;
    let run_id = uuid::Uuid::now_v7().to_string();
    Ok(Json(ConverseResponse {
        run_id,
        ws_url: format!("/ws/converse/{project_id}"),
    }))
}
