use axum::extract::ws::{WebSocket, WebSocketUpgrade};
use axum::extract::{Path, State};
use axum::response::IntoResponse;
use axum::routing::get;
use axum::Router;
use std::sync::Arc;

use crate::state::AppState;

pub fn router() -> Router<Arc<AppState>> {
    Router::new().route("/ws/converse/{project_id}", get(ws_converse_handler))
}

async fn ws_converse_handler(
    ws: WebSocketUpgrade,
    State(state): State<Arc<AppState>>,
    Path(project_id): Path<String>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_converse_ws(socket, state, project_id))
}

async fn handle_converse_ws(mut socket: WebSocket, state: Arc<AppState>, project_id: String) {
    use axum::extract::ws::Message;

    let project = match state.project_manager.open_project(&project_id) {
        Ok(p) => p,
        Err(e) => {
            let _ = socket
                .send(Message::Text(
                    serde_json::json!({"type": "error", "message": e.to_string()})
                        .to_string()
                        .into(),
                ))
                .await;
            return;
        }
    };

    let settings = state.settings();
    if settings.api_key.is_empty() {
        let _ = socket
            .send(Message::Text(
                serde_json::json!({"type": "error", "message": "API key not configured. Open Settings to set it."})
                    .to_string()
                    .into(),
            ))
            .await;
        return;
    }
    let harness = match studio_core::agents::build_converser(
        &settings.api_key,
        &settings.model,
        settings.meta_base_url(),
        &project.dir,
    )
    .await
    {
        Ok(h) => h,
        Err(e) => {
            let _ = socket
                .send(Message::Text(
                    serde_json::json!({"type": "error", "message": e.to_string()})
                        .to_string()
                        .into(),
                ))
                .await;
            return;
        }
    };

    let mut rx = harness.subscribe();

    loop {
        tokio::select! {
            msg = socket.recv() => {
                match msg {
                    Some(Ok(Message::Text(text))) => {
                        let text_str = text.to_string();
                        if let Err(e) = harness.prompt(&text_str).await {
                            let _ = socket.send(Message::Text(
                                serde_json::json!({"type": "error", "message": e.to_string()})
                                    .to_string().into()
                            )).await;
                        }
                    }
                    _ => break,
                }
            }
            event = rx.recv() => {
                match event {
                    Ok(ev) => {
                        let event_json = serde_json::to_string(&format_harness_event(&ev)).unwrap_or_default();
                        if socket.send(Message::Text(event_json.into())).await.is_err() {
                            break;
                        }
                    }
                    Err(_) => break,
                }
            }
        }
    }
}

fn format_harness_event(ev: &llm_harness_agent::AgentHarnessEvent) -> serde_json::Value {
    use llm_harness_agent::AgentHarnessEvent;
    use llm_harness_types::AgentEvent;
    match ev {
        AgentHarnessEvent::Agent(agent_ev) => {
            match agent_ev {
                AgentEvent::TextDelta { message_id, text } => serde_json::json!({
                    "type": "text_delta", "message_id": message_id, "text": text
                }),
                AgentEvent::ThinkingDelta { message_id, thinking, .. } => serde_json::json!({
                    "type": "thinking_delta", "message_id": message_id, "text": thinking
                }),
                AgentEvent::ToolCallStart { message_id, tool_use_id, name } => serde_json::json!({
                    "type": "tool_call_start", "message_id": message_id, "tool_use_id": tool_use_id, "name": name
                }),
                AgentEvent::ToolCallEnd { tool_use_id, args } => serde_json::json!({
                    "type": "tool_call_end", "tool_use_id": tool_use_id, "args": args
                }),
                AgentEvent::ToolExecutionStart { tool_use_id, tool_name, args } => serde_json::json!({
                    "type": "tool_execution_start", "tool_use_id": tool_use_id, "tool_name": tool_name, "args": args
                }),
                AgentEvent::ToolExecutionEnd { tool_use_id, result } => serde_json::json!({
                    "type": "tool_execution_end", "tool_use_id": tool_use_id,
                    "ok": result.is_ok()
                }),
                AgentEvent::MessageEnd { message_id, .. } => serde_json::json!({
                    "type": "message_end", "message_id": message_id
                }),
                AgentEvent::TurnEnd { index, .. } => serde_json::json!({
                    "type": "turn_end", "index": index
                }),
                AgentEvent::Error(e) => serde_json::json!({
                    "type": "error", "message": format!("{e:?}")
                }),
                _ => serde_json::json!({"type": "agent_event"}),
            }
        }
        AgentHarnessEvent::Settled => serde_json::json!({"type": "settled"}),
        AgentHarnessEvent::Aborted => serde_json::json!({"type": "aborted"}),
        AgentHarnessEvent::ToolCallStart {
            tool_use_id,
            tool_name,
            args,
        } => serde_json::json!({
            "type": "tool_call_start",
            "tool_use_id": tool_use_id,
            "tool_name": tool_name,
            "args": args,
        }),
        AgentHarnessEvent::ToolCallEnd {
            tool_use_id,
            tool_name,
            result,
        } => serde_json::json!({
            "type": "tool_execution_end",
            "tool_use_id": tool_use_id,
            "tool_name": tool_name,
            "result": {"details": result.details, "is_error": result.is_error},
        }),
        _ => serde_json::json!({"type": "harness_event"}),
    }
}
