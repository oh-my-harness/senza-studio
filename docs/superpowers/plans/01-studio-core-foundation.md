# Plan 1: Studio Core Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the Cargo workspace, `studio-core` crate with spec/project/error data types, and the examples library directory structure.

**Architecture:** A new standalone repo `senza-studio/` with a Cargo workspace containing `studio-core` (business logic, no web deps) and `studio-server` (added in Plan 4). `studio-core` depends on `llm-harness-runtime`, `llm-harness-agent`, `llm-harness-types`, and `llm-harness-loop` via relative path. This plan covers workspace setup + spec.rs + project.rs + error.rs + examples/ scaffolding.

**Tech Stack:** Rust 2024, serde, serde_json, thiserror, tempfile (for tests), `llm-harness-runtime` crates.

## Global Constraints

(See `00-overview.md`)

---

## File Structure

```
senza-studio/
├── Cargo.toml                          # workspace root
├── crates/
│   └── studio-core/
│       ├── Cargo.toml
│       ├── src/
│       │   ├── lib.rs                  # crate root, re-exports
│       │   ├── spec.rs                 # Spec data structures + validation + DeployMode
│       │   ├── project.rs              # ProjectManager: FS CRUD for project dirs
│       │   ├── error.rs                # StudioError enum
│       │   └── examples/               # Built-in example projects (embedded with include_str! or read from dir)
│       │       ├── mod.rs              # Example registry
│       │       ├── basic_chat/         # Converted from Senza example 01_basic_prompt
│       │       ├── tool_calling/       # Converted from 02_tool_calling
│       │       ├── streaming/          # Converted from 03_streaming
│       │       ├── budget_controlled/  # Converted from 08_budget_pricing
│       │       ├── linear_pipeline/    # Converted from runtime/01_linear_workflow
│       │       ├── conditional_routing/# Converted from runtime/02_conditional_routing
│       │       ├── crash_recovery/     # Converted from runtime/04_crash_recovery (reference only)
│       │       └── human_in_loop/      # Converted from runtime/06_human_in_the_loop
├── docs/
│   └── design.md                       # Already exists
└── README.md
```

---

### Task 1: Scaffold Cargo Workspace

**Files:**
- Create: `Cargo.toml` (workspace root)
- Create: `crates/studio-core/Cargo.toml`
- Create: `crates/studio-core/src/lib.rs`
- Create: `README.md`

**Interfaces:**
- Produces: workspace with `studio-core` member crate

- [ ] **Step 1: Create workspace Cargo.toml**

```toml
[workspace]
members = [
    "crates/studio-core",
]
resolver = "2"

[workspace.package]
edition = "2024"
version = "0.1.0"
license = "MIT"

[workspace.dependencies]
# Runtime crates (sibling repo, relative path)
llm-harness-types   = { path = "../../llm-harness-runtime/crates/llm-harness-types" }
llm-harness-loop    = { path = "../../llm-harness-runtime/crates/llm-harness-loop" }
llm-harness-agent   = { path = "../../llm-harness-runtime/crates/llm-harness-agent" }
llm-harness-runtime = { path = "../../llm-harness-runtime/crates/llm-harness-runtime" }
llm-harness-runtime-sandbox-os = { path = "../../llm-harness-runtime/crates/llm-harness-runtime-sandbox-os" }

# Third-party
anyhow      = "1"
async-trait = "0.1"
chrono      = { version = "0.4", features = ["serde"] }
futures     = "0.3"
serde       = { version = "1", features = ["derive"] }
serde_json  = "1"
thiserror   = "2"
tokio       = { version = "1", features = ["full"] }
uuid        = { version = "1", features = ["v4", "v7"] }
tempfile    = "3"
tracing     = "0.1"
```

- [ ] **Step 2: Create studio-core Cargo.toml**

```toml
[package]
name = "studio-core"
edition.workspace = true
version.workspace = true
license.workspace = true

[dependencies]
llm-harness-types   = { workspace = true }
llm-harness-loop    = { workspace = true }
llm-harness-agent   = { workspace = true }
llm-harness-runtime = { workspace = true }
llm-harness-runtime-sandbox-os = { workspace = true }
anyhow      = { workspace = true }
async-trait = { workspace = true }
chrono      = { workspace = true }
futures     = { workspace = true }
serde       = { workspace = true }
serde_json  = { workspace = true }
thiserror   = { workspace = true }
tokio       = { workspace = true }
uuid        = { workspace = true }
tracing     = { workspace = true }

[dev-dependencies]
tempfile = { workspace = true }
```

- [ ] **Step 3: Create lib.rs**

```rust
//! studio-core — Core business logic for Senza Studio.
//!
//! No web dependencies. Contains:
//! - Spec data structures and validation
//! - Project management (filesystem CRUD)
//! - Meta-agent definitions (Converser + Coding Agent)
//! - Python subprocess runner with fd 3 frame protocol
//! - Built-in example library

pub mod error;
pub mod project;
pub mod spec;
pub mod examples;
```

- [ ] **Step 4: Create README.md**

```markdown
# Senza Studio

A web application that helps developers customize AI agents via natural-language conversation, an example library, or direct code editing.

## Architecture

See `docs/design.md` for the full v5.3 design document.

## Development

```bash
# Build
cargo build

# Test (deterministic, no LLM)
cargo test

# Test (with real LLM calls, requires API keys)
cargo test -- --ignored
```
```

- [ ] **Step 5: Verify workspace compiles**

Run: `cargo check`
Expected: PASS (no errors, empty crate with just module declarations will fail until modules exist — create stubs first)

- [ ] **Step 6: Commit**

```bash
git init
git add -A
git commit -m "feat: scaffold Cargo workspace with studio-core crate"
```

---

### Task 2: Error Types (error.rs)

**Files:**
- Create: `crates/studio-core/src/error.rs`
- Test: `crates/studio-core/src/error.rs` (inline tests)

**Interfaces:**
- Produces: `StudioError` enum used by all studio-core modules

- [ ] **Step 1: Write the failing test**

```rust
// In error.rs

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_spec_validation_error_display() {
        let err = StudioError::SpecValidation("missing agent_type".into());
        assert!(err.to_string().contains("missing agent_type"));
    }

    #[test]
    fn test_project_not_found_display() {
        let err = StudioError::ProjectNotFound("proj-123".into());
        assert!(err.to_string().contains("proj-123"));
    }

    #[test]
    fn test_path_traversal_blocked() {
        let err = StudioError::PathTraversalBlocked("../etc/passwd".into());
        assert!(err.to_string().contains("../etc/passwd"));
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --lib error`
Expected: FAIL — `StudioError` not defined

- [ ] **Step 3: Write minimal implementation**

