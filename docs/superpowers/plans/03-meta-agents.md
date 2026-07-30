# Plan 3: Meta Agents

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the two meta-agents (Converser + Senza Coding Agent) as `AgentHarness` instances with `Tool` trait implementations, plus the `StudioTool` helper and the diff rule engine.

**Architecture:** Each meta-agent is an `AgentHarness` built via `HarnessBuilder`. The Converser has 4 tools (`emit_spec`, `emit_spec_diff`, `read_project`, `read_current_spec`). The Coding Agent has 5 tools (`write_file`, `read_file`, `read_spec`, `list_project_files`, `ast_check`). A `StudioTool` helper struct reduces boilerplate. The diff rule engine maps spec diff paths to affected files deterministically.

**Tech Stack:** Rust 2024, `llm-harness-runtime` (HarnessBuilder, AgentHarness), `llm-harness-types` (Tool trait, ToolResult, ToolFailure, DataBlock), `llm-harness-loop` (OpenAIProvider, LlmClient), `llm-harness-runtime-sandbox-os` (OsEnv).

## Global Constraints

(See `00-overview.md`)

---

## File Structure

```
crates/studio-core/src/
├── agents/
│   ├── mod.rs               # Module root, agent builder helpers
│   ├── studio_tool.rs       # StudioTool helper struct (reduces Tool impl boilerplate)
│   ├── converser.rs         # Converser agent: build + 4 tools + system prompt
│   ├── coding_agent.rs      # Senza coding agent: build + 5 tools + system prompt
│   └── diff_engine.rs       # Rule engine: spec diff → affected files
```

---

### Task 1: StudioTool Helper (studio_tool.rs)

**Files:**
- Create: `crates/studio-core/src/agents/mod.rs`
- Create: `crates/studio-core/src/agents/studio_tool.rs`
- Modify: `crates/studio-core/src/lib.rs` (add `pub mod agents;`)
- Test: inline in `studio_tool.rs`

**Interfaces:**
- Produces: `StudioTool` struct implementing `Tool` trait
- Consumes: `llm-harness-types::{Tool, ToolResult, ToolFailure, ToolContext, DataBlock}`

**Design doc reference:** §6 工具实现, §6 StudioTool helper

- [ ] **Step 1: Write the failing test**

```rust
// In studio_tool.rs

#[cfg(test)]
mod tests {
    use super::*;
    use llm_harness_types::{ToolContext, ToolResult, ToolFailure, DataBlock};
    use std::sync::Arc;

    #[tokio::test]
    async fn test_studio_tool_executes_closure() {
        let schema = serde_json::json!({"type": "object", "properties": {"path": {"type": "string"}}});
        let tool = StudioTool::new(
            "write_file",
            "Write a file to the project",
            schema,
            |_args, _ctx| {
                Box::pin(async move {
                    Ok(ToolResult::full(
                        vec![DataBlock::text("File written.")],
                        serde_json::json!({"success": true}),
                        false,
                    ))
                })
            },
        );

        assert_eq!(tool.name(), "write_file");
        assert_eq!(tool.description(), "Write a file to the project");

        let ctx = make_test_context();
        let result = tool.execute(serde_json::json!({"path": "main.py", "content": "print(1)"}), &ctx).await;
        assert!(result.is_ok());
        let tool_result = result.unwrap();
        assert!(!tool_result.terminate);
    }

    #[tokio::test]
    async fn test_studio_tool_returns_error_from_closure() {
        let tool = StudioTool::new(
            "read_file",
            "Read a file",
            serde_json::json!({"type": "object"}),
            |_args, _ctx| {
                Box::pin(async move {
                    Err(ToolFailure::new("file_not_found", "File does not exist"))
                })
            },
        );

        let ctx = make_test_context();
        let result = tool.execute(serde_json::json!({}), &ctx).await;
        assert!(result.is_err());
    }

    fn make_test_context() -> ToolContext {
        // ToolContext requires RunContext + env; for testing we use a minimal setup.
        // This is complex; in practice tests use the full agent harness.
        // For unit tests of StudioTool, we test the closure logic separately.
        unimplemented!("ToolContext construction requires full runtime setup")
    }
}
```

Note: The `make_test_context` is problematic because `ToolContext` requires a full `RunContext` + `ExecutionEnv`. For unit testing tools, we'll test the closure logic directly instead of through the `Tool::execute` interface. Let's adjust the tests:

```rust
    #[tokio::test]
    async fn test_studio_tool_name_and_description() {
        let schema = serde_json::json!({"type": "object"});
        let tool = StudioTool::new(
            "test_tool",
            "A test tool",
            schema.clone(),
            Box::new(|_args, _ctx| Box::pin(async move {
                Ok(ToolResult::full(vec![DataBlock::text("ok")], serde_json::json!({}), false))
            })),
        );

        assert_eq!(tool.name(), "test_tool");
        assert_eq!(tool.description(), "A test tool");
        assert_eq!(tool.parameters_schema(), &schema);
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --lib studio_tool`
Expected: FAIL — `StudioTool` not defined

- [ ] **Step 3: Write minimal implementation**

