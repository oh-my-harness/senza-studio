use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::Json;
use axum::routing::{get, post};
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
        .route("/api/projects/{id}", get(get_project))
        .route("/api/projects/{id}/files", get(list_files))
        .route("/api/projects/{id}/files/{*path}", get(get_file).put(put_file))
}

async fn create_project(
    State(state): State<Arc<AppState>>,
    Json(req): Json<CreateProjectRequest>,
) -> Result<Json<ProjectResponse>, (StatusCode, String)> {
    let project = state
        .project_manager
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
    let projects = state
        .project_manager
        .list_projects()
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    Ok(Json(
        projects
            .into_iter()
            .map(|p| ProjectResponse {
                id: p.id,
                name: p.name,
                dir: p.dir.to_string_lossy().into_owned(),
                created_at: p.created_at.to_rfc3339(),
            })
            .collect(),
    ))
}

async fn get_project(
    State(state): State<Arc<AppState>>,
    Path(id): Path<String>,
) -> Result<Json<ProjectResponse>, (StatusCode, String)> {
    let project = state
        .project_manager
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
    let files = state
        .project_manager
        .list_files(&id)
        .map_err(|e| (StatusCode::NOT_FOUND, e.to_string()))?;
    Ok(Json(files))
}

async fn get_file(
    State(state): State<Arc<AppState>>,
    Path((id, path)): Path<(String, String)>,
) -> Result<String, (StatusCode, String)> {
    state
        .project_manager
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
    state
        .project_manager
        .write_file(&id, &path, &req.content)
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    Ok(StatusCode::OK)
}