```rust
use thiserror::Error;

/// All errors produced by studio-core.
#[derive(Error, Debug)]
pub enum StudioError {
    #[error("spec validation failed: {0}")]
    SpecValidation(String),

    #[error("project not found: {0}")]
    ProjectNotFound(String),

    #[error("file not found in project: {0}")]
    FileNotFound(String),

    #[error("path traversal blocked: {0}")]
    PathTraversalBlocked(String),

    #[error("run not found: {0}")]
    RunNotFound(String),

    #[error("run already active: {0}")]
    RunAlreadyActive(String),

    #[error("subprocess error: {0}")]
    Subprocess(String),

    #[error("frame protocol error: {0}")]
    FrameProtocol(String),

    #[error("agent error: {0}")]
    Agent(String),

    #[error("io error: {0}")]
    Io(#[from] std::io::Error),

    #[error("json error: {0}")]
    Json(#[from] serde_json::Error),
}

pub type StudioResult<T> = Result<T, StudioError>;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --lib error`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add StudioError types"
```

---

### Task 3: Spec Data Structures (spec.rs)

**Files:**
- Create: `crates/studio-core/src/spec.rs`
- Test: `crates/studio-core/src/spec.rs` (inline tests)

**Interfaces:**
- Produces: `Spec`, `AgentType`, `DeployMode`, `ToolSpec`, `WorkflowSpec`, `WorkflowStep`, `WorkflowEdge`, `EdgeCondition`, `JudgeSpec`, `BudgetSpec`, `ProviderSpec`, `SpecDiff`
- Consumes: `StudioError` from Task 2

**Design doc reference:** §3 spec.json, §4.1 spec JSON format, §4.2 implementation field, §4.4 diff format

- [ ] **Step 1: Write the failing tests**

```rust
// In spec.rs

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_valid_single_agent_spec() {
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
        assert!(spec.validate().is_ok());
    }

    #[test]
    fn test_single_with_tools_requires_at_least_one_tool() {
        let spec = Spec {
            agent_type: AgentType::SingleWithTools,
            name: "tool-bot".into(),
            description: "A bot with tools".into(),
            model: "gpt-4o".into(),
            system_prompt: "You help with tasks.".into(),
            max_tokens: 4096,
            budget: None,
            tools: vec![], // empty — should fail
            workflow: None,
            deploy: DeployMode::Cli,
            provider: ProviderSpec::default(),
        };
        let err = spec.validate().unwrap_err();
        assert!(err.to_string().contains("at least 1 tool"));
    }

    #[test]
    fn test_linear_workflow_requires_at_least_2_steps() {
        let spec = Spec {
            agent_type: AgentType::LinearWorkflow,
            name: "pipeline".into(),
            description: "A pipeline".into(),
            model: "gpt-4o".into(),
            system_prompt: "Process data.".into(),
            max_tokens: 4096,
            budget: None,
            tools: vec![],
            workflow: Some(WorkflowSpec {
                entry_step: "step1".into(),
                steps: vec![
                    WorkflowStep { id: "step1".into(), name: "Step 1".into(), prompt: "Do thing 1".into(), allowed_tools: vec![] },
                ], // only 1 step — should fail
                edges: vec![],
                judge: JudgeSpec { strategy: "linear".into() },
            }),
            deploy: DeployMode::Cli,
            provider: ProviderSpec::default(),
        };
        let err = spec.validate().unwrap_err();
        assert!(err.to_string().contains("at least 2 steps"));
    }

    #[test]
    fn test_conditional_workflow_requires_declarative_judge() {
        let spec = Spec {
            agent_type: AgentType::ConditionalWorkflow,
            name: "router".into(),
            description: "A router".into(),
            model: "gpt-4o".into(),
            system_prompt: "Route requests.".into(),
            max_tokens: 4096,
            budget: None,
            tools: vec![],
            workflow: Some(WorkflowSpec {
                entry_step: "classify".into(),
                steps: vec![
                    WorkflowStep { id: "classify".into(), name: "Classify".into(), prompt: "Classify input".into(), allowed_tools: vec![] },
                    WorkflowStep { id: "fix".into(), name: "Fix".into(), prompt: "Fix issue".into(), allowed_tools: vec![] },
                    WorkflowStep { id: "report".into(), name: "Report".into(), prompt: "Report result".into(), allowed_tools: vec![] },
                ],
                edges: vec![
                    WorkflowEdge { from: "classify".into(), to: "fix".into(), condition: Some(EdgeConditionSpec { op: "eq".into(), pointer: "/status".into(), value: serde_json::json!("fail") }) },
                    WorkflowEdge { from: "classify".into(), to: "report".into(), condition: Some(EdgeConditionSpec { op: "eq".into(), pointer: "/status".into(), value: serde_json::json!("ok") }) },
                    WorkflowEdge { from: "fix".into(), to: "report".into(), condition: None },
                ],
                judge: JudgeSpec { strategy: "declarative".into() },
            }),
            deploy: DeployMode::Cli,
            provider: ProviderSpec::default(),
        };
        assert!(spec.validate().is_ok());
    }

    #[test]
    fn test_conditional_workflow_fails_with_linear_judge() {
        let mut spec = Spec {
            agent_type: AgentType::ConditionalWorkflow,
            name: "router".into(),
            description: "A router".into(),
            model: "gpt-4o".into(),
            system_prompt: "Route requests.".into(),
            max_tokens: 4096,
            budget: None,
            tools: vec![],
            workflow: Some(WorkflowSpec {
                entry_step: "classify".into(),
                steps: vec![
                    WorkflowStep { id: "classify".into(), name: "Classify".into(), prompt: "Classify input".into(), allowed_tools: vec![] },
                    WorkflowStep { id: "fix".into(), name: "Fix".into(), prompt: "Fix issue".into(), allowed_tools: vec![] },
                    WorkflowStep { id: "report".into(), name: "Report".into(), prompt: "Report result".into(), allowed_tools: vec![] },
                ],
                edges: vec![
                    WorkflowEdge { from: "classify".into(), to: "fix".into(), condition: Some(EdgeConditionSpec { op: "eq".into(), pointer: "/status".into(), value: serde_json::json!("fail") }) },
                    WorkflowEdge { from: "classify".into(), to: "report".into(), condition: None },
                    WorkflowEdge { from: "fix".into(), to: "report".into(), condition: None },
                ],
                judge: JudgeSpec { strategy: "linear".into() }, // wrong strategy
            }),
            deploy: DeployMode::Cli,
            provider: ProviderSpec::default(),
        };
        let err = spec.validate().unwrap_err();
        assert!(err.to_string().contains("declarative"));
    }

    #[test]
    fn test_workflow_entry_step_must_exist_in_steps() {
        let spec = Spec {
            agent_type: AgentType::LinearWorkflow,
            name: "pipeline".into(),
            description: "A pipeline".into(),
            model: "gpt-4o".into(),
            system_prompt: "Process.".into(),
            max_tokens: 4096,
            budget: None,
            tools: vec![],
            workflow: Some(WorkflowSpec {
                entry_step: "nonexistent".into(), // not in steps
                steps: vec![
                    WorkflowStep { id: "step1".into(), name: "Step 1".into(), prompt: "Do 1".into(), allowed_tools: vec![] },
                    WorkflowStep { id: "step2".into(), name: "Step 2".into(), prompt: "Do 2".into(), allowed_tools: vec![] },
                ],
                edges: vec![WorkflowEdge { from: "step1".into(), to: "step2".into(), condition: None }],
                judge: JudgeSpec { strategy: "linear".into() },
            }),
            deploy: DeployMode::Cli,
            provider: ProviderSpec::default(),
        };
        let err = spec.validate().unwrap_err();
        assert!(err.to_string().contains("entry_step"));
    }

    #[test]
    fn test_edge_references_must_exist_in_steps() {
        let spec = Spec {
            agent_type: AgentType::LinearWorkflow,
            name: "pipeline".into(),
            description: "A pipeline".into(),
            model: "gpt-4o".into(),
            system_prompt: "Process.".into(),
            max_tokens: 4096,
            budget: None,
            tools: vec![],
            workflow: Some(WorkflowSpec {
                entry_step: "step1".into(),
                steps: vec![
                    WorkflowStep { id: "step1".into(), name: "Step 1".into(), prompt: "Do 1".into(), allowed_tools: vec![] },
                    WorkflowStep { id: "step2".into(), name: "Step 2".into(), prompt: "Do 2".into(), allowed_tools: vec![] },
                ],
                edges: vec![WorkflowEdge { from: "step1".into(), to: "nonexistent".into(), condition: None }],
                judge: JudgeSpec { strategy: "linear".into() },
            }),
            deploy: DeployMode::Cli,
            provider: ProviderSpec::default(),
        };
        let err = spec.validate().unwrap_err();
        assert!(err.to_string().contains("edge"));
    }

    #[test]
    fn test_spec_serialization_roundtrip() {
        let spec = Spec {
            agent_type: AgentType::SingleWithTools,
            name: "test-bot".into(),
            description: "Test".into(),
            model: "gpt-4o".into(),
            system_prompt: "You are helpful.".into(),
            max_tokens: 4096,
            budget: Some(BudgetSpec { max_cost: 0.10 }),
            tools: vec![ToolSpec {
                name: "search".into(),
                description: "Search the web".into(),
                parameters: serde_json::json!({"type": "object", "properties": {"query": {"type": "string"}}}),
                implementation: "GET https://api.example.com/search?q={query}".into(),
            }],
            workflow: None,
            deploy: DeployMode::Api,
            provider: ProviderSpec { r#type: "openai".into(), base_url: None },
        };
        let json = serde_json::to_string(&spec).unwrap();
        let back: Spec = serde_json::from_str(&json).unwrap();
        assert_eq!(back.name, "test-bot");
        assert_eq!(back.agent_type, AgentType::SingleWithTools);
        assert_eq!(back.deploy, DeployMode::Api);
        assert_eq!(back.tools.len(), 1);
        assert!(back.tools[0].implementation.contains("api.example.com"));
    }

    #[test]
    fn test_spec_diff_parse() {
        let diff_json = serde_json::json!({
            "ops": [
                {"op": "add", "path": "/tools/0", "value": {"name": "search", "description": "Search", "parameters": {}, "implementation": "TODO: stub"}},
                {"op": "replace", "path": "/system_prompt", "value": "New prompt"}
            ]
        });
        let diff: SpecDiff = serde_json::from_value(diff_json).unwrap();
        assert_eq!(diff.ops.len(), 2);
        assert_eq!(diff.ops[0].op, "add");
        assert_eq!(diff.ops[1].path, "/system_prompt");
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --lib spec`
Expected: FAIL — types not defined

- [ ] **Step 3: Write minimal implementation**

```rust
use serde::{Deserialize, Serialize};

use crate::error::{StudioError, StudioResult};

/// Agent type determines the structure of the generated project.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AgentType {
    Single,
    SingleWithTools,
    LinearWorkflow,
    ConditionalWorkflow,
}

/// Deployment mode for the generated project.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum DeployMode {
    #[default]
    Cli,
    Api,
}

