//! Senza Coding Agent: spec JSON → Python project code.
//!
//! The coding agent has 5 tools:
//! - write_file(path, content): write a project file
//! - read_file(path): read a project file
//! - read_spec(): read the current spec JSON
//! - list_project_files(): list all files in the project
//! - ast_check(path): validate Python syntax

use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use llm_harness_agent::AgentHarness;
use llm_harness_loop::{LlmClient, OpenAIProvider};
use llm_harness_runtime::builder::HarnessBuilder;
use llm_harness_runtime_sandbox_os::OsEnv;
use llm_harness_types::{DataBlock, ThinkingLevel, Tool, ToolFailure, ToolResult};

use crate::agents::studio_tool::StudioTool;
use crate::error::StudioResult;

const SYSTEM_PROMPT: &str = include_str!("coding_agent_system_prompt.txt");

/// Build the Senza coding agent harness.
///
/// `allowed_files`: When `Some`, the write_file tool is restricted to only
/// these paths (used in incremental/diff mode). When `None`, all paths allowed.
///
/// Also returns a flag set to `true` the moment `write_file` first succeeds.
/// `harness.prompt(...)` returning `Ok(())` only means the LLM produced a
/// normal completion — some models/providers respond with a "plan" (or just
/// stop) without ever actually calling a tool, which looks identical to
/// success from the harness's point of view. Callers should treat
/// `!flag.load(...)` after a successful prompt as a real failure.
pub async fn build_coding_agent(
    api_key: &str,
    model: &str,
    base_url: Option<&str>,
    project_dir: &Path,
    allowed_files: Option<Vec<String>>,
) -> StudioResult<(AgentHarness, Arc<AtomicBool>)> {
    let mut provider_builder = OpenAIProvider::builder(api_key)
        .parse_reasoning_content(true);
    if let Some(url) = base_url {
        provider_builder = provider_builder.base_url(url);
    }
    let client: Arc<dyn LlmClient> = Arc::new(provider_builder.build());

    let project_dir = Arc::new(project_dir.to_path_buf());
    let allowed_files = Arc::new(allowed_files);
    let wrote_any_file = Arc::new(AtomicBool::new(false));

    // Tool: write_file
    let write_dir = project_dir.clone();
    let write_allowed = allowed_files.clone();
    let write_flag = wrote_any_file.clone();
    let write_file = StudioTool::new(
        "write_file",
        "Write content to a file in the project. Path is relative to the project root.",
        serde_json::json!({
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path (e.g., 'main.py', 'tools.py')"},
                "content": {"type": "string", "description": "Full file content"}
            },
            "required": ["path", "content"]
        }),
        Box::new(move |invocation| {
            let dir = write_dir.clone();
            let allowed = write_allowed.clone();
            let flag = write_flag.clone();
            Box::pin(async move {
                let path = invocation.args.get("path")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                let content = invocation.args.get("content")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");

                if let Some(allowed_list) = allowed.as_ref() {
                    if !allowed_list.iter().any(|a| a == path) {
                        return Err(ToolFailure::invalid_arguments(
                            format!("File '{path}' is not in the allowed files list: {allowed_list:?}. You can only modify files in this list.")
                        ));
                    }
                }

                let full_path = dir.join(path);
                let canonical_base = dir.as_ref().clone();
                if let Some(parent) = full_path.parent() {
                    std::fs::create_dir_all(parent).ok();
                }
                let canonical_file = full_path.canonicalize().map_err(|_| {
                    ToolFailure::invalid_arguments(format!("cannot resolve path: {path}"))
                })?;
                if !canonical_file.starts_with(&canonical_base) {
                    return Err(ToolFailure::invalid_arguments("path traversal blocked"));
                }

                std::fs::write(&full_path, content)
                    .map_err(|e| ToolFailure::new("execution_failed", format!("write error: {e}")))?;
                flag.store(true, Ordering::Relaxed);

                Ok(ToolResult::full(
                    vec![DataBlock::text(format!("Written {path} ({} bytes). Run ast_check to verify syntax.", content.len()))],
                    serde_json::json!({"path": path, "bytes": content.len()}),
                    false,
                ))
            })
        }),
    );

    // Tool: read_file
    let read_dir = project_dir.clone();
    let read_file = StudioTool::new(
        "read_file",
        "Read a file from the project directory.",
        serde_json::json!({
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path"}
            },
            "required": ["path"]
        }),
        Box::new(move |invocation| {
            let dir = read_dir.clone();
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
                Ok(ToolResult::full(
                    vec![DataBlock::text(content)],
                    serde_json::json!({"path": path}),
                    false,
                ))
            })
        }),
    );

    // Tool: read_spec
    let spec_dir = project_dir.clone();
    let read_spec = StudioTool::new(
        "read_spec",
        "Read the current spec JSON from .studio/specs/current.json. Always call this first before writing any code.",
        serde_json::json!({"type": "object", "properties": {}}),
        Box::new(move |_invocation| {
            let dir = spec_dir.clone();
            Box::pin(async move {
                let spec_path = dir.join(".studio/specs/current.json");
                if !spec_path.exists() {
                    return Ok(ToolResult::full(
                        vec![DataBlock::text("No spec found. Cannot generate code without a spec.")],
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

    // Tool: list_project_files
    let list_dir = project_dir.clone();
    let list_project_files = StudioTool::new(
        "list_project_files",
        "List all files in the project (excluding .studio/ directory).",
        serde_json::json!({"type": "object", "properties": {}}),
        Box::new(move |_invocation| {
            let dir = list_dir.clone();
            Box::pin(async move {
                let mut files = vec![];
                collect_files(&dir, &dir, &mut files);
                files.sort();
                let listing = files.join("\n");
                Ok(ToolResult::full(
                    vec![DataBlock::text(listing)],
                    serde_json::json!({"count": files.len()}),
                    false,
                ))
            })
        }),
    );

    // Tool: ast_check
    let ast_dir = project_dir.clone();
    let ast_check = StudioTool::new(
        "ast_check",
        "Validate Python syntax of a file using python3 -c 'import ast; ast.parse(...)'. Always call after write_file.",
        serde_json::json!({
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path to check"}
            },
            "required": ["path"]
        }),
        Box::new(move |invocation| {
            let dir = ast_dir.clone();
            Box::pin(async move {
                let path = invocation.args.get("path")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                let full_path = dir.join(path);
                if !full_path.exists() {
                    return Err(ToolFailure::invalid_arguments(format!("file not found: {path}")));
                }
                let output = std::process::Command::new("python3")
                    .arg("-c")
                    .arg(format!("import ast; ast.parse(open('{}').read())", full_path.display()))
                    .output()
                    .map_err(|e| ToolFailure::new("execution_failed", format!("python3 error: {e}")))?;

                if output.status.success() {
                    Ok(ToolResult::full(
                        vec![DataBlock::text(format!("OK: {path} syntax valid"))],
                        serde_json::json!({"path": path, "valid": true}),
                        false,
                    ))
                } else {
                    let stderr = String::from_utf8_lossy(&output.stderr);
                    Err(ToolFailure::new("syntax_error", format!("Python syntax error in {path}:\n{stderr}")))
                }
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
        .tool(Arc::new(write_file) as Arc<dyn Tool>)
        .tool(Arc::new(read_file) as Arc<dyn Tool>)
        .tool(Arc::new(read_spec) as Arc<dyn Tool>)
        .tool(Arc::new(list_project_files) as Arc<dyn Tool>)
        .tool(Arc::new(ast_check) as Arc<dyn Tool>)
        .build(env)
        .await
        .map_err(|e| crate::error::StudioError::Agent(format!("coding agent build failed: {e}")))?;

    Ok((harness, wrote_any_file))
}

fn collect_files(base: &Path, current: &Path, files: &mut Vec<String>) {
    if let Ok(entries) = std::fs::read_dir(current) {
        for entry in entries.flatten() {
            let path = entry.path();
            let name = entry.file_name();
            if name == ".studio" {
                continue;
            }
            if path.is_dir() {
                collect_files(base, &path, files);
            } else if let Ok(rel) = path.strip_prefix(base) {
                files.push(rel.to_string_lossy().into_owned());
            }
        }
    }
}

#[cfg(test)]
mod tests {
    // LLM tests are #[ignore] — run with: cargo test -- --ignored coding_agent

    use super::*;

    /// Diagnostic: subscribe to the harness event stream during a real
    /// `generate` call and print every event, to see what's actually
    /// happening when `write_file` never gets called (routes/generate.rs
    /// only checks `.prompt()`'s top-level `Result`, which doesn't surface
    /// this — the call returns `Ok(())` even when zero tool calls happen).
    #[tokio::test]
    #[ignore]
    async fn debug_generate_event_stream() {
        let settings_json = std::fs::read_to_string(
            std::env::var("SENZA_STUDIO_SETTINGS_PATH").unwrap_or_else(|_| "../../settings.json".into()),
        )
        .expect("read settings.json (run from repo root or set SENZA_STUDIO_SETTINGS_PATH)");
        let settings: serde_json::Value = serde_json::from_str(&settings_json).unwrap();
        let api_key = settings["api_key"].as_str().unwrap().to_string();
        let model = settings["model"].as_str().unwrap().to_string();
        let base_url = settings["base_url"].as_str().filter(|s| !s.is_empty()).map(|s| s.to_string());

        let tmp = tempfile::TempDir::new().unwrap();
        std::fs::create_dir_all(tmp.path().join(".studio/specs")).unwrap();
        let spec = serde_json::json!({
            "agent_type": "single",
            "name": "debug-agent",
            "description": "diagnostic",
            "model": model,
            "system_prompt": "You are a friendly greeter.",
            "max_tokens": 512,
            "tools": [],
            "deploy": "cli",
            "provider": {"type": "openai"}
        });
        std::fs::write(
            tmp.path().join(".studio/specs/current.json"),
            serde_json::to_string_pretty(&spec).unwrap(),
        )
        .unwrap();

        let (harness, wrote_any_file) = build_coding_agent(&api_key, &model, base_url.as_deref(), tmp.path(), None)
            .await
            .expect("build_coding_agent");
        let harness = std::sync::Arc::new(harness);

        let mut rx = harness.subscribe();
        let prompt = "Read the spec using read_spec(), then generate all project files. Write main.py (and tools.py, workflow.py, server.py as needed based on the spec). Run ast_check on each file after writing.";

        let prompt_task = {
            let h = harness.clone();
            tokio::spawn(async move { h.prompt(prompt).await })
        };

        let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(45);
        loop {
            tokio::select! {
                ev = rx.recv() => {
                    match ev {
                        Ok(event) => eprintln!("EVENT: {event:?}"),
                        Err(e) => { eprintln!("EVENT STREAM ENDED: {e:?}"); break; }
                    }
                }
                _ = tokio::time::sleep_until(deadline) => {
                    eprintln!("TIMEOUT waiting for events");
                    break;
                }
            }
        }

        let prompt_result = prompt_task.await;
        eprintln!("prompt() task result: {prompt_result:?}");

        let mut files = vec![];
        collect_files(tmp.path(), tmp.path(), &mut files);
        eprintln!("Files written: {files:?}");
        eprintln!("wrote_any_file flag: {}", wrote_any_file.load(Ordering::Relaxed));
    }
}
