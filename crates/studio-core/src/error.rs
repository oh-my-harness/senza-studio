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

    #[error("invalid project name: {0}")]
    InvalidProjectName(String),

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

    #[test]
    fn test_invalid_project_name_display() {
        let err = StudioError::InvalidProjectName("empty name".into());
        assert!(err.to_string().contains("empty name"));
    }
}