```rust
//! StudioTool helper: reduces Tool trait implementation boilerplate.
//!
//! Instead of writing a struct + impl Tool for each of the 9 meta-agent tools,
//! StudioTool accepts a name, description, JSON Schema, and an async closure.

use std::sync::Arc;
use futures::future::BoxFuture;
use llm_harness_types::{Tool, ToolContext, ToolFailure, ToolResult};
use serde_json::Value;

type ToolFn = Box<
    dyn Fn(Value, Arc<ToolContext>) -> BoxFuture<'static, Result<ToolResult, ToolFailure>>
        + Send
        + Sync,
>;

pub struct StudioTool {
    name: String,
    description: String,
    schema: Value,
    handler: ToolFn,
}

impl StudioTool {
    pub fn new(
        name: impl Into<String>,
        description: impl Into<String>,
        schema: Value,
        handler: ToolFn,
    ) -> Self {
        Self {
            name: name.into(),
            description: description.into(),
            schema,
            handler,
        }
    }
}

impl Tool for StudioTool {
    fn name(&self) -> &str {
        &self.name
    }

    fn description(&self) -> &str {
        &self.description
    }

    fn parameters_schema(&self) -> &Value {
        &self.schema
    }

    fn execute<'a>(
        &'a self,
        args: Value,
        ctx: &'a ToolContext,
    ) -> BoxFuture<'a, Result<ToolResult, ToolFailure>> {
        let handler = &self.handler;
        // ToolContext is 'a, but handler expects Arc<ToolContext>.
        // We wrap it in Arc for the duration of the call.
        // SAFETY: The Arc is valid for the lifetime of this future.
        let ctx_arc = unsafe { Arc::from_raw(ctx as *const ToolContext) };
        // Actually, we can't do this safely. Let me reconsider.
        // The Tool trait gives us &ToolContext, not Arc<ToolContext>.
        // We need to change the handler signature to accept &ToolContext.
        Box::pin(async move {
            // We can't safely create Arc from a reference.
            // Let's change the approach: handler takes &ToolContext.
            // But Box<dyn Fn(Value, &ToolContext)> is not object-safe due to lifetime.
            // Solution: use a concrete handler type per tool, not a generic closure.
            // For StudioTool, we'll store the handler as accepting &ToolContext
            // by erasing the lifetime.
            handler(args, ctx_arc).await
        })
    }
}
```

Wait — the `Tool::execute` signature provides `&'a ToolContext`, but our closure wants `Arc<ToolContext>`. This mismatch means `StudioTool` can't use `Arc<ToolContext>` in the handler. Let me fix the design:

The correct approach is to have the handler accept `&ToolContext`:

```rust
type ToolFn = Box<
    dyn for<'a> Fn(Value, &'a ToolContext) -> BoxFuture<'a, Result<ToolResult, ToolFailure>>
        + Send
        + Sync,
>;
```

But this requires HRTB (higher-ranked trait bounds), which works but is awkward. A simpler approach: each tool is a concrete struct with the data it needs (project_dir, etc.) and implements `Tool` directly. The `StudioTool` helper is less generic but still reduces boilerplate by providing a builder pattern.

Let me redesign `StudioTool` to use a simpler approach that matches the actual `Tool` trait:

```rust
//! StudioTool helper: reduces Tool trait implementation boilerplate.
//!
//! Each StudioTool holds:
//! - name, description, JSON Schema (static data)
//! - a reference to shared state (e.g., project dir, spec)
//! - a handler function that receives args + shared state
//!
//! The handler receives a `ToolInvocation` struct that contains the args
//! and a reference to the tool's state, avoiding the ToolContext lifetime issue.

use std::sync::Arc;
use futures::future::BoxFuture;
use llm_harness_types::{Tool, ToolContext, ToolFailure, ToolResult};
use serde_json::Value;

/// Context passed to a StudioTool handler.
/// Contains the tool arguments and a reference to the ToolContext.
pub struct ToolInvocation<'a> {
    pub args: Value,
    pub ctx: &'a ToolContext,
}

impl<'a> ToolInvocation<'a> {
    pub fn new(args: Value, ctx: &'a ToolContext) -> Self {
        Self { args, ctx }
    }
}

/// A tool handler function type.
pub type ToolHandler = Box<
    dyn for<'a> Fn(ToolInvocation<'a>) -> BoxFuture<'a, Result<ToolResult, ToolFailure>>
        + Send
        + Sync,
>;

/// A tool built from a name, description, schema, and async handler.
pub struct StudioTool {
    name: String,
    description: String,
    schema: Value,
    handler: ToolHandler,
}

impl StudioTool {
    pub fn new(
        name: impl Into<String>,
        description: impl Into<String>,
        schema: Value,
        handler: ToolHandler,
    ) -> Self {
        Self {
            name: name.into(),
            description: description.into(),
            schema,
            handler,
        }
    }
}

impl Tool for StudioTool {
    fn name(&self) -> &str {
        &self.name
    }

    fn description(&self) -> &str {
        &self.description
    }

    fn parameters_schema(&self) -> &Value {
        &self.schema
    }

    fn execute<'a>(
        &'a self,
        args: Value,
        ctx: &'a ToolContext,
    ) -> BoxFuture<'a, Result<ToolResult, ToolFailure>> {
        let invocation = ToolInvocation::new(args, ctx);
        (self.handler)(invocation)
    }
}
```

