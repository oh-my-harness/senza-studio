//! Built-in example projects.
//!
//! Each example is a self-contained Senza Python project.
//! The frontend lists these via the example registry; selecting one
//! copies all files into a new project directory.

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
        description: "3-step linear workflow (collect -> process -> report).",
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
        assert!(example.files.iter().any(|(path, _)| path == &"main.py"));
    }

    #[test]
    fn test_get_nonexistent_example() {
        assert!(get_example("nonexistent").is_none());
    }

    #[test]
    fn test_example_files_are_valid_python() {
        for ex in list_examples() {
            let main_py = ex.files.iter().find(|(p, _)| p == &"main.py");
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
