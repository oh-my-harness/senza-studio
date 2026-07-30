use axum::extract::ws::{WebSocket, WebSocketUpgrade};
use axum::extract::{Path, State};
use axum::response::IntoResponse;
use axum::routing::get;
use axum::Router;
use std::sync::Arc;

use crate::state::AppState;

pub fn router() -> Router<Arc<AppState>> {
    Router::new().route("/ws/run/{project_id}", get(ws_run_handler))
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

    // Wait for the client to tell us which run_id to subscribe to.
    // The first message must be {"run_id": "..."}.
    let run_id = loop {
        match socket.recv().await {
            Some(Ok(Message::Text(text))) => {
                if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&text) {
                    if let Some(id) = parsed.get("run_id").and_then(|v| v.as_str()) {
                        break id.to_string();
                    }
                }
            }
            _ => return,
        }
    };

    // Get the run handle and subscribe to its broadcast channel.
    let handle = match state.runner.get_run(&run_id).await {
        Some(h) => h,
        None => {
            let _ = socket.send(Message::Text(
                serde_json::json!({"type": "error", "message": format!("run {run_id} not found")})
                    .to_string().into(),
            )).await;
            return;
        }
    };

    let mut rx = handle.subscribe();

    // Send settled event so the frontend knows streaming is live.
    let _ = socket.send(Message::Text(
        serde_json::json!({"type": "settled"}).to_string().into()
    )).await;

    loop {
        tokio::select! {
            msg = socket.recv() => {
                match msg {
                    Some(Ok(Message::Text(text))) => {
                        if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&text) {
                            if let (Some(msg_run_id), Some(input)) = (
                                parsed.get("run_id").and_then(|v| v.as_str()),
                                parsed.get("input").and_then(|v| v.as_str()),
                            ) {
                                let _ = state.runner.send_input(msg_run_id, input).await;
                            }
                        }
                    }
                    _ => break,
                }
            }
            event = rx.recv() => {
                match event {
                    Ok(ev) => {
                        let json = serde_json::to_string(&ev).unwrap_or_default();
                        if socket.send(Message::Text(json.into())).await.is_err() {
                            break;
                        }
                    }
                    Err(tokio::sync::broadcast::error::RecvError::Lagged(_)) => continue,
                    Err(_) => {
                        // Channel closed — process exited
                        let _ = socket.send(Message::Text(
                            serde_json::json!({"type": "done"}).to_string().into()
                        )).await;
                        break;
                    }
                }
            }
        }
    }
}
