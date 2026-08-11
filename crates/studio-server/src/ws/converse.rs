use axum::extract::ws::{WebSocket, WebSocketUpgrade};
use axum::extract::{Path, State};
use axum::response::IntoResponse;
use axum::routing::get;
use axum::Router;
use std::sync::Arc;

use studio_core::conversation::{
    load_conversation, save_conversation, to_agent_messages, ConversationMessage,
};

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

    let project = match state.project_manager().open_project(&project_id) {
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
        Ok(h) => Arc::new(h),
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

    // Restore prior conversation, if any — the harness above was just built
    // fresh with an empty in-memory session, so on the first message of this
    // connection we seed it with everything discussed before via
    // prompt_with_messages, instead of just prompt(text). This gives the LLM
    // actual context continuity across reconnects, not just a redrawn chat UI.
    let mut transcript = load_conversation(&project.dir).unwrap_or_default();
    let mut seeded = false;
    let mut current_text = String::new();
    let mut current_thinking = String::new();

    loop {
        tokio::select! {
            msg = socket.recv() => {
                match msg {
                    Some(Ok(Message::Text(text))) => {
                        let text_str = text.to_string();

                        transcript.push(ConversationMessage {
                            role: "user".into(),
                            content: text_str.clone(),
                            thinking: None,
                            timestamp: chrono::Utc::now(),
                        });
                        let _ = save_conversation(&project.dir, &transcript);
                        current_text.clear();
                        current_thinking.clear();

                        // Spawn prompt as a separate task so events flow concurrently
                        let h = harness.clone();
                        if !seeded {
                            let seed_messages = to_agent_messages(&transcript);
                            tokio::spawn(async move {
                                if let Err(e) = h.prompt_with_messages(seed_messages).await {
                                    tracing::error!("converser prompt_with_messages error: {e}");
                                }
                            });
                            seeded = true;
                        } else {
                            tokio::spawn(async move {
                                if let Err(e) = h.prompt(&text_str).await {
                                    tracing::error!("converser prompt error: {e}");
                                }
                            });
                        }
                    }
                    _ => break,
                }
            }
            event = rx.recv() => {
                match event {
                    Ok(ev) => {
                        let event_json = format_harness_event(&ev);
                        accumulate_for_transcript(
                            &event_json,
                            &mut transcript,
                            &mut current_text,
                            &mut current_thinking,
                            &project.dir,
                        );
                        let event_str = serde_json::to_string(&event_json).unwrap_or_default();
                        if socket.send(Message::Text(event_str.into())).await.is_err() {
                            break;
                        }
                    }
                    Err(tokio::sync::broadcast::error::RecvError::Lagged(_)) => continue,
                    Err(_) => break,
                }
            }
        }
    }
}

/// Feed a formatted (already client-bound) event into the persisted
/// transcript accumulator. Driven by the same `"type"` strings the frontend
/// already keys off of (`onConverseEvent` in `projectStore.ts`), so the
/// restored transcript has the same fidelity as what was shown live —
/// including the same "🔧 tool(...)" marker bubbles for tool calls.
fn accumulate_for_transcript(
    event_json: &serde_json::Value,
    transcript: &mut Vec<ConversationMessage>,
    current_text: &mut String,
    current_thinking: &mut String,
    project_dir: &std::path::Path,
) {
    let ty = event_json.get("type").and_then(|t| t.as_str()).unwrap_or("");
    match ty {
        "text_delta" => {
            if let Some(t) = event_json.get("text").and_then(|t| t.as_str()) {
                current_text.push_str(t);
            }
        }
        "thinking_delta" => {
            if let Some(t) = event_json.get("thinking").and_then(|t| t.as_str()) {
                current_thinking.push_str(t);
            }
        }
        "tool_call_start" | "tool_execution_start" => {
            flush_turn(transcript, current_text, current_thinking);
            let name = event_json
                .get("name")
                .or_else(|| event_json.get("tool_name"))
                .and_then(|n| n.as_str())
                .unwrap_or("tool");
            transcript.push(ConversationMessage {
                role: "assistant".into(),
                content: format!("🔧 {name}(...)"),
                thinking: None,
                timestamp: chrono::Utc::now(),
            });
            let _ = save_conversation(project_dir, transcript);
        }
        "settled" | "aborted" | "error" => {
            flush_turn(transcript, current_text, current_thinking);
            let _ = save_conversation(project_dir, transcript);
        }
        _ => {}
    }
}

/// Push accumulated text/thinking as a completed assistant turn, if any.
fn flush_turn(transcript: &mut Vec<ConversationMessage>, current_text: &mut String, current_thinking: &mut String) {
    if current_text.is_empty() && current_thinking.is_empty() {
        return;
    }
    transcript.push(ConversationMessage {
        role: "assistant".into(),
        content: std::mem::take(current_text),
        thinking: if current_thinking.is_empty() { None } else { Some(std::mem::take(current_thinking)) },
        timestamp: chrono::Utc::now(),
    });
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
                    "type": "thinking_delta", "message_id": message_id, "thinking": thinking
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
