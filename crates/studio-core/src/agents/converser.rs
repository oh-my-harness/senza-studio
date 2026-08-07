//! Converser agent: multi-turn dialogue → structured spec JSON.
//!
//! The Converser has 5 tools:
//! - emit_spec(spec_json): output full spec, terminate conversation
//! - emit_spec_diff(diff_json): output incremental spec diff
//! - read_project(path): read current project files
//! - read_current_spec(): read current spec.json
//! - read_run_trace(run_id?): read a run's outcome (errors, final output),
//!   so the Converser can see what actually happened instead of relying on
//!   the user's paraphrase of a failure.

use std::path::Path;
use std::sync::Arc;

use llm_harness_agent::AgentHarness;
use llm_harness_loop::{LlmClient, OpenAIProvider};
use llm_harness_runtime::builder::HarnessBuilder;
use llm_harness_runtime_sandbox_os::OsEnv;
use llm_harness_types::{DataBlock, ThinkingLevel, Tool, ToolFailure, ToolResult};

use crate::agents::studio_tool::StudioTool;
use crate::error::StudioResult;
use crate::spec::{Spec, SpecDiff};

const SYSTEM_PROMPT: &str = include_str!("converser_system_prompt.txt");

/// Build the Converser agent harness.
pub async fn build_converser(
    api_key: &str,
    model: &str,
    base_url: Option<&str>,
    project_dir: &Path,
) -> StudioResult<AgentHarness> {
    let mut provider_builder = OpenAIProvider::builder(api_key)
        .parse_reasoning_content(true);
    if let Some(url) = base_url {
        provider_builder = provider_builder.base_url(url);
    }
    let client: Arc<dyn LlmClient> = Arc::new(provider_builder.build());

    let project_dir = Arc::new(project_dir.to_path_buf());

    // Tool: emit_spec
    let emit_spec_dir = project_dir.clone();
    let emit_spec = StudioTool::new(
        "emit_spec",
        "Output the complete structured spec JSON. Call this when you have enough information to generate the project. The spec_json must be a valid JSON object matching the spec format.",
        serde_json::json!({
            "type": "object",
            "properties": {
                "spec_json": {
                    "type": "object",
                    "description": "The complete spec JSON object"
                }
            },
            "required": ["spec_json"]
        }),
        Box::new(move |invocation| {
            let dir = emit_spec_dir.clone();
            Box::pin(async move {
                let spec_value = invocation.args.get("spec_json").cloned().unwrap_or(serde_json::Value::Null);
                let spec = Spec::from_conversation_json(&spec_value)
                    .map_err(|e| ToolFailure::invalid_arguments(e.to_string()))?;
                spec.validate()
                    .map_err(|e| ToolFailure::invalid_arguments(e.to_string()))?;

                let spec_dir = dir.join(".studio/specs");
                std::fs::create_dir_all(&spec_dir).ok();
                let json = serde_json::to_string_pretty(&spec).unwrap_or_default();
                std::fs::write(spec_dir.join("current.json"), &json).ok();

                let ts = chrono::Utc::now().format("%Y%m%dT%H%M%S");
                std::fs::write(spec_dir.join(format!("{ts}.json")), &json).ok();

                Ok(ToolResult::full(
                    vec![DataBlock::text(format!("Spec saved. Agent type: {:?}, name: {}", spec.agent_type, spec.name))],
                    serde_json::json!({"spec_saved": true, "agent_type": format!("{:?}", spec.agent_type)}),
                    true,
                ))
            })
        }),
    );

    // Tool: emit_spec_diff
    let diff_dir = project_dir.clone();
    let emit_spec_diff = StudioTool::new(
        "emit_spec_diff",
        "Output an incremental spec diff (JSON Patch style) to modify the current spec. Only use this for small changes to an existing project.",
        serde_json::json!({
            "type": "object",
            "properties": {
                "diff_json": {
                    "type": "object",
                    "description": "JSON Patch style diff with 'ops' array"
                }
            },
            "required": ["diff_json"]
        }),
        Box::new(move |invocation| {
            let dir = diff_dir.clone();
            Box::pin(async move {
                let diff_value = invocation.args.get("diff_json").cloned().unwrap_or(serde_json::Value::Null);
                let diff: SpecDiff = serde_json::from_value(diff_value)
                    .map_err(|e| ToolFailure::invalid_arguments(format!("diff parse error: {e}")))?;

                let spec_dir = dir.join(".studio/specs");
                std::fs::create_dir_all(&spec_dir).ok();
                let json = serde_json::to_string_pretty(&diff).unwrap_or_default();
                std::fs::write(spec_dir.join("pending_diff.json"), &json).ok();

                Ok(ToolResult::full(
                    vec![DataBlock::text(format!("Spec diff saved with {} ops.", diff.ops.len()))],
                    serde_json::json!({"diff_saved": true, "ops_count": diff.ops.len()}),
                    true,
                ))
            })
        }),
    );

    // Tool: read_project
    let read_project_dir = project_dir.clone();
    let read_project = StudioTool::new(
        "read_project",
        "Read files from the current project directory. Pass a relative path (e.g., 'main.py', 'tools.py').",
        serde_json::json!({
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path within the project"}
            },
            "required": ["path"]
        }),
        Box::new(move |invocation| {
            let dir = read_project_dir.clone();
            Box::pin(async move {
                let path = invocation.args.get("path")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                let full_path = dir.join(path);

                let canonical_base = dir.as_ref().clone();
                let canonical_file = full_path.canonicalize().map_err(|_| {
                    ToolFailure::invalid_arguments(format!("file not found: {path}"))
                })?;
                if !canonical_file.starts_with(&canonical_base) {
                    return Err(ToolFailure::invalid_arguments("path traversal blocked"));
                }

                let content = std::fs::read_to_string(&full_path)
                    .map_err(|e| ToolFailure::invalid_arguments(format!("read error: {e}")))?;
                let size = content.len();
                Ok(ToolResult::full(
                    vec![DataBlock::text(content)],
                    serde_json::json!({"path": path, "size": size}),
                    false,
                ))
            })
        }),
    );

    // Tool: read_current_spec
    let read_spec_dir = project_dir.clone();
    let read_current_spec = StudioTool::new(
        "read_current_spec",
        "Read the current spec.json from the project. Use this before emitting a spec diff to understand the current state.",
        serde_json::json!({"type": "object", "properties": {}}),
        Box::new(move |_invocation| {
            let dir = read_spec_dir.clone();
            Box::pin(async move {
                let spec_path = dir.join(".studio/specs/current.json");
                if !spec_path.exists() {
                    return Ok(ToolResult::full(
                        vec![DataBlock::text("No current spec found. This is a new project.")],
                        serde_json::json!({"spec_found": false}),
                        false,
                    ));
                }
                let content = std::fs::read_to_string(&spec_path).unwrap_or_default();
                Ok(ToolResult::full(
                    vec![DataBlock::text(content)],
                    serde_json::json!({"spec_found": true}),
                    false,
                ))
            })
        }),
    );

    // Tool: read_run_trace
    let trace_dir = project_dir.clone();
    let read_run_trace = StudioTool::new(
        "read_run_trace",
        "Read the outcome of a run of the user's agent — errors, tool failures, and final output. Call this when the user reports their agent crashed, failed, or behaved unexpectedly, or when you want to verify a fix actually worked. Omit run_id to inspect the most recent run.",
        serde_json::json!({
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "string",
                    "description": "Specific run ID to inspect; omit to use the most recent run."
                }
            },
            "required": []
        }),
        Box::new(move |invocation| {
            let dir = trace_dir.clone();
            Box::pin(async move {
                let requested_run_id = invocation.args.get("run_id").and_then(|v| v.as_str()).map(|s| s.to_string());
                let run_id = match requested_run_id {
                    Some(id) => Some(id),
                    None => crate::runner::Runner::list_runs(&dir)
                        .map_err(|e| ToolFailure::new("execution_failed", format!("failed to list runs: {e}")))?
                        .last()
                        .cloned(),
                };
                let run_id = match run_id {
                    Some(id) => id,
                    None => {
                        return Ok(ToolResult::full(
                            vec![DataBlock::text("No runs found for this project yet.")],
                            serde_json::json!({"run_found": false}),
                            false,
                        ));
                    }
                };

                let events = crate::runner::Runner::read_events_sync(&dir, &run_id)
                    .map_err(|e| ToolFailure::new("execution_failed", format!("failed to read run events: {e}")))?;
                let summary = crate::events::summarize_run_events(&run_id, &events);
                let text = crate::events::format_trace_summary(&summary);
                let details = serde_json::to_value(&summary).unwrap_or(serde_json::Value::Null);

                Ok(ToolResult::full(vec![DataBlock::text(text)], details, false))
            })
        }),
    );

    let env = Arc::new(OsEnv::new(project_dir.as_ref().clone()));

    let harness = HarnessBuilder::new(model)
        .provider("*", client)
        .system_prompt(Some(SYSTEM_PROMPT.into()))
        .max_tokens(8192)
        .thinking_level(ThinkingLevel::High)
        .auto_compact(true)
        .tool(Arc::new(emit_spec) as Arc<dyn Tool>)
        .tool(Arc::new(emit_spec_diff) as Arc<dyn Tool>)
        .tool(Arc::new(read_project) as Arc<dyn Tool>)
        .tool(Arc::new(read_current_spec) as Arc<dyn Tool>)
        .tool(Arc::new(read_run_trace) as Arc<dyn Tool>)
        .build(env)
        .await
        .map_err(|e| crate::error::StudioError::Agent(format!("converser build failed: {e}")))?;

    Ok(harness)
}

#[cfg(test)]
mod tests {
    // LLM tests are #[ignore] — run with: cargo test -- --ignored converser
}