/// LLM provider configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProviderSpec {
    #[serde(rename = "type")]
    pub r#type: String, // "openai" | "anthropic"
    /// null → generated code reads from env (OPENAI_API_BASE / ANTHROPIC_API_BASE)
    #[serde(default)]
    pub base_url: Option<String>,
}

impl Default for ProviderSpec {
    fn default() -> Self {
        Self {
            r#type: "openai".into(),
            base_url: None,
        }
    }
}

/// Budget limit for the agent.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BudgetSpec {
    pub max_cost: f64,
}

/// A tool definition in the spec.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolSpec {
    pub name: String,
    pub description: String,
    /// JSON Schema for tool parameters.
    pub parameters: serde_json::Value,
    /// Implementation description (API endpoint / SQL / file path / logic).
    /// If uncertain, this is "TODO: stub" and the coding agent generates a placeholder.
    #[serde(default)]
    pub implementation: String,
}

/// A workflow step definition.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkflowStep {
    pub id: String,
    pub name: String,
    pub prompt: String,
    #[serde(default)]
    pub allowed_tools: Vec<String>,
}

/// Edge condition for conditional routing (declarative).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EdgeConditionSpec {
    pub op: String, // eq, ne, gt, gte, lt, lte, exists, missing
    pub pointer: String, // JSON pointer into step_finished.result.structured
    #[serde(default)]
    pub value: serde_json::Value, // comparison value (not used for exists/missing)
}

/// A workflow edge.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkflowEdge {
    pub from: String,
    pub to: String,
    #[serde(default)]
    pub condition: Option<EdgeConditionSpec>,
}

/// Judge configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JudgeSpec {
    pub strategy: String, // "linear" | "declarative"
}

/// Workflow definition.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkflowSpec {
    pub entry_step: String,
    pub steps: Vec<WorkflowStep>,
    pub edges: Vec<WorkflowEdge>,
    pub judge: JudgeSpec,
}

