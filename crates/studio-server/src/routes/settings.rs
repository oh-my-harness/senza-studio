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
