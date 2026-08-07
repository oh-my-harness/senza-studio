//! Event types for the Studio event stream.
//!
//! Events are serde_json::Value to allow flexible passthrough of SDK events
//! without tight coupling to internal Rust types. The `type` field discriminates.

use std::collections::HashMap;

use serde::Serialize;
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

/// Deterministic summary of a run's outcome, extracted from its event
/// stream — built for a meta-agent tool to consume (see
/// `agents::converser::build_converser`'s `read_run_trace` tool), not for
/// UI rendering (see `frontend/src/components/trace/timeline.ts` for that).
#[derive(Debug, Clone, Serialize)]
pub struct RunTraceSummary {
    pub run_id: String,
    pub status: String, // "settled" | "aborted" | "error" | "unknown"
    pub errors: Vec<TraceError>,
    pub final_output: Option<String>,
    pub steps: Vec<StepSummary>, // empty for non-workflow runs
}

#[derive(Debug, Clone, Serialize)]
pub struct TraceError {
    pub source: String, // "agent_error" | "tool_execution" | "workflow_failed"
    pub tool_name: Option<String>,
    pub message: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct StepSummary {
    pub step_id: String,
    pub step_name: Option<String>,
    pub status: String, // "done" | "unfinished"
    pub had_error: bool,
}

fn str_field<'a>(ev: &'a Value, key: &str) -> Option<&'a str> {
    ev.get(key)?.as_str()
}

fn ok_field(ev: &Value) -> Option<bool> {
    ev.get("ok")?.as_bool()
}

/// Handle a single tool-lifecycle event (already unwrapped from
/// `step_progress.progress` if applicable), updating the correlation map
/// and pushing a `TraceError` on failure.
fn handle_tool_event(
    ev: &Value,
    ty: &str,
    tool_names: &mut HashMap<String, String>,
    errors: &mut Vec<TraceError>,
) {
    let tool_use_id = match str_field(ev, "tool_use_id") {
        Some(id) => id.to_string(),
        None => return,
    };
    match ty {
        "tool_call_start" => {
            let name = str_field(ev, "name").or_else(|| str_field(ev, "tool_name"));
            if let Some(name) = name {
                tool_names.insert(tool_use_id, name.to_string());
            }
        }
        "tool_execution_start" => {
            if let Some(name) = str_field(ev, "tool_name") {
                tool_names.insert(tool_use_id, name.to_string());
            }
        }
        "tool_execution_end" => {
            if ok_field(ev) == Some(false) {
                let message = str_field(ev, "error").unwrap_or("tool execution failed").to_string();
                errors.push(TraceError {
                    source: "tool_execution".into(),
                    tool_name: tool_names.get(&tool_use_id).cloned(),
                    message,
                });
            }
        }
        _ => {}
    }
}

/// Summarize a run's event stream into a compact, failure-focused view.
pub fn summarize_run_events(run_id: &str, events: &[Value]) -> RunTraceSummary {
    let mut status = "unknown".to_string();
    let mut errors: Vec<TraceError> = vec![];
    let mut tool_names: HashMap<String, String> = HashMap::new();
    let mut final_output: Option<String> = None;
    let mut current_text = String::new();

    let mut steps: Vec<StepSummary> = vec![];
    let mut open_step_idx: Option<usize> = None;
    let mut open_step_had_error = false;

    for ev in events {
        let ty = match event_type(ev) {
            Some(t) => t,
            None => continue,
        };

        match ty {
            "settled" => status = "settled".into(),
            "aborted" => status = "aborted".into(),
            "error" => {
                let message = str_field(ev, "message").unwrap_or("unknown error").to_string();
                errors.push(TraceError { source: "agent_error".into(), tool_name: None, message });
            }
            "failed" => {
                let message = str_field(ev, "error").unwrap_or("workflow failed").to_string();
                errors.push(TraceError { source: "workflow_failed".into(), tool_name: None, message });
            }
            "text_delta" => {
                if let Some(t) = str_field(ev, "text") {
                    current_text.push_str(t);
                }
            }
            "message_end" => {
                if let Some(t) = str_field(ev, "text") {
                    current_text = t.to_string();
                }
                final_output = Some(current_text.clone());
            }
            "step_started" => {
                steps.push(StepSummary {
                    step_id: str_field(ev, "step_id").unwrap_or_default().to_string(),
                    step_name: str_field(ev, "step_name").map(|s| s.to_string()),
                    status: "unfinished".into(),
                    had_error: false,
                });
                open_step_idx = Some(steps.len() - 1);
                open_step_had_error = false;
            }
            "step_finished" => {
                if let Some(idx) = open_step_idx.take() {
                    steps[idx].status = "done".into();
                    steps[idx].had_error = open_step_had_error;
                }
                open_step_had_error = false;
            }
            "step_progress" => {
                if let Some(progress) = ev.get("progress") {
                    if let Some(inner_ty) = event_type(progress) {
                        let before = errors.len();
                        handle_tool_event(progress, inner_ty, &mut tool_names, &mut errors);
                        if errors.len() > before {
                            open_step_had_error = true;
                        }
                    }
                }
            }
            "tool_call_start" | "tool_execution_start" | "tool_execution_end" => {
                handle_tool_event(ev, ty, &mut tool_names, &mut errors);
            }
            _ => {}
        }
    }

    if final_output.is_none() && !current_text.is_empty() {
        final_output = Some(current_text);
    }
    if !errors.is_empty() {
        status = "error".into();
    }

    RunTraceSummary {
        run_id: run_id.to_string(),
        status,
        errors,
        final_output,
        steps,
    }
}

