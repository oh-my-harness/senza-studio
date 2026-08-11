use axum::extract::State;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Json};
use axum::routing::get;
use axum::Router;
use serde_json::Value;
use std::sync::Arc;

use crate::state::AppState;

pub fn router() -> Router<Arc<AppState>> {
    Router::new()
        .route("/api/settings", get(get_settings).put(save_settings))
}

async fn get_settings(State(state): State<Arc<AppState>>) -> impl IntoResponse {
    let settings = state.settings_store.get();
    (
        StatusCode::OK,
        Json(serde_json::to_value(&settings).unwrap_or_default()),
    )
}

async fn save_settings(
    State(state): State<Arc<AppState>>,
    Json(settings): Json<Value>,
) -> impl IntoResponse {
    // Validate (and create, mirroring what main.rs already does for the
    // startup default) the working directory before persisting — a
    // persist-then-fail here would leave a broken setting saved, silently
    // breaking every subsequent project operation.
    if let Some(dir) = settings.get("working_directory").and_then(|v| v.as_str()) {
        let trimmed = dir.trim();
        if !trimmed.is_empty() {
            if let Err(e) = std::fs::create_dir_all(trimmed) {
                return (
                    StatusCode::BAD_REQUEST,
                    Json(serde_json::json!({
                        "error": format!("cannot use '{trimmed}' as working directory: {e}")
                    })),
                ).into_response();
            }
        }
    }

    match state.settings_store.update(settings) {
        Ok(updated) => (
            StatusCode::OK,
            Json(serde_json::to_value(&updated).unwrap_or_default()),
        ).into_response(),
        Err(e) => (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({ "error": e.to_string() })),
        ).into_response(),
    }
}