/// The complete spec — the structured intent produced by the Converser agent.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Spec {
    pub agent_type: AgentType,
    pub name: String,
    pub description: String,
    pub model: String,
    pub system_prompt: String,
    pub max_tokens: u32,
    #[serde(default)]
    pub budget: Option<BudgetSpec>,
    #[serde(default)]
    pub tools: Vec<ToolSpec>,
    #[serde(default)]
    pub workflow: Option<WorkflowSpec>,
    #[serde(default)]
    pub deploy: DeployMode,
    #[serde(default)]
    pub provider: ProviderSpec,
}

impl Spec {
    /// Validate spec completeness per §4.1 "信息充分" criteria.
    pub fn validate(&self) -> StudioResult<()> {
        match self.agent_type {
            AgentType::Single => {
                // agent type, description, model, system_prompt required
                if self.system_prompt.is_empty() {
                    return Err(StudioError::SpecValidation("system_prompt is required".into()));
                }
            }
            AgentType::SingleWithTools => {
                if self.system_prompt.is_empty() {
                    return Err(StudioError::SpecValidation("system_prompt is required".into()));
                }
                if self.tools.is_empty() {
                    return Err(StudioError::SpecValidation(
                        "single_with_tools requires at least 1 tool".into(),
                    ));
                }
            }
            AgentType::LinearWorkflow => {
                let wf = self.workflow.as_ref().ok_or_else(|| {
                    StudioError::SpecValidation("linear_workflow requires workflow field".into())
                })?;
                if wf.steps.len() < 2 {
                    return Err(StudioError::SpecValidation(
                        "linear_workflow requires at least 2 steps".into(),
                    ));
                }
                if wf.judge.strategy != "linear" && wf.judge.strategy != "declarative" {
                    return Err(StudioError::SpecValidation(
                        format!("unknown judge strategy: {}", wf.judge.strategy),
                    ));
                }
                Self::validate_workflow_structure(wf)?;
            }
            AgentType::ConditionalWorkflow => {
                let wf = self.workflow.as_ref().ok_or_else(|| {
                    StudioError::SpecValidation(
                        "conditional_workflow requires workflow field".into(),
                    ))
                })?;
                if wf.steps.len() < 2 {
                    return Err(StudioError::SpecValidation(
                        "conditional_workflow requires at least 2 steps".into(),
                    ));
                }
                if wf.judge.strategy != "declarative" {
                    return Err(StudioError::SpecValidation(
                        "conditional_workflow requires judge strategy = 'declarative'".into(),
                    ));
                }
                let has_conditional_edge = wf.edges.iter().any(|e| e.condition.is_some());
                if !has_conditional_edge {
                    return Err(StudioError::SpecValidation(
                        "conditional_workflow requires at least 1 edge with a condition".into(),
                    ));
                }
                Self::validate_workflow_structure(wf)?;
            }
        }
        Ok(())
    }

    fn validate_workflow_structure(wf: &WorkflowSpec) -> StudioResult<()> {
        let step_ids: std::collections::HashSet<&str> =
            wf.steps.iter().map(|s| s.id.as_str()).collect();

        if !step_ids.contains(wf.entry_step.as_str()) {
            return Err(StudioError::SpecValidation(format!(
                "entry_step '{}' not found in steps",
                wf.entry_step
            )));
        }

        for edge in &wf.edges {
            if !step_ids.contains(edge.from.as_str()) {
                return Err(StudioError::SpecValidation(format!(
                    "edge from '{}' references nonexistent step",
                    edge.from
                )));
            }
            if !step_ids.contains(edge.to.as_str()) {
                return Err(StudioError::SpecValidation(format!(
                    "edge to '{}' references nonexistent step",
                    edge.to
                )));
            }
        }

        Ok(())
    }

    /// Parse from the JSON that the Converser agent emits via emit_spec.
    pub fn from_conversation_json(json: &serde_json::Value) -> StudioResult<Self> {
        serde_json::from_value(json.clone())
            .map_err(|e| StudioError::SpecValidation(format!("spec parse error: {e}")))
    }
}

// ── Spec Diff (JSON Patch style, §4.4) ───────────────────────────────────────

/// A single JSON Patch operation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SpecDiffOp {
    pub op: String, // "add", "replace", "remove"
    pub path: String, // JSON Pointer, e.g. "/tools/0", "/system_prompt"
    #[serde(default)]
    pub value: Option<serde_json::Value>,
}

/// Spec diff — JSON Patch style, used by emit_spec_diff (mode 2, incremental).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SpecDiff {
    pub ops: Vec<SpecDiffOp>,
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --lib spec`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add Spec data structures with validation"
```

---

### Task 4: Project Management (project.rs)

**Files:**
- Create: `crates/studio-core/src/project.rs`
- Test: `crates/studio-core/src/project.rs` (inline tests)

**Interfaces:**
- Produces: `ProjectManager`, `ProjectMeta`, `RunSummary`
- Consumes: `StudioError` from Task 2, `Spec` from Task 3

**Design doc reference:** §3 项目结构, §6 ProjectManager

- [ ] **Step 1: Write the failing tests**

```rust
// In project.rs

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn make_manager() -> (ProjectManager, TempDir) {
        let dir = TempDir::new().unwrap();
        let mgr = ProjectManager::new(dir.path().to_path_buf());
        (mgr, dir)
    }

    #[test]
    fn test_create_project() {
        let (mgr, _dir) = make_manager();
        let project = mgr.create_project("my-agent").unwrap();
        assert_eq!(project.name, "my-agent");
        assert!(project.dir.exists());
        assert!(project.dir.join(".studio").exists());
        assert!(project.dir.join(".studio/specs").exists());
        assert!(project.dir.join(".studio/runs").exists());
    }

    #[test]
    fn test_write_and_read_file() {
        let (mgr, _dir) = make_manager();
        let project = mgr.create_project("test-proj").unwrap();
        mgr.write_file(&project.id, "main.py", "print('hello')").unwrap();
        let content = mgr.read_file(&project.id, "main.py").unwrap();
        assert_eq!(content, "print('hello')");
    }

    #[test]
    fn test_list_files() {
        let (mgr, _dir) = make_manager();
        let project = mgr.create_project("test-proj").unwrap();
        mgr.write_file(&project.id, "main.py", "...").unwrap();
        mgr.write_file(&project.id, "tools.py", "...").unwrap();
        let files = mgr.list_files(&project.id).unwrap();
        assert!(files.iter().any(|f| f == "main.py"));
        assert!(files.iter().any(|f| f == "tools.py"));
    }

    #[test]
    fn test_path_traversal_blocked() {
        let (mgr, _dir) = make_manager();
        let project = mgr.create_project("test-proj").unwrap();
        let result = mgr.read_file(&project.id, "../../../etc/passwd");
        assert!(result.is_err());
        let result = mgr.write_file(&project.id, "../../evil.py", "malicious");
        assert!(result.is_err());
    }

    #[test]
    fn test_project_not_found() {
        let (mgr, _dir) = make_manager();
        let result = mgr.open_project("nonexistent-id");
        assert!(result.is_err());
    }

    #[test]
    fn test_list_projects() {
        let (mgr, _dir) = make_manager();
        mgr.create_project("proj-a").unwrap();
        mgr.create_project("proj-b").unwrap();
        let projects = mgr.list_projects().unwrap();
        assert_eq!(projects.len(), 2);
    }

    #[test]
    fn test_save_and_load_spec() {
        let (mgr, _dir) = make_manager();
        let project = mgr.create_project("test-proj").unwrap();
        let spec = Spec {
            agent_type: AgentType::Single,
            name: "test".into(),
            description: "test".into(),
            model: "gpt-4o".into(),
            system_prompt: "You are helpful.".into(),
            max_tokens: 4096,
            budget: None,
            tools: vec![],
            workflow: None,
            deploy: DeployMode::Cli,
            provider: ProviderSpec::default(),
        };
        mgr.save_spec(&project.id, &spec).unwrap();
        let loaded = mgr.load_current_spec(&project.id).unwrap();
        assert_eq!(loaded.name, "test");
        assert_eq!(loaded.agent_type, AgentType::Single);
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --lib project`
Expected: FAIL — types not defined