This is the correct design. The HRTB `for<'a> Fn(ToolInvocation<'a>) -> BoxFuture<'a, ...>` ensures the handler works for any lifetime of `ToolContext`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --lib studio_tool`
Expected: PASS (name/description/schema test; the execute test needs ToolContext which we skip)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add StudioTool helper for Tool trait boilerplate reduction"
```

---

### Task 2: Diff Rule Engine (diff_engine.rs)

**Files:**
- Create: `crates/studio-core/src/agents/diff_engine.rs`

**Interfaces:**
- Produces: `compute_affected_files(diff: &SpecDiff, spec: &Spec) -> Vec<String>`

**Design doc reference:** §4.4 模式 2 受影响文件判定

- [ ] **Step 1: Write the failing tests**

```rust
// In diff_engine.rs

#[cfg(test)]
mod tests {
    use super::*;
    use crate::spec::*;

    fn make_spec() -> Spec {
        Spec {
            agent_type: AgentType::SingleWithTools,
            name: "test".into(),
            description: "test".into(),
            model: "gpt-4o".into(),
            system_prompt: "You are helpful.".into(),
            max_tokens: 4096,
            budget: Some(BudgetSpec { max_cost: 0.10 }),
            tools: vec![ToolSpec {
                name: "search".into(),
                description: "Search".into(),
                parameters: serde_json::json!({}),
                implementation: "TODO: stub".into(),
            }],
            workflow: None,
            deploy: DeployMode::Cli,
            provider: ProviderSpec::default(),
        }
    }

    #[test]
    fn test_system_prompt_change_affects_main_py() {
        let spec = make_spec();
        let diff = SpecDiff {
            ops: vec![SpecDiffOp {
                op: "replace".into(),
                path: "/system_prompt".into(),
                value: Some(serde_json::json!("New prompt")),
            }],
        };
        let files = compute_affected_files(&diff, &spec);
        assert!(files.contains(&"main.py".to_string()));
    }

    #[test]
    fn test_tools_change_affects_tools_and_main() {
        let spec = make_spec();
        let diff = SpecDiff {
            ops: vec![SpecDiffOp {
                op: "add".into(),
                path: "/tools/1".into(),
                value: Some(serde_json::json!({"name": "calc", "description": "Calculator", "parameters": {}, "implementation": "TODO: stub"})),
            }],
        };
        let files = compute_affected_files(&diff, &spec);
        assert!(files.contains(&"tools.py".to_string()));
        assert!(files.contains(&"main.py".to_string()));
    }

    #[test]
    fn test_model_change_affects_main_py() {
        let spec = make_spec();
        let diff = SpecDiff {
            ops: vec![SpecDiffOp {
                op: "replace".into(),
                path: "/model".into(),
                value: Some(serde_json::json!("claude-3-5-sonnet")),
            }],
        };
        let files = compute_affected_files(&diff, &spec);
        assert!(files.contains(&"main.py".to_string()));
    }

    #[test]
    fn test_deploy_change_creates_or_deletes_server_py() {
        let spec = make_spec();
        let diff = SpecDiff {
            ops: vec![SpecDiffOp {
                op: "replace".into(),
                path: "/deploy".into(),
                value: Some(serde_json::json!("api")),
            }],
        };
        let files = compute_affected_files(&diff, &spec);
        assert!(files.contains(&"main.py".to_string()));
        assert!(files.contains(&"server.py".to_string()));
    }

    #[test]
    fn test_workflow_steps_change_affects_workflow_and_main() {
        let mut spec = make_spec();
        spec.agent_type = AgentType::LinearWorkflow;
        spec.workflow = Some(WorkflowSpec {
            entry_step: "s1".into(),
            steps: vec![
                WorkflowStep { id: "s1".into(), name: "S1".into(), prompt: "Do 1".into(), allowed_tools: vec![] },
                WorkflowStep { id: "s2".into(), name: "S2".into(), prompt: "Do 2".into(), allowed_tools: vec![] },
            ],
            edges: vec![WorkflowEdge { from: "s1".into(), to: "s2".into(), condition: None }],
            judge: JudgeSpec { strategy: "linear".into() },
        });
        let diff = SpecDiff {
            ops: vec![SpecDiffOp {
                op: "replace".into(),
                path: "/workflow/steps/0/prompt".into(),
                value: Some(serde_json::json!("New prompt")),
            }],
        };
        let files = compute_affected_files(&diff, &spec);
        assert!(files.contains(&"workflow.py".to_string()));
        assert!(files.contains(&"main.py".to_string()));
    }

    #[test]
    fn test_workflow_edges_change_affects_only_workflow() {
        let mut spec = make_spec();
        spec.agent_type = AgentType::LinearWorkflow;
        spec.workflow = Some(WorkflowSpec {
            entry_step: "s1".into(),
            steps: vec![
                WorkflowStep { id: "s1".into(), name: "S1".into(), prompt: "Do 1".into(), allowed_tools: vec![] },
                WorkflowStep { id: "s2".into(), name: "S2".into(), prompt: "Do 2".into(), allowed_tools: vec![] },
            ],
            edges: vec![WorkflowEdge { from: "s1".into(), to: "s2".into(), condition: None }],
            judge: JudgeSpec { strategy: "linear".into() },
        });
        let diff = SpecDiff {
            ops: vec![SpecDiffOp {
                op: "add".into(),
                path: "/workflow/edges/1".into(),
                value: Some(serde_json::json!({"from": "s1", "to": "s3"})),
            }],
        };
        let files = compute_affected_files(&diff, &spec);
        assert!(files.contains(&"workflow.py".to_string()));
        // main.py is NOT affected by edge-only changes
        assert!(!files.contains(&"main.py".to_string()));
    }

    #[test]
    fn test_api_deploy_includes_server_py() {
        let mut spec = make_spec();
        spec.deploy = DeployMode::Api;
        let diff = SpecDiff {
            ops: vec![SpecDiffOp {
                op: "replace".into(),
                path: "/system_prompt".into(),
                value: Some(serde_json::json!("New")),
            }],
        };
        let files = compute_affected_files(&diff, &spec);
        // When deploy=api and system_prompt changes, server.py is also affected
        assert!(files.contains(&"server.py".to_string()));
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --lib diff_engine`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```rust
//! Diff rule engine: maps spec diff paths to affected files.
//!
//! This is deterministic (no LLM). The coding agent only modifies
//! files in the returned set.

use std::collections::HashSet;

use crate::spec::{DeployMode, Spec, SpecDiff};

/// Compute the set of files affected by a spec diff.
///
/// Rules (from design doc §4.4):
/// | spec diff path           | affected files                          |
/// |--------------------------|-----------------------------------------|
/// | /system_prompt           | main.py (+ server.py if deploy=api)     |
/// | /model                   | main.py (+ server.py if deploy=api)     |
/// | /max_tokens              | main.py (+ server.py if deploy=api)     |
/// | /budget                  | main.py (+ server.py if deploy=api)     |
/// | /tools/*                 | tools.py + main.py (+ server.py if api) |
/// | /provider                | main.py (+ server.py if deploy=api)     |
/// | /workflow/steps/*        | workflow.py + main.py (+ server.py)     |
/// | /workflow/edges/*        | workflow.py                              |
/// | /workflow/judge          | main.py (+ server.py if deploy=api)     |
/// | /deploy                  | main.py + create/delete server.py       |
pub fn compute_affected_files(diff: &SpecDiff, spec: &Spec) -> Vec<String> {
    let mut files: HashSet<String> = HashSet::new();
    let has_server = spec.deploy == DeployMode::Api;

    for op in &diff.ops {
        let path = &op.path;

        if path == "/deploy" {
            // Deploy change: always main.py + server.py
            files.insert("main.py".into());
            files.insert("server.py".into());
            continue;
        }

        // Check if deploy is being changed TO api in this diff
        let will_have_server = if path == "/deploy" {
            op.value
                .as_ref()
                .and_then(|v| v.as_str())
                .map(|s| s == "api")
                .unwrap_or(has_server)
        } else {
            has_server
        };

        let add_server = |files: &mut HashSet<String>| {
            if will_have_server {
                files.insert("server.py".into());
            }
        };

        match path.as_str() {
            "/system_prompt" | "/model" | "/max_tokens" | "/budget" | "/provider" => {
                files.insert("main.py".into());
                add_server(&mut files);
            }
            p if p.starts_with("/tools") => {
                files.insert("tools.py".into());
                files.insert("main.py".into());
                add_server(&mut files);
            }
            p if p.starts_with("/workflow/steps") => {
                files.insert("workflow.py".into());
                files.insert("main.py".into());
                add_server(&mut files);
            }
            p if p.starts_with("/workflow/edges") => {
                files.insert("workflow.py".into());
                // edges only — main.py not affected
            }
            "/workflow/judge" => {
                files.insert("main.py".into());
                add_server(&mut files);
            }
            _ => {
                // Unknown path — be conservative, include main.py
                files.insert("main.py".into());
                add_server(&mut files);
            }
        }
    }

    let mut result: Vec<String> = files.into_iter().collect();
    result.sort();
    result
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --lib diff_engine`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add diff rule engine for spec → affected file mapping"
```

---

### Task 3: Converser Agent (converser.rs)

**Files:**
- Create: `crates/studio-core/src/agents/converser.rs`

**Interfaces:**
- Produces: `build_converser(api_key, model, base_url, project_dir) -> AgentHarness`
- Consumes: `StudioTool` from Task 1, `Spec`/`SpecDiff` from Plan 1, `ProjectManager` from Plan 1

**Design doc reference:** §4.1 对话 Agent

- [ ] **Step 1: Write the test (LLM, `#[ignore]`)**

