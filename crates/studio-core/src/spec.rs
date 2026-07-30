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
                if self.system_prompt.is_empty() {
                    return Err(StudioError::SpecValidation(
                        "system_prompt is required".into(),
                    ));
                }
            }
            AgentType::SingleWithTools => {
                if self.system_prompt.is_empty() {
                    return Err(StudioError::SpecValidation(
                        "system_prompt is required".into(),
                    ));
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
                    return Err(StudioError::SpecValidation(format!(
                        "unknown judge strategy: {}",
                        wf.judge.strategy
                    )));
                }
                Self::validate_workflow_structure(wf)?;
            }
            AgentType::ConditionalWorkflow => {
                let wf = self.workflow.as_ref().ok_or_else(|| {
                    StudioError::SpecValidation(
                        "conditional_workflow requires workflow field".into(),
                    )
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
            tools: vec![],
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
                steps: vec![WorkflowStep {
                    id: "step1".into(),
                    name: "Step 1".into(),
                    prompt: "Do thing 1".into(),
                    allowed_tools: vec![],
                }],
                edges: vec![],
                judge: JudgeSpec {
                    strategy: "linear".into(),
                },
            }),
            deploy: DeployMode::Cli,
            provider: ProviderSpec::default(),
        };
        let err = spec.validate().unwrap_err();
        assert!(err.to_string().contains("at least 2 steps"));
    }

    #[test]
    fn test_conditional_workflow_valid() {
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
                    WorkflowStep {
                        id: "classify".into(),
                        name: "Classify".into(),
                        prompt: "Classify input".into(),
                        allowed_tools: vec![],
                    },
                    WorkflowStep {
                        id: "fix".into(),
                        name: "Fix".into(),
                        prompt: "Fix issue".into(),
                        allowed_tools: vec![],
                    },
                    WorkflowStep {
                        id: "report".into(),
                        name: "Report".into(),
                        prompt: "Report result".into(),
                        allowed_tools: vec![],
                    },
                ],
                edges: vec![
                    WorkflowEdge {
                        from: "classify".into(),
                        to: "fix".into(),
                        condition: Some(EdgeConditionSpec {
                            op: "eq".into(),
                            pointer: "/status".into(),
                            value: serde_json::json!("fail"),
                        }),
                    },
                    WorkflowEdge {
                        from: "classify".into(),
                        to: "report".into(),
                        condition: Some(EdgeConditionSpec {
                            op: "eq".into(),
                            pointer: "/status".into(),
                            value: serde_json::json!("ok"),
                        }),
                    },
                    WorkflowEdge {
                        from: "fix".into(),
                        to: "report".into(),
                        condition: None,
                    },
                ],
                judge: JudgeSpec {
                    strategy: "declarative".into(),
                },
            }),
            deploy: DeployMode::Cli,
            provider: ProviderSpec::default(),
        };
        assert!(spec.validate().is_ok());
    }

    #[test]
    fn test_conditional_workflow_fails_with_linear_judge() {
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
                    WorkflowStep {
                        id: "classify".into(),
                        name: "Classify".into(),
                        prompt: "Classify input".into(),
                        allowed_tools: vec![],
                    },
                    WorkflowStep {
                        id: "fix".into(),
                        name: "Fix".into(),
                        prompt: "Fix issue".into(),
                        allowed_tools: vec![],
                    },
                    WorkflowStep {
                        id: "report".into(),
                        name: "Report".into(),
                        prompt: "Report result".into(),
                        allowed_tools: vec![],
                    },
                ],
                edges: vec![
                    WorkflowEdge {
                        from: "classify".into(),
                        to: "fix".into(),
                        condition: Some(EdgeConditionSpec {
                            op: "eq".into(),
                            pointer: "/status".into(),
                            value: serde_json::json!("fail"),
                        }),
                    },
                    WorkflowEdge {
                        from: "classify".into(),
                        to: "report".into(),
                        condition: None,
                    },
                    WorkflowEdge {
                        from: "fix".into(),
                        to: "report".into(),
                        condition: None,
                    },
                ],
                judge: JudgeSpec {
                    strategy: "linear".into(),
                },
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
                entry_step: "nonexistent".into(),
                steps: vec![
                    WorkflowStep {
                        id: "step1".into(),
                        name: "Step 1".into(),
                        prompt: "Do 1".into(),
                        allowed_tools: vec![],
                    },
                    WorkflowStep {
                        id: "step2".into(),
                        name: "Step 2".into(),
                        prompt: "Do 2".into(),
                        allowed_tools: vec![],
                    },
                ],
                edges: vec![WorkflowEdge {
                    from: "step1".into(),
                    to: "step2".into(),
                    condition: None,
                }],
                judge: JudgeSpec {
                    strategy: "linear".into(),
                },
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
                    WorkflowStep {
                        id: "step1".into(),
                        name: "Step 1".into(),
                        prompt: "Do 1".into(),
                        allowed_tools: vec![],
                    },
                    WorkflowStep {
                        id: "step2".into(),
                        name: "Step 2".into(),
                        prompt: "Do 2".into(),
                        allowed_tools: vec![],
                    },
                ],
                edges: vec![WorkflowEdge {
                    from: "step1".into(),
                    to: "nonexistent".into(),
                    condition: None,
                }],
                judge: JudgeSpec {
                    strategy: "linear".into(),
                },
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
            provider: ProviderSpec {
                r#type: "openai".into(),
                base_url: None,
            },
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