- [ ] **Step 3: Write minimal implementation**

```rust
use std::path::{Path, PathBuf};
use std::fs;

use serde::{Deserialize, Serialize};

use crate::error::{StudioError, StudioResult};
use crate::spec::Spec;

/// Project metadata stored in `.studio/meta.json`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProjectMeta {
    pub id: String,
    pub name: String,
    pub dir: PathBuf,
    pub model: String,
    pub agent_type: String,
    pub created_at: chrono::DateTime<chrono::Utc>,
}

/// Summary of a run, for listing.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunSummary {
    pub run_id: String,
    pub project_id: String,
    pub status: String, // "running", "completed", "failed", "timeout"
    pub started_at: chrono::DateTime<chrono::Utc>,
    pub ended_at: Option<chrono::DateTime<chrono::Utc>>,
}

/// Manages project directories on the filesystem.
/// All projects live under a root directory (typically `~/.senza-studio/projects/`).
pub struct ProjectManager {
    root: PathBuf,
}

impl ProjectManager {
    pub fn new(root: PathBuf) -> Self {
        Self { root }
    }

    /// Create a new project directory with `.studio/` substructure.
    pub fn create_project(&self, name: &str) -> StudioResult<ProjectMeta> {
        let id = uuid::Uuid::now_v7().to_string();
        let dir = self.root.join(&id);

        // Create directory structure
        fs::create_dir_all(dir.join(".studio/specs"))?;
        fs::create_dir_all(dir.join(".studio/runs"))?;

        let meta = ProjectMeta {
            id: id.clone(),
            name: name.into(),
            dir: dir.clone(),
            model: String::new(),
            agent_type: String::new(),
            created_at: chrono::Utc::now(),
        };
        self.save_meta(&id, &meta)?;
        Ok(meta)
    }

    /// Open an existing project by ID.
    pub fn open_project(&self, id: &str) -> StudioResult<ProjectMeta> {
        let dir = self.root.join(id);
        if !dir.exists() {
            return Err(StudioError::ProjectNotFound(id.into()));
        }
        let meta_path = dir.join(".studio/meta.json");
        let meta_str = fs::read_to_string(&meta_path)
            .map_err(|_| StudioError::ProjectNotFound(id.into()))?;
        let meta: ProjectMeta = serde_json::from_str(&meta_str)?;
        Ok(meta)
    }

    /// List all projects.
    pub fn list_projects(&self) -> StudioResult<Vec<ProjectMeta>> {
        if !self.root.exists() {
            return Ok(vec![]);
        }
        let mut projects = vec![];
        for entry in fs::read_dir(&self.root)? {
            let entry = entry?;
            let path = entry.path();
            if path.is_dir() && path.join(".studio/meta.json").exists() {
                let id = path
                    .file_name()
                    .and_then(|n| n.to_str())
                    .unwrap_or("");
                if let Ok(meta) = self.open_project(id) {
                    projects.push(meta);
                }
            }
        }
        Ok(projects)
    }

    /// Read a file from a project.
    pub fn read_file(&self, project_id: &str, path: &str) -> StudioResult<String> {
        let resolved = self.resolve_path(project_id, path)?;
        if !resolved.exists() {
            return Err(StudioError::FileNotFound(path.into()));
        }
        Ok(fs::read_to_string(&resolved)?)
    }

    /// Write a file to a project.
    pub fn write_file(&self, project_id: &str, path: &str, content: &str) -> StudioResult<()> {
        let resolved = self.resolve_path(project_id, path)?;
        if let Some(parent) = resolved.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(&resolved, content)?;
        Ok(())
    }

    /// List all files in a project (excluding `.studio/`).
    pub fn list_files(&self, project_id: &str) -> StudioResult<Vec<String>> {
        let dir = self.root.join(project_id);
        if !dir.exists() {
            return Err(StudioError::ProjectNotFound(project_id.into()));
        }
        let mut files = vec![];
        self.collect_files(&dir, &dir, &mut files)?;
        files.sort();
        Ok(files)
    }

    /// Save spec to `.studio/specs/current.json`.
    pub fn save_spec(&self, project_id: &str, spec: &Spec) -> StudioResult<()> {
        let spec_dir = self.root.join(project_id).join(".studio/specs");
        fs::create_dir_all(&spec_dir)?;
        let json = serde_json::to_string_pretty(spec)?;
        fs::write(spec_dir.join("current.json"), json)?;

        // Also save a timestamped snapshot
        let timestamp = chrono::Utc::now().format("%Y%m%dT%H%M%S");
        fs::write(spec_dir.join(format!("{timestamp}.json")), json)?;
        Ok(())
    }

    /// Load the current spec from `.studio/specs/current.json`.
    pub fn load_current_spec(&self, project_id: &str) -> StudioResult<Spec> {
        let path = self
            .root
            .join(project_id)
            .join(".studio/specs/current.json");
        if !path.exists() {
            return Err(StudioError::FileNotFound(
                ".studio/specs/current.json".into(),
            ));
        }
        let json = fs::read_to_string(&path)?;
        let spec: Spec = serde_json::from_str(&json)?;
        Ok(spec)
    }

    /// Get the project directory path.
    pub fn project_dir(&self, project_id: &str) -> StudioResult<PathBuf> {
        let dir = self.root.join(project_id);
        if !dir.exists() {
            return Err(StudioError::ProjectNotFound(project_id.into()));
        }
        Ok(dir)
    }

    fn save_meta(&self, project_id: &str, meta: &ProjectMeta) -> StudioResult<()> {
        let meta_path = self.root.join(project_id).join(".studio/meta.json");
        let json = serde_json::to_string_pretty(meta)?;
        fs::write(&meta_path, json)?;
        Ok(())
    }

    fn resolve_path(&self, project_id: &str, path: &str) -> StudioResult<PathBuf> {
        let base = self.root.join(project_id);
        if !base.exists() {
            return Err(StudioError::ProjectNotFound(project_id.into()));
        }
        let resolved = base.join(path);
        // Canonicalize to resolve `..` and verify it's still under base
        let canonical_base = base.canonicalize()?;
        let canonical_resolved = resolved
            .parent()
            .map(|p| {
                fs::create_dir_all(p).ok();
                p.canonicalize()
            })
            .unwrap_or_else(|| canonical_base.clone().canonicalize())
            .map_err(|_| StudioError::PathTraversalBlocked(path.into()))?;
        // Check that resolved path is within base
        if !canonical_resolved.starts_with(&canonical_base) {
            return Err(StudioError::PathTraversalBlocked(path.into()));
        }
        Ok(resolved)
    }

    fn collect_files(
        &self,
        base: &Path,
        current: &Path,
        files: &mut Vec<String>,
    ) -> StudioResult<()> {
        for entry in fs::read_dir(current)? {
            let entry = entry?;
            let path = entry.path();
            let name = entry.file_name();
            // Skip .studio directory
            if name == ".studio" {
                continue;
            }
            if path.is_dir() {
                self.collect_files(base, &path, files)?;
            } else {
                if let Ok(rel) = path.strip_prefix(base) {
                    files.push(rel.to_string_lossy().into_owned());
                }
            }
        }
        Ok(())
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --lib project`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add ProjectManager with FS CRUD and path safety"
```

---

### Task 5: Examples Library Scaffolding

**Files:**
- Create: `crates/studio-core/src/examples/mod.rs`
- Create: `crates/studio-core/src/examples/basic_chat/main.py`
- Create: `crates/studio-core/src/examples/tool_calling/main.py`
- Create: `crates/studio-core/src/examples/streaming/main.py`
- Create: `crates/studio-core/src/examples/budget_controlled/main.py`
- Create: `crates/studio-core/src/examples/linear_pipeline/main.py`
- Create: `crates/studio-core/src/examples/conditional_routing/main.py`
- Create: `crates/studio-core/src/examples/crash_recovery/main.py`
- Create: `crates/studio-core/src/examples/human_in_loop/main.py`

**Interfaces:**
- Produces: `ExampleProject`, `ExampleRegistry`, `list_examples()`, `get_example(id) -> Option<ExampleProject>`
- Consumes: nothing from earlier tasks

**Design doc reference:** §4.2 示例库, §5 示例库入口

- [ ] **Step 1: Write the failing test**

```rust
// In examples/mod.rs

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_list_examples_returns_all_8() {
        let examples = list_examples();
        assert_eq!(examples.len(), 8);
    }

    #[test]
    fn test_get_example_by_id() {
        let example = get_example("basic_chat").unwrap();
        assert_eq!(example.id, "basic_chat");
        assert!(!example.name.is_empty());
        assert!(!example.description.is_empty());
        assert!(!example.files.is_empty());
        // Each example has at least main.py
        assert!(example.files.iter().any(|(path, _)| path == "main.py"));
    }

    #[test]
    fn test_get_nonexistent_example() {
        assert!(get_example("nonexistent").is_none());
    }

    #[test]
    fn test_example_files_are_valid_python() {
        // Quick smoke: each main.py contains "import senza"
        for ex in list_examples() {
            let main_py = ex.files.iter().find(|(p, _)| p == "main.py");
            assert!(main_py.is_some(), "example {} missing main.py", ex.id);
            let (_, content) = main_py.unwrap();
            assert!(
                content.contains("senza"),
                "example {} main.py doesn't import senza",
                ex.id
            );
        }
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --lib examples`
Expected: FAIL — module not defined

- [ ] **Step 3: Create example Python files**

Create `basic_chat/main.py` (adapted from Senza example `01_basic_prompt.py`):

```python
"""Basic chat agent — minimal Senza usage."""
import os
import senza
from senza import HarnessBuilder, create_openai_provider

def build_harness():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_API_BASE") or None
    provider = create_openai_provider(api_key=api_key, base_url=base_url)
    return (
        HarnessBuilder(model="gpt-4o")
        .provider("gpt-*", provider)
        .system_prompt("You are a helpful assistant.")
        .max_tokens(4096)
        .auto_compact(True)
        .build(env=senza.OsEnv(working_dir="."))
    )

if __name__ == "__main__":
    harness = build_harness()
    print("Chat agent ready. Ctrl+D to exit.")
    while True:
        try:
            user_input = input("> ")
        except EOFError:
            break
        if not user_input:
            break
        events = harness.prompt_and_collect(user_input, timeout_ms=30000)
        for event in events:
            if event["type"] == "text_delta":
                print(event.get("text", ""), end="", flush=True)
        print()
```

Create `tool_calling/main.py` (adapted from `02_tool_calling.py`):

```python
"""Tool-calling agent — demonstrates create_tool."""
import os
import json
import senza
from senza import HarnessBuilder, create_openai_provider, create_tool

def weather_tool():
    schema = json.dumps({
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "City name"}
        },
        "required": ["city"],
    })
    def callback(args, ctx):
        city = args.get("city", "unknown")
        return {"content": [{"type": "text", "text": f"Weather in {city}: Sunny, 22°C"}], "terminate": False}
    return create_tool(name="get_weather", description="Get weather for a city", parameters_schema=schema, callback=callback)