```rust
// In converser.rs

#[cfg(test)]
mod tests {
    use super::*;
    use crate::project::ProjectManager;

    // This test requires a real LLM API key.
    // Run with: cargo test -- --ignored converser
    #[tokio::test]
    #[ignore]
    async fn test_converser_emits_spec_for_simple_request() {
        let api_key = std::env::var("STUDIO_API_KEY").expect("STUDIO_API_KEY required");
        let model = std::env::var("STUDIO_MODEL").unwrap_or("gpt-4o".into());
        let base_url = std::env::var("STUDIO_BASE_URL").ok();

        let tmp = tempfile::TempDir::new().unwrap();
        let mgr = ProjectManager::new(tmp.path().to_path_buf());
        let project = mgr.create_project("test-converser").unwrap();

        let harness = build_converser(
            &api_key,
            &model,
            base_url.as_deref(),
            &project.dir,
        )
        .await
        .unwrap();

        // Send a simple user message
        harness
            .prompt("我想做一个简单的聊天助手，用 gpt-4o，系统提示是'你是一个友好的助手'。不需要工具，终端运行就行。")
            .await
            .unwrap();

        // Collect events
        let events = harness.prompt_and_collect("__trigger__", 60000).await;

        // The agent should have called emit_spec tool.
        // Check if spec.json was written to the project.
        let spec_path = project.dir.join(".studio/specs/current.json");
        assert!(
            spec_path.exists(),
            "emit_spec should have written spec.json"
        );

        let spec_content = std::fs::read_to_string(&spec_path).unwrap();
        let spec: crate::spec::Spec = serde_json::from_str(&spec_content).unwrap();
        assert!(spec.validate().is_ok(), "emitted spec should be valid");
        assert_eq!(spec.agent_type, crate::spec::AgentType::Single);
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test -- --ignored converser`
Expected: FAIL — `build_converser` not defined (or timeout if LLM not available)

