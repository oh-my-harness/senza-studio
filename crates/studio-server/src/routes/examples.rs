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
        .route("/api/examples/{id}", get(get_example))
        .route("/api/projects/from-example", post(create_from_example))
}

async fn list_examples() -> Json<Vec<ExampleResponse>> {
    let examples = studio_core::examples::list_examples();
    Json(
        examples
            .into_iter()
            .map(|e| ExampleResponse {
                id: e.id.into(),
                name: e.name.into(),
                description: e.description.into(),
                tags: e.tags.iter().map(|t| t.to_string()).collect(),
            })
            .collect(),
    )
}

async fn get_example(
    Path(id): Path<String>,
) -> Result<Json<serde_json::Value>, (StatusCode, String)> {
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
    let project = state
        .project_manager()
        .create_project(&req.project_name)
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    for (path, content) in &example.files {
        state
            .project_manager()
            .write_file(&project.id, path, content)
            .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    }
    Ok(Json(serde_json::json!({
        "project_id": project.id,
        "name": project.name,
        "files_copied": example.files.len(),
    })))
}