def build_harness():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_API_BASE") or None
    provider = create_openai_provider(api_key=api_key, base_url=base_url)
    return (
        HarnessBuilder(model="gpt-4o")
        .provider("gpt-*", provider)
        .system_prompt("You are a weather assistant. Use get_weather to answer.")
        .max_tokens(4096)
        .tool(weather_tool())
        .auto_compact(True)
        .build(env=senza.OsEnv(working_dir="."))
    )

if __name__ == "__main__":
    harness = build_harness()
    print("Weather agent ready. Ctrl+D to exit.")
    while True:
        try:
            user_input = input("> ")
        except EOFError:
            break
        if not user_input:
            break
        events = harness.prompt_and_collect(user_input, timeout_ms=30000)
        for event in events:
            if event["type"] == "text_delta":
                print(event.get("text", ""), end="", flush=True)
        print()
```

Create `streaming/main.py` (adapted from `03_streaming.py`):

```python
"""Streaming agent — dual-thread events() + prompt() pattern."""
import os
import threading
import senza
from senza import HarnessBuilder, create_openai_provider

def build_harness():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_API_BASE") or None
    provider = create_openai_provider(api_key=api_key, base_url=base_url)
    return (
        HarnessBuilder(model="gpt-4o")
        .provider("gpt-*", provider)
        .system_prompt("You are a helpful assistant.")
        .max_tokens(4096)
        .auto_compact(True)
        .build(env=senza.OsEnv(working_dir="."))
    )