- [ ] **Step 3: Write minimal implementation**

```rust
//! Converser agent: multi-turn dialogue → structured spec JSON.
//!
//! The Converser has 4 tools:
//! - emit_spec(spec_json): output full spec, terminate conversation
//! - emit_spec_diff(diff_json): output incremental spec diff
//! - read_project(path): read current project files
//! - read_current_spec(): read current spec.json

use std::path::{Path, PathBuf};
use std::sync::Arc;

use llm_harness_agent::AgentHarness;
use llm_harness_loop::{LlmClient, OpenAIProvider};
use llm_harness_runtime::builder::HarnessBuilder;
use llm_harness_runtime_sandbox_os::OsEnv;
use llm_harness_types::{DataBlock, Tool, ToolResult};

use crate::error::StudioResult;
use crate::spec::{Spec, SpecDiff};

/// System prompt for the Converser agent (§4.1).
const SYSTEM_PROMPT: &str = include_str!("converser_system_prompt.txt");

/// Build the Converser agent harness.
pub async fn build_converser(
    api_key: &str,
    model: &str,
    base_url: Option<&str>,
    project_dir: &Path,
) -> StudioResult<AgentHarness> {
    let mut provider_builder = OpenAIProvider::builder(api_key);
    if let Some(url) = base_url {
        provider_builder = provider_builder.base_url(url);
    }
    let client: Arc<dyn LlmClient> = Arc::new(provider_builder.build());

    let project_dir = Arc::new(project_dir.to_path_buf());

    // Tool: emit_spec
    let emit_spec_dir = project_dir.clone();
    let emit_spec = crate::agents::studio_tool::StudioTool::new(
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
                    .map_err(|e| llm_harness_types::ToolFailure::invalid_arguments(e.to_string()))?;
                spec.validate()
                    .map_err(|e| llm_harness_types::ToolFailure::invalid_arguments(e.to_string()))?;

                // Write spec to .studio/specs/current.json
                let spec_dir = dir.join(".studio/specs");
                std::fs::create_dir_all(&spec_dir).ok();
                let json = serde_json::to_string_pretty(&spec).unwrap_or_default();
                std::fs::write(spec_dir.join("current.json"), &json).ok();

                // Also save timestamped snapshot
                let ts = chrono::Utc::now().format("%Y%m%dT%H%M%S");
                std::fs::write(spec_dir.join(format!("{ts}.json")), &json).ok();

                Ok(ToolResult::full(
                    vec![DataBlock::text(format!("Spec saved. Agent type: {:?}, name: {}", spec.agent_type, spec.name))],
                    serde_json::json!({"spec_saved": true, "agent_type": format!("{:?}", spec.agent_type)}),
                    true, // terminate — spec emission ends the conversation
                ))
            })
        }),
    );

    // Tool: emit_spec_diff
    let diff_dir = project_dir.clone();
    let emit_spec_diff = crate::agents::studio_tool::StudioTool::new(
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
                    .map_err(|e| llm_harness_types::ToolFailure::invalid_arguments(format!("diff parse error: {e}")))?;

                // Write diff to .studio/specs/pending_diff.json
                let spec_dir = dir.join(".studio/specs");
                std::fs::create_dir_all(&spec_dir).ok();
                let json = serde_json::to_string_pretty(&diff).unwrap_or_default();
                std::fs::write(spec_dir.join("pending_diff.json"), &json).ok();

                Ok(ToolResult::full(
                    vec![DataBlock::text(format!("Spec diff saved with {} ops.", diff.ops.len()))],
                    serde_json::json!({"diff_saved": true, "ops_count": diff.ops.len()}),
                    true, // terminate
                ))
            })
        }),
    );

    // Tool: read_project
    let read_project_dir = project_dir.clone();
    let read_project = crate::agents::studio_tool::StudioTool::new(
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

                // Security: prevent path traversal
                let canonical_base = dir.canonicalize().unwrap_or_else(|_| dir.clone());
                let canonical_file = full_path.canonicalize().map_err(|_| {
                    llm_harness_types::ToolFailure::invalid_arguments(format!("file not found: {path}"))
                })?;
                if !canonical_file.starts_with(&canonical_base) {
                    return Err(llm_harness_types::ToolFailure::invalid_arguments("path traversal blocked"));
                }

                let content = std::fs::read_to_string(&full_path)
                    .map_err(|e| llm_harness_types::ToolFailure::invalid_arguments(format!("read error: {e}")))?;

                Ok(ToolResult::full(
                    vec![DataBlock::text(content)],
                    serde_json::json!({"path": path, "size": content.len()}),
                    false,
                ))
            })
        }),
    );

    // Tool: read_current_spec
    let read_spec_dir = project_dir.clone();
    let read_current_spec = crate::agents::studio_tool::StudioTool::new(
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

    let env = Arc::new(OsEnv::new(project_dir.as_ref().clone()));

    let harness = HarnessBuilder::new(model)
        .provider("*", client)
        .system_prompt(Some(SYSTEM_PROMPT.into()))
        .max_tokens(8192)
        .auto_compact(true)
        .tool(Arc::new(emit_spec) as Arc<dyn Tool>)
        .tool(Arc::new(emit_spec_diff) as Arc<dyn Tool>)
        .tool(Arc::new(read_project) as Arc<dyn Tool>)
        .tool(Arc::new(read_current_spec) as Arc<dyn Tool>)
        .build(env)
        .await
        .map_err(|e| crate::error::StudioError::Agent(format!("converser build failed: {e}")))?;

    Ok(harness)
}
```

