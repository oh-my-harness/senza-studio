use axum::extract::ws::{WebSocket, WebSocketUpgrade};
use axum::extract::{Path, State};
use axum::response::IntoResponse;
use axum::routing::get;
use axum::Router;
use std::sync::Arc;

use crate::state::AppState;

pub fn router() -> Router<Arc<AppState>> {
    Router::new().route("/ws/run/:project_id", get(ws_run_handler))
}

async fn ws_run_handler(
    ws: WebSocketUpgrade,
    State(state): State<Arc<AppState>>,
    Path(project_id): Path<String>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_run_ws(socket, state, project_id))
}

async fn handle_run_ws(mut socket: WebSocket, state: Arc<AppState>, _project_id: String) {
    use axum::extract::ws::Message;

    // The run WebSocket polls for events from active runs and pushes to the client.
    // The client sends user input as JSON: {"run_id": "...", "input": "..."}
    loop {
        tokio::select! {
            msg = socket.recv() => {
                match msg {
                    Some(Ok(Message::Text(text))) => {
                        if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&text) {
                            if let (Some(run_id), Some(input)) = (
                                parsed.get("run_id").and_then(|v| v.as_str()),
                                parsed.get("input").and_then(|v| v.as_str()),
                            ) {
                                let _ = state.runner.send_input(run_id, input).await;
                            }
                        }
                    }
                    _ => break,
                }
            }
            _ = tokio::time::sleep(std::time::Duration::from_millis(100)) => {
                // Poll for events — in production this would use broadcast channels.
                // For MVP, the client can also fetch events via REST.
            }
        }
    }
}