if __name__ == "__main__":
    harness = build_harness()
    print("Streaming agent ready. Ctrl+D to exit.")
    while True:
        try:
            user_input = input("> ")
        except EOFError:
            break
        if not user_input:
            break
        done = threading.Event()
        def stream_events():
            for event in harness.events(timeout_ms=30000):
                t = event["type"]
                if t == "text_delta":
                    print(event.get("text", ""), end="", flush=True)
                elif t in ("settled", "aborted", "error"):
                    done.set()
                    break
        t = threading.Thread(target=stream_events)
        t.start()
        harness.prompt(user_input)
        t.join(timeout=30)
        print()
```

Create `budget_controlled/main.py` (adapted from `08_budget_pricing.py`):

```python
"""Budget-controlled agent — demonstrates budget + pricing."""
import os
import senza
from senza import HarnessBuilder, create_openai_provider, create_pricing_provider

def build_harness():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_API_BASE") or None
    provider = create_openai_provider(api_key=api_key, base_url=base_url)
    pricing = create_pricing_provider()
    return (
        HarnessBuilder(model="gpt-4o")
        .provider("gpt-*", provider)
        .system_prompt("You are a helpful assistant.")
        .max_tokens(4096)
        .pricing(pricing)
        .budget(0.10, None)  # $0.10 max, surveillance mode
        .auto_compact(True)
        .build(env=senza.OsEnv(working_dir="."))
    )

if __name__ == "__main__":
    harness = build_harness()
    print("Budget-controlled agent ready ($0.10 max). Ctrl+D to exit.")
    while True:
        try:
            user_input = input("> ")
        except EOFError:
            break
        if not user_input:
            break
        events = harness.prompt_and_collect(user_input, timeout_ms=30000)
        for event in events:
            if event["type"] == "text_delta":
                print(event.get("text", ""), end="", flush=True)
        print()
    usage = harness.usage()
    print(f"\nTotal cost: ${usage.get('total_cost', 0):.4f}")
```

Create `linear_pipeline/main.py` (adapted from runtime `01_linear_workflow.py`):

```python
"""Linear pipeline workflow — 3 sequential steps."""
import os
import senza
from senza import HarnessBuilder, create_openai_provider, WorkflowEngine, Workflow

def build_workflow():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_API_BASE") or None
    provider = create_openai_provider(api_key=api_key, base_url=base_url)

    workflow = Workflow(
        entry_step="collect",
        steps=[
            {"kind": "llm", "id": "collect", "name": "Collect Info", "prompt": "Collect the user's request: {user_input}", "allowed_tools": []},
            {"kind": "llm", "id": "process", "name": "Process", "prompt": "Process the collected info and produce a result.", "allowed_tools": []},
            {"kind": "llm", "id": "report", "name": "Report", "prompt": "Summarize the result for the user.", "allowed_tools": []},
        ],
        edges=[
            {"from": "collect", "to": "process"},
            {"from": "process", "to": "report"},
        ],
    )
    return WorkflowEngine(workflow, config={"provider": provider, "model": "gpt-4o"})

if __name__ == "__main__":
    engine = build_workflow()
    task_input = input("Submit task: ")
    engine.set_context_variable("user_input", task_input)
    for event in engine.subscribe(timeout_ms=60000):
        t = event.get("type", "")
        if t == "step_started":
            print(f"\n[step] {event.get('step_name', '?')}")
        elif t == "step_finished":
            result = event.get("result", {})
            output = result.get("output", "")
            if output:
                print(f"  → {output.strip()[:200]}")
        elif t in ("failed", "cancelled"):
            break
    engine.run()
```

Create `conditional_routing/main.py` (adapted from runtime `02_conditional_routing.py`):

```python
"""Conditional routing workflow — branches based on structured output."""
import os
import senza
from senza import HarnessBuilder, create_openai_provider, WorkflowEngine, Workflow

def build_workflow():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_API_BASE") or None
    provider = create_openai_provider(api_key=api_key, base_url=base_url)

    workflow = Workflow(
        entry_step="classify",
        steps=[
            {"kind": "llm", "id": "classify", "name": "Classify", "prompt": "Classify the input as 'ok' or 'fail'. Respond with JSON: {\"status\": \"ok\"|\"fail\"}", "allowed_tools": [], "structured": True},
            {"kind": "llm", "id": "fix", "name": "Fix", "prompt": "The input was classified as 'fail'. Fix the issue.", "allowed_tools": []},
            {"kind": "llm", "id": "report", "name": "Report", "prompt": "Report the final result.", "allowed_tools": []},
        ],
        edges=[
            {"from": "classify", "to": "fix", "condition": {"op": "eq", "pointer": "/status", "value": "fail"}},
            {"from": "classify", "to": "report", "condition": {"op": "eq", "pointer": "/status", "value": "ok"}},
            {"from": "fix", "to": "report"},
        ],
    )
    return WorkflowEngine(workflow, config={"provider": provider, "model": "gpt-4o"})

if __name__ == "__main__":
    engine = build_workflow()
    task_input = input("Submit task: ")
    engine.set_context_variable("user_input", task_input)
    for event in engine.subscribe(timeout_ms=60000):
        t = event.get("type", "")
        if t == "step_started":
            print(f"\n[step] {event.get('step_name', '?')}")
        elif t == "step_finished":
            result = event.get("result", {})
            print(f"  structured: {result.get('structured', {})}")
        elif t in ("failed", "cancelled"):
            break
    engine.run()
```

Create `crash_recovery/main.py` (adapted from runtime `04_crash_recovery.py`):

```python
"""Crash recovery workflow — demonstrates with_task_store + restore.
NOTE: Reference only. Crash recovery is NOT in Studio MVP."""
import os
import senza
from senza import HarnessBuilder, create_openai_provider, WorkflowEngine, Workflow

def build_workflow():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_API_BASE") or None
    provider = create_openai_provider(api_key=api_key, base_url=base_url)

    workflow = Workflow(
        entry_step="step1",
        steps=[
            {"kind": "llm", "id": "step1", "name": "Step 1", "prompt": "Do step 1.", "allowed_tools": []},
            {"kind": "llm", "id": "step2", "name": "Step 2", "prompt": "Do step 2.", "allowed_tools": []},
        ],
        edges=[{"from": "step1", "to": "step2"}],
    )
    engine = WorkflowEngine(workflow, config={"provider": provider, "model": "gpt-4o"})
    engine.with_task_store("./.task_store")
    return engine

