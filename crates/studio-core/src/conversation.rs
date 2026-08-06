//! Persisted conversation transcript for the Converse tab.
//!
//! Stored as plain text turns (`.studio/conversation.json`) — deliberately
//! not the full `AgentMessage`/`ContentBlock` structure. This is the same
//! shape already used for display (matches the frontend `Message` type),
//! and is what gets fed back into a freshly-built `AgentHarness` via
//! `to_agent_messages` + `prompt_with_messages` to restore LLM context on
//! reconnect, not just redraw the chat UI. Tool-call arguments/results are
//! intentionally not round-tripped — what's persisted mirrors exactly what's
//! already shown live (text, thinking, and "🔧 tool(...)" marker bubbles).

use std::path::Path;

use serde::{Deserialize, Serialize};

use llm_harness_types::{AgentMessage, AssistantMessage, AssistantMessageKind, ContentBlock, UserMessage};

use crate::error::StudioResult;

const CONVERSATION_FILE: &str = ".studio/conversation.json";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConversationMessage {
    pub role: String, // "user" | "assistant"
    pub content: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub thinking: Option<String>,
    pub timestamp: chrono::DateTime<chrono::Utc>,
}

/// Load the persisted conversation transcript. Missing file → empty list.
pub fn load_conversation(project_dir: &Path) -> StudioResult<Vec<ConversationMessage>> {
    let path = project_dir.join(CONVERSATION_FILE);
    if !path.exists() {
        return Ok(vec![]);
    }
    let json = std::fs::read_to_string(&path)?;
    Ok(serde_json::from_str(&json)?)
}

/// Persist the conversation transcript, overwriting any previous contents.
pub fn save_conversation(project_dir: &Path, messages: &[ConversationMessage]) -> StudioResult<()> {
    let path = project_dir.join(CONVERSATION_FILE);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let json = serde_json::to_string_pretty(messages)?;
    std::fs::write(&path, json)?;
    Ok(())
}

/// Convert a persisted transcript into `AgentMessage`s for seeding a fresh
/// `AgentHarness` via `prompt_with_messages`. `message_id`/`turn_id` are
/// synthesized since they aren't persisted — they're only used for internal
/// harness bookkeeping, never surfaced to the user.
pub fn to_agent_messages(messages: &[ConversationMessage]) -> Vec<AgentMessage> {
    messages
        .iter()
        .map(|m| {
            if m.role == "user" {
                AgentMessage::User(UserMessage {
                    content: vec![ContentBlock::Text { text: m.content.clone() }],
                    timestamp: m.timestamp,
                })
            } else {
                let mut content = vec![];
                if let Some(thinking) = &m.thinking {
                    content.push(ContentBlock::Thinking {
                        thinking: thinking.clone(),
                        signature: None,
                    });
                }
                content.push(ContentBlock::Text { text: m.content.clone() });
                AgentMessage::Assistant(AssistantMessage {
                    kind: AssistantMessageKind::FinalAnswer,
                    message_id: uuid::Uuid::now_v7().to_string(),
                    turn_id: uuid::Uuid::now_v7().to_string(),
                    content,
                    stop_reason: None,
                    timestamp: m.timestamp,
                    provider: None,
                    api: None,
                    model: None,
                    usage: None,
                    error_message: None,
                })
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn sample() -> Vec<ConversationMessage> {
        vec![
            ConversationMessage {
                role: "user".into(),
                content: "build me a chatbot".into(),
                thinking: None,
                timestamp: chrono::Utc::now(),
            },
            ConversationMessage {
                role: "assistant".into(),
                content: "Sure, what should it be about?".into(),
                thinking: Some("the user wants a chatbot".into()),
                timestamp: chrono::Utc::now(),
            },
        ]
    }

    #[test]
    fn test_load_missing_file_returns_empty() {
        let dir = TempDir::new().unwrap();
        let result = load_conversation(dir.path()).unwrap();
        assert!(result.is_empty());
    }

    #[test]
    fn test_save_and_load_roundtrip() {
        let dir = TempDir::new().unwrap();
        let messages = sample();
        save_conversation(dir.path(), &messages).unwrap();
        let loaded = load_conversation(dir.path()).unwrap();
        assert_eq!(loaded.len(), 2);
        assert_eq!(loaded[0].role, "user");
        assert_eq!(loaded[0].content, "build me a chatbot");
        assert_eq!(loaded[1].role, "assistant");
        assert_eq!(loaded[1].thinking.as_deref(), Some("the user wants a chatbot"));
    }

    #[test]
    fn test_to_agent_messages_shape() {
        let messages = sample();
        let agent_messages = to_agent_messages(&messages);
        assert_eq!(agent_messages.len(), 2);

        match &agent_messages[0] {
            AgentMessage::User(u) => {
                assert_eq!(u.content.len(), 1);
                match &u.content[0] {
                    ContentBlock::Text { text } => assert_eq!(text, "build me a chatbot"),
                    _ => panic!("expected Text block"),
                }
            }
            _ => panic!("expected User message"),
        }

        match &agent_messages[1] {
            AgentMessage::Assistant(a) => {
                assert_eq!(a.content.len(), 2);
                assert!(matches!(a.content[0], ContentBlock::Thinking { .. }));
                assert!(matches!(a.content[1], ContentBlock::Text { .. }));
            }
            _ => panic!("expected Assistant message"),
        }
    }
}
