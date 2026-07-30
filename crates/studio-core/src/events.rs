//! Event types for the Studio event stream.
//!
//! Events are serde_json::Value to allow flexible passthrough of SDK events
//! without tight coupling to internal Rust types. The `type` field discriminates.

use serde_json::Value;

/// Extract the event type string from an event JSON.
pub fn event_type(event: &Value) -> Option<&str> {
    event.get("type")?.as_str()
}

/// Parse events.jsonl content into a list of JSON events.
/// Empty lines and malformed JSON are silently skipped.
pub fn parse_events_jsonl(content: &str) -> Vec<Value> {
    content
        .lines()
        .filter(|line| !line.trim().is_empty())
        .filter_map(|line| serde_json::from_str(line).ok())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_event_type_extraction() {
        let event = json!({"type": "text_delta", "text": "hello"});
        assert_eq!(event_type(&event), Some("text_delta"));
    }

    #[test]
    fn test_event_type_missing() {
        let event = json!({"text": "hello"});
        assert_eq!(event_type(&event), None);
    }

    #[test]
    fn test_events_jsonl_parse() {
        let jsonl = r#"{"type":"step_started","step_id":"s1","step_name":"Step 1"}
{"type":"text_delta","text":"hello"}
{"type":"step_finished","step_id":"s1","result":{"output":"hello","structured":null,"tool_calls_count":0,"session_id":"sess1","cost":{"total_cost":0.001}}}"#;
        let events = parse_events_jsonl(jsonl);
        assert_eq!(events.len(), 3);
        assert_eq!(event_type(&events[0]), Some("step_started"));
        assert_eq!(event_type(&events[2]), Some("step_finished"));
    }

    #[test]
    fn test_events_jsonl_empty_lines_skipped() {
        let jsonl = "{\"type\":\"settled\"}\n\n\n";
        let events = parse_events_jsonl(jsonl);
        assert_eq!(events.len(), 1);
    }

    #[test]
    fn test_events_jsonl_malformed_skipped() {
        let jsonl = "{\"type\":\"settled\"}\nnot json\n{\"type\":\"error\",\"message\":\"oops\"}";
        let events = parse_events_jsonl(jsonl);
        assert_eq!(events.len(), 2);
    }
}