if __name__ == "__main__":
    engine = build_workflow()
    print("Crash recovery demo. Submit a task:")
    task_input = input("> ")
    engine.set_context_variable("user_input", task_input)
    engine.run()
    print(f"Final state: {engine.state()}")
```

Create `human_in_loop/main.py` (adapted from runtime `06_human_in_the_loop.py`):

```python
"""Human-in-the-loop workflow — pause/resume pattern."""
import os
import senza
from senza import HarnessBuilder, create_openai_provider, WorkflowEngine, Workflow, create_event_channel

def build_workflow():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_API_BASE") or None
    provider = create_openai_provider(api_key=api_key, base_url=base_url)

    review_tool, wait_for_review = create_event_channel("human_review")

    workflow = Workflow(
        entry_step="draft",
        steps=[
            {"kind": "llm", "id": "draft", "name": "Draft", "prompt": "Draft a response to: {user_input}", "allowed_tools": []},
            {"kind": "llm", "id": "review", "name": "Review", "prompt": "The draft needs review. Call request_review to get human feedback.", "allowed_tools": ["request_review"]},
            {"kind": "llm", "id": "finalize", "name": "Finalize", "prompt": "Finalize the response based on review feedback.", "allowed_tools": []},
        ],
        edges=[
            {"from": "draft", "to": "review"},
            {"from": "review", "to": "finalize"},
        ],
    )
    engine = WorkflowEngine(workflow, config={"provider": provider, "model": "gpt-4o"})
    engine.with_tool(review_tool)
    return engine, wait_for_review

if __name__ == "__main__":
    engine, wait_for_review = build_workflow()
    task_input = input("Submit task: ")
    engine.set_context_variable("user_input", task_input)
    import threading
    done = threading.Event()
    def stream():
        for event in engine.subscribe(timeout_ms=120000):
            t = event.get("type", "")
            if t == "paused":
                print(f"\n[paused] {event.get('reason', '')}")
                feedback = input("Review feedback: ")
                engine.set_context_variable("review_feedback", feedback)
                engine.resume()
            elif t in ("failed", "cancelled"):
                done.set()
                break
    t = threading.Thread(target=stream)
    t.start()
    engine.run()
    t.join(timeout=120)
```

- [ ] **Step 4: Write the examples module**

Create `crates/studio-core/src/examples/mod.rs`:

```rust
//! Built-in example projects.
//!
//! Each example is a self-contained Senza Python project.
//! The frontend lists these via the example registry; selecting one
//! copies all files into a new project directory.

use std::collections::HashMap;

/// A single example project.
#[derive(Debug, Clone)]
pub struct ExampleProject {
    pub id: &'static str,
    pub name: &'static str,
    pub description: &'static str,
    pub tags: &'static [&'static str],
    /// (relative_path, content) pairs
    pub files: Vec<(&'static str, &'static str)>,
}

/// List all built-in examples.
pub fn list_examples() -> Vec<ExampleProject> {
    vec![
        basic_chat(),
        tool_calling(),
        streaming(),
        budget_controlled(),
        linear_pipeline(),
        conditional_routing(),
        crash_recovery(),
        human_in_loop(),
    ]
}

/// Get an example by ID.
pub fn get_example(id: &str) -> Option<ExampleProject> {
    list_examples().into_iter().find(|e| e.id == id)
}

fn basic_chat() -> ExampleProject {
    ExampleProject {
        id: "basic_chat",
        name: "Basic Chat",
        description: "Minimal single-agent chat with streaming output.",
        tags: &["single", "streaming"],
        files: vec![("main.py", include_str!("basic_chat/main.py"))],
    }
}

fn tool_calling() -> ExampleProject {
    ExampleProject {
        id: "tool_calling",
        name: "Tool Calling",
        description: "Agent with a custom tool (weather lookup).",
        tags: &["single_with_tools", "tools"],
        files: vec![("main.py", include_str!("tool_calling/main.py"))],
    }
}

fn streaming() -> ExampleProject {
    ExampleProject {
        id: "streaming",
        name: "Streaming",
        description: "Dual-thread streaming pattern with events().",
        tags: &["single", "streaming"],
        files: vec![("main.py", include_str!("streaming/main.py"))],
    }
}

fn budget_controlled() -> ExampleProject {
    ExampleProject {
        id: "budget_controlled",
        name: "Budget Controlled",
        description: "Agent with pricing provider and budget limit.",
        tags: &["single", "budget", "pricing"],
        files: vec![("main.py", include_str!("budget_controlled/main.py"))],
    }
}

fn linear_pipeline() -> ExampleProject {
    ExampleProject {
        id: "linear_pipeline",
        name: "Linear Pipeline",
        description: "3-step linear workflow (collect → process → report).",
        tags: &["workflow", "linear"],
        files: vec![("main.py", include_str!("linear_pipeline/main.py"))],
    }
}

fn conditional_routing() -> ExampleProject {
    ExampleProject {
        id: "conditional_routing",
        name: "Conditional Routing",
        description: "Workflow with declarative edge conditions.",
        tags: &["workflow", "conditional", "structured"],
        files: vec![("main.py", include_str!("conditional_routing/main.py"))],
    }
}

fn crash_recovery() -> ExampleProject {
    ExampleProject {
        id: "crash_recovery",
        name: "Crash Recovery",
        description: "Workflow with task store for crash recovery (reference only).",
        tags: &["workflow", "crash_recovery"],
        files: vec![("main.py", include_str!("crash_recovery/main.py"))],
    }
}

fn human_in_loop() -> ExampleProject {
    ExampleProject {
        id: "human_in_loop",
        name: "Human in the Loop",
        description: "Workflow with pause/resume for human review.",
        tags: &["workflow", "pause_resume", "human_in_loop"],
        files: vec![("main.py", include_str!("human_in_loop/main.py"))],
    }
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cargo test --lib examples`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: add 8 built-in example projects"
```

---

### Task 6: Verify Full Crate Compiles and Tests Pass

**Files:**
- No new files

- [ ] **Step 1: Run cargo check**

Run: `cargo check`
Expected: PASS with no errors

- [ ] **Step 2: Run all tests**

Run: `cargo test`
Expected: All tests pass (no `#[ignore]` tests in this plan)

- [ ] **Step 3: Commit any fixes**

```bash
git add -A
git commit -m "chore: verify studio-core compiles and tests pass"
```