- [ ] **Step 4: Create the system prompt file**

Create `crates/studio-core/src/agents/converser_system_prompt.txt` with the full system prompt from design doc §4.1 (the full text starting with "你是 Senza Studio 的助手..." through the "信息充分" criteria table).

Copy the full system prompt text from the design document §4.1 (lines 341-441 of design.md).

- [ ] **Step 5: Run test to verify it passes**

Run: `cargo test -- --ignored converser`
Expected: PASS (requires `STUDIO_API_KEY` env var + Python + senza installed)

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: add Converser agent with 4 tools and system prompt"
```

---

### Task 4: Senza Coding Agent (coding_agent.rs)

**Files:**
- Create: `crates/studio-core/src/agents/coding_agent.rs`

**Interfaces:**
- Produces: `build_coding_agent(api_key, model, base_url, project_dir, allowed_files) -> AgentHarness`
- Consumes: `StudioTool` from Task 1, `Spec` from Plan 1

**Design doc reference:** §4.2 Senza Coding Agent

- [ ] **Step 1: Write the test (LLM, `#[ignore]`)**

```rust
// In coding_agent.rs

#[cfg(test)]
mod tests {
    use super::*;
    use crate::project::ProjectManager;
    use crate::spec::*;

    #[tokio::test]
    #[ignore]
    async fn test_coding_agent_generates_valid_python() {
        let api_key = std::env::var("STUDIO_API_KEY").expect("STUDIO_API_KEY required");
        let model = std::env::var("STUDIO_MODEL").unwrap_or("gpt-4o".into());
        let base_url = std::env::var("STUDIO_BASE_URL").ok();

        let tmp = tempfile::TempDir::new().unwrap();
        let mgr = ProjectManager::new(tmp.path().to_path_buf());
        let project = mgr.create_project("test-coding").unwrap();

        // Save a spec for the coding agent to read
        let spec = Spec {
            agent_type: AgentType::Single,
            name: "chat-bot".into(),
            description: "A simple chat bot".into(),
            model: "gpt-4o".into(),
            system_prompt: "You are a helpful assistant.".into(),
            max_tokens: 4096,
            budget: None,
            tools: vec![],
            workflow: None,
            deploy: DeployMode::Cli,
            provider: ProviderSpec::default(),
        };
        mgr.save_spec(&project.id, &spec).unwrap();

        let harness = build_coding_agent(
            &api_key,
            &model,
            base_url.as_deref(),
            &project.dir,
            None, // no file restrictions
        )
        .await
        .unwrap();

        // The coding agent reads spec and writes files
        harness
            .prompt("Read the spec and generate the project files. Write main.py with the Studio dual-mode runtime code.")
            .await
            .unwrap();

        // Verify main.py exists and is valid Python
        let main_py = project.dir.join("main.py");
        assert!(main_py.exists(), "main.py should be generated");

        let content = std::fs::read_to_string(&main_py).unwrap();
        assert!(content.contains("senza"), "main.py should import senza");
        assert!(content.contains("_emit"), "main.py should contain _emit function");
        assert!(content.contains("_get_input"), "main.py should contain _get_input function");

        // Verify Python syntax is valid
        let ast_check = std::process::Command::new("python3")
            .arg("-c")
            .arg(format!("import ast; ast.parse(open('{}').read())", main_py.display()))
            .output()
            .unwrap();
        assert!(ast_check.status.success(), "main.py should have valid Python syntax: {}",
            String::from_utf8_lossy(&ast_check.stderr));
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test -- --ignored coding_agent`
Expected: FAIL — `build_coding_agent` not defined

- [ ] **Step 3: Write minimal implementation**

