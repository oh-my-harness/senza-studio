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
            files.insert("main.py".into());
            files.insert("server.py".into());
            continue;
        }

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
            }
            "/workflow/judge" => {
                files.insert("main.py".into());
                add_server(&mut files);
            }
            _ => {
                files.insert("main.py".into());
                add_server(&mut files);
            }
        }
    }

    let mut result: Vec<String> = files.into_iter().collect();
    result.sort();
    result
}

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
        assert!(files.contains(&"server.py".to_string()));
    }
}
