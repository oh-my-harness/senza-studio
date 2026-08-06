use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::Json;
use axum::routing::post;
use axum::Router;
use serde::{Deserialize, Serialize};
use std::sync::Arc;

use studio_core::conversation::{load_conversation, ConversationMessage};

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
        .route("/api/projects/{id}/converse", post(converse))
        .route("/api/projects/{id}/conversation", axum::routing::get(get_conversation))
}

async fn get_conversation(
    State(state): State<Arc<AppState>>,
    Path(project_id): Path<String>,
) -> Result<Json<Vec<ConversationMessage>>, (StatusCode, String)> {
    let project = state
        .project_manager
        .open_project(&project_id)
        .map_err(|e| (StatusCode::NOT_FOUND, e.to_string()))?;
    let messages = load_conversation(&project.dir)
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    Ok(Json(messages))
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