/// Render a `RunTraceSummary` as short, readable text for the model —
/// deliberately not a JSON dump; this is what gets sent as the tool's
/// model-visible content.
pub fn format_trace_summary(summary: &RunTraceSummary) -> String {
    let mut out = format!("Run {} — status: {}\n", summary.run_id, summary.status);

    if !summary.steps.is_empty() {
        out.push_str("\nSteps:\n");
        for step in &summary.steps {
            let name = step.step_name.as_deref().unwrap_or(&step.step_id);
            let flag = if step.had_error { " (error)" } else { "" };
            out.push_str(&format!("- {name}: {}{flag}\n", step.status));
        }
    }

    if !summary.errors.is_empty() {
        out.push_str("\nErrors:\n");
        for e in &summary.errors {
            match &e.tool_name {
                Some(name) => out.push_str(&format!("- [{}] {name}: {}\n", e.source, e.message)),
                None => out.push_str(&format!("- [{}] {}\n", e.source, e.message)),
            }
        }
    } else {
        out.push_str("\nNo errors.\n");
    }

    match &summary.final_output {
        Some(text) if !text.is_empty() => out.push_str(&format!("\nFinal output: {text}\n")),
        _ => out.push_str("\nFinal output: (none — agent may have failed before producing output)\n"),
    }

    out
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

    #[test]
    fn test_summarize_clean_single_agent_run() {
        let events = vec![
            json!({"type": "text_delta", "message_id": "m1", "text": "Your order "}),
            json!({"type": "text_delta", "message_id": "m1", "text": "has shipped."}),
            json!({"type": "message_end", "message_id": "m1", "text": "Your order has shipped."}),
            json!({"type": "settled"}),
        ];
        let summary = summarize_run_events("run-1", &events);
        assert_eq!(summary.status, "settled");
        assert!(summary.errors.is_empty());
        assert_eq!(summary.final_output.as_deref(), Some("Your order has shipped."));
        assert!(summary.steps.is_empty());
    }

    #[test]
    fn test_summarize_single_agent_failing_tool_call() {
        let events = vec![
            json!({"type": "tool_call_start", "tool_use_id": "t1", "name": "lookup_order"}),
            json!({"type": "tool_execution_start", "tool_use_id": "t1", "tool_name": "lookup_order"}),
            json!({"type": "tool_execution_end", "tool_use_id": "t1", "ok": false, "error": "KeyError: 'order_id'"}),
            json!({"type": "error", "message": "agent gave up"}),
            json!({"type": "aborted"}),
        ];
        let summary = summarize_run_events("run-2", &events);
        assert_eq!(summary.status, "error"); // errors override the terminal marker
        assert_eq!(summary.errors.len(), 2);
        assert_eq!(summary.errors[0].source, "tool_execution");
        assert_eq!(summary.errors[0].tool_name.as_deref(), Some("lookup_order"));
        assert_eq!(summary.errors[0].message, "KeyError: 'order_id'");
        assert_eq!(summary.errors[1].source, "agent_error");
    }

    #[test]
    fn test_summarize_workflow_run_with_step_progress_failure_and_unfinished_step() {
        let events = vec![
            json!({"type": "step_started", "step_id": "s1", "step_name": "classify"}),
            json!({
                "type": "step_progress", "step_id": "s1",
                "progress": {"type": "tool_call_start", "tool_use_id": "t1", "name": "classify_tool"}
            }),
            json!({
                "type": "step_progress", "step_id": "s1",
                "progress": {"type": "tool_execution_end", "tool_use_id": "t1", "ok": false, "error": "timeout"}
            }),
            json!({"type": "step_finished", "step_id": "s1", "output": "failed", "structured": null}),
            json!({"type": "step_started", "step_id": "s2", "step_name": "report"}),
            // s2 never gets a step_finished — process killed mid-step.
        ];
        let summary = summarize_run_events("run-3", &events);
        assert_eq!(summary.status, "error");
        assert_eq!(summary.steps.len(), 2);
        assert_eq!(summary.steps[0].status, "done");
        assert!(summary.steps[0].had_error);
        assert_eq!(summary.steps[1].status, "unfinished");
        assert!(!summary.steps[1].had_error);
        assert_eq!(summary.errors.len(), 1);
        assert_eq!(summary.errors[0].tool_name.as_deref(), Some("classify_tool"));
    }

    #[test]
    fn test_summarize_empty_events() {
        let summary = summarize_run_events("run-4", &[]);
        assert_eq!(summary.status, "unknown");
        assert!(summary.errors.is_empty());
        assert!(summary.final_output.is_none());
        assert!(summary.steps.is_empty());
    }

    #[test]
    fn test_format_trace_summary_readable() {
        let summary = RunTraceSummary {
            run_id: "run-1".into(),
            status: "error".into(),
            errors: vec![TraceError {
                source: "tool_execution".into(),
                tool_name: Some("lookup_order".into()),
                message: "KeyError: 'order_id'".into(),
            }],
            final_output: None,
            steps: vec![],
        };
        let text = format_trace_summary(&summary);
        assert!(text.contains("status: error"));
        assert!(text.contains("lookup_order"));
        assert!(text.contains("KeyError"));
        assert!(text.contains("Final output: (none"));
    }
}