```rust
//! Senza Coding Agent: spec JSON → Python project code.
//!
//! The coding agent has 5 tools:
//! - write_file(path, content): write a project file
//! - read_file(path): read a project file
//! - read_spec(): read the current spec JSON
//! - list_project_files(): list all files in the project
//! - ast_check(path): validate Python syntax

use std::path::{Path, PathBuf};
use std::sync::Arc;

use llm_harness_agent::AgentHarness;
use llm_harness_loop::{LlmClient, OpenAIProvider};
use llm_harness_runtime::builder::HarnessBuilder;
use llm_harness_runtime_sandbox_os::OsEnv;
use llm_harness_types::{DataBlock, Tool, ToolResult};

use crate::error::StudioResult;

/// System prompt for the Senza coding agent (§4.2).
/// Embeds Senza SKILL.md knowledge + Studio runtime integration instructions.
const SYSTEM_PROMPT: &str = include_str!("coding_agent_system_prompt.txt");

/// Build the Senza coding agent harness.
///
/// `allowed_files`: When `Some`, the write_file tool is restricted to only
/// these paths (used in incremental/diff mode). When `None`, all paths allowed.
pub async fn build_coding_agent(
    api_key: &str,
    model: &str,
    base_url: Option<&str>,
    project_dir: &Path,
    allowed_files: Option<Vec<String>>,
) -> StudioResult<AgentHarness> {
    let mut provider_builder = OpenAIProvider::builder(api_key);
    if let Some(url) = base_url {
        provider_builder = provider_builder.base_url(url);
    }
    let client: Arc<dyn LlmClient> = Arc::new(provider_builder.build());

    let project_dir = Arc::new(project_dir.to_path_buf());
    let allowed_files = Arc::new(allowed_files);

    // Tool: write_file
    let write_dir = project_dir.clone();
    let write_allowed = allowed_files.clone();
    let write_file = crate::agents::studio_tool::StudioTool::new(
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
            Box::pin(async move {
                let path = invocation.args.get("path")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                let content = invocation.args.get("content")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");

                // Check allowed files restriction
                if let Some(allowed_list) = allowed.as_ref() {
                    if !allowed_list.iter().any(|a| a == path) {
                        return Err(llm_harness_types::ToolFailure::invalid_arguments(
                            format!("File '{path}' is not in the allowed files list: {allowed_list:?}. You can only modify files in this list.")
                        ));
                    }
                }

                // Path traversal check
                let full_path = dir.join(path);
                let canonical_base = dir.canonicalize().unwrap_or_else(|_| dir.clone());
                if let Some(parent) = full_path.parent() {
                    std::fs::create_dir_all(parent).ok();
                }
                let canonical_file = full_path.canonicalize().map_err(|_| {
                    llm_harness_types::ToolFailure::invalid_arguments(format!("cannot resolve path: {path}"))
                })?;
                if !canonical_file.starts_with(&canonical_base) {
                    return Err(llm_harness_types::ToolFailure::invalid_arguments("path traversal blocked"));
                }

                std::fs::write(&full_path, content)
                    .map_err(|e| llm_harness_types::ToolFailure::execution_failed().clone())?;

                Ok(ToolResult::full(
                    vec![DataBlock::text(format!("Written {path} ({content.len()} bytes). Run ast_check to verify syntax."))],
                    serde_json::json!({"path": path, "bytes": content.len()}),
                    false,
                ))
            })
        }),
    );

    // Tool: read_file
    let read_dir = project_dir.clone();
    let read_file = crate::agents::studio_tool::StudioTool::new(
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
                let canonical_base = dir.canonicalize().unwrap_or_else(|_| dir.clone());
                let canonical_file = full_path.canonicalize().map_err(|_| {
                    llm_harness_types::ToolFailure::invalid_arguments(format!("file not found: {path}"))
                })?;
                if !canonical_file.starts_with(&canonical_base) {
                    return Err(llm_harness_types::ToolFailure::invalid_arguments("path traversal blocked"));
                }
                let content = std::fs::read_to_string(&full_path)
                    .map_err(|e| llm_harness_types::ToolFailure::invalid_arguments(format!("read error: {e}")))?;
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
    let read_spec = crate::agents::studio_tool::StudioTool::new(
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
    let list_project_files = crate::agents::studio_tool::StudioTool::new(
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
    let ast_check = crate::agents::studio_tool::StudioTool::new(
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
                    return Err(llm_harness_types::ToolFailure::invalid_arguments(format!("file not found: {path}")));
                }
                let output = std::process::Command::new("python3")
                    .arg("-c")
                    .arg(format!("import ast; ast.parse(open('{}').read())", full_path.display()))
                    .output()
                    .map_err(|e| llm_harness_types::ToolFailure::execution_failed().clone())?;

                if output.status.success() {
                    Ok(ToolResult::full(
                        vec![DataBlock::text(format!("✓ {path}: syntax OK"))],
                        serde_json::json!({"path": path, "valid": true}),
                        false,
                    ))
                } else {
                    let stderr = String::from_utf8_lossy(&output.stderr);
                    Err(llm_harness_types::ToolFailure::new("syntax_error", format!("Python syntax error in {path}:\n{stderr}")))
                }
            })
        }),
    );

    let env = Arc::new(OsEnv::new(project_dir.as_ref().clone()));

    let harness = HarnessBuilder::new(model)
        .provider("*", client)
        .system_prompt(Some(SYSTEM_PROMPT.into()))
        .max_tokens(8192)
        .auto_compact(true)
        .tool(Arc::new(write_file) as Arc<dyn Tool>)
        .tool(Arc::new(read_file) as Arc<dyn Tool>)
        .tool(Arc::new(read_spec) as Arc<dyn Tool>)
        .tool(Arc::new(list_project_files) as Arc<dyn Tool>)
        .tool(Arc::new(ast_check) as Arc<dyn Tool>)
        .build(env)
        .await
        .map_err(|e| crate::error::StudioError::Agent(format!("coding agent build failed: {e}")))?;

    Ok(harness)
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
```

- [ ] **Step 4: Create the system prompt file**

Create `crates/studio-core/src/agents/coding_agent_system_prompt.txt` with the full system prompt from design doc §4.2 (lines 463-494 of design.md), preceded by the full content of the three Senza SKILL.md files:

```
你是一个 Senza 专家 coding agent，负责根据意图描述（spec JSON）写/改 Senza Python 项目代码。

## Senza API 参考

（以下内嵌 senza-agent SKILL.md + senza-workflow SKILL.md + senza-advanced SKILL.md 的完整内容）

--- senza-agent SKILL.md ---
[full content of Senza/skills/senza-agent/SKILL.md]

--- senza-workflow SKILL.md ---
[full content of Senza/skills/senza-workflow/SKILL.md]

--- senza-advanced SKILL.md ---
[full content of Senza/skills/senza-advanced/SKILL.md]

## Studio 运行时接入

生成的 main.py 必须支持双模式运行（Studio 模式 + 独立模式）。Studio 模式通过环境变量 SENZA_STUDIO_RUN_ID 检测。**single agent 和 workflow agent 的交互模型完全不同**：

- 事件输出：Studio 模式下通过 fd 3 帧协议输出事件（长度前缀 + JSON），独立模式不输出
- 用户输入：Studio 模式下从 stdin 读取，独立模式用 input()
- trace 文件：SENZA_STUDIO_TRACE_DIR 存在时写 events.jsonl
- **single agent**（AgentHarness）：多轮对话模型。Studio 模式用 `senza.stream_prompt(harness, text)` async generator，独立模式用双线程 `events()`+`prompt()`。`prompt()` 自动追加到 session，保持多轮上下文。SDK 的 `auto_compact` 机制处理长对话的 token 压缩
- **workflow agent**（WorkflowEngine）：一次性任务提交模型。Studio 模式用 `senza.stream_run(engine)` async generator（启动 `engine.run()` 并 yield workflow 事件），独立模式用双线程 `subscribe()`+`run()`。用户输入通过 `engine.set_context_variable()` 注入。pause 时从 stdin 读取后 `engine.resume()`

## 你的工具

- write_file(path, content) — 写项目文件
- read_file(path) — 读项目文件
- read_spec() — 读当前 spec JSON
- list_project_files() — 列出项目文件
- ast_check(path) — 用 python -c "import ast; ast.parse(open(path).read())" 验证语法

## 行为约束

- 拿到 spec 后，先 read_spec() 理解意图，再决定文件结构
- 每个 write_file 后调用 ast_check 验证语法
- Studio 运行时接入代码（_emit / _get_input / _run_studio / _run_standalone / _run_studio_workflow / _run_standalone_workflow）是固定的——参考 §4.2 标准运行时接入代码。**必须根据 agent_type 选择正确的运行函数**
- 如果 spec.deploy == "api"，额外生成 server.py（FastAPI + 极简 chat 网页），把 agent 包成 HTTP API。server.py 复用 main.py 中的 harness 构建逻辑，不重复定义
- 如果是增量修改（spec diff），只在规则引擎指定的受影响文件内修改，不碰其他文件
```

The implementer should embed the actual SKILL.md content by reading the files from the Senza repo during implementation. The system prompt file should be created by concatenating:
1. The coding agent instructions (from design.md §4.2 lines 463-494)
2. The full content of `Senza/skills/senza-agent/SKILL.md`
3. The full content of `Senza/skills/senza-workflow/SKILL.md`
4. The full content of `Senza/skills/senza-advanced/SKILL.md`
5. The standard runtime integration code (from design.md §4.2 lines 520-690)

- [ ] **Step 5: Run test to verify it passes**

Run: `cargo test -- --ignored coding_agent`
Expected: PASS (requires `STUDIO_API_KEY` env var + Python + senza installed)

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: add Senza coding agent with 5 tools and SKILL.md-embedded system prompt"
```

---

### Task 5: Agents Module Root (mod.rs)

**Files:**
- Create: `crates/studio-core/src/agents/mod.rs`

- [ ] **Step 1: Write mod.rs**

```rust
//! Meta-agent layer: 2 AgentHarness instances (Converser + Coding Agent).
//!
//! These are the "meta agents" that help users build Senza projects.
//! They are NOT the user's agents — those run as Python subprocesses.

pub mod coding_agent;
pub mod converser;
pub mod diff_engine;
pub mod studio_tool;

pub use coding_agent::build_coding_agent;
pub use converser::build_converser;
pub use diff_engine::compute_affected_files;
pub use studio_tool::StudioTool;
```

- [ ] **Step 2: Verify compilation**

Run: `cargo check`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat: add agents module root"
```

---

### Task 6: Verify All Tests Pass

- [ ] **Step 1: Run deterministic tests**

Run: `cargo test`
Expected: All non-`#[ignore]` tests pass (studio_tool, diff_engine)

- [ ] **Step 2: Run LLM tests (if API key available)**

Run: `cargo test -- --ignored`
Expected: Converser + coding agent tests pass (requires `STUDIO_API_KEY`)

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: verify meta-agent tests pass"
```
