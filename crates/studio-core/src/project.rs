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
    pub status: String,
    pub started_at: chrono::DateTime<chrono::Utc>,
    pub ended_at: Option<chrono::DateTime<chrono::Utc>>,
}

/// Manages project directories on the filesystem.
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
                let id = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
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
        fs::write(spec_dir.join("current.json"), &json)?;
        let timestamp = chrono::Utc::now().format("%Y%m%dT%H%M%S");
        fs::write(spec_dir.join(format!("{timestamp}.json")), &json)?;
        Ok(())
    }

    /// Load the current spec from `.studio/specs/current.json`.
    pub fn load_current_spec(&self, project_id: &str) -> StudioResult<Spec> {
        let path = self.root.join(project_id).join(".studio/specs/current.json");
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

    /// Delete a project directory and everything in it. Irreversible.
    pub fn delete_project(&self, project_id: &str) -> StudioResult<()> {
        let dir = self.root.join(project_id);
        if !dir.exists() {
            return Err(StudioError::ProjectNotFound(project_id.into()));
        }
        let canonical_root = self.root.canonicalize()?;
        let canonical_dir = dir.canonicalize()?;
        if !canonical_dir.starts_with(&canonical_root) || canonical_dir == canonical_root {
            return Err(StudioError::PathTraversalBlocked(project_id.into()));
        }
        fs::remove_dir_all(&dir)?;
        Ok(())
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
        let canonical_base = base.canonicalize()?;
        let canonical_resolved = resolved
            .parent()
            .map(|p| {
                fs::create_dir_all(p).ok();
                p.canonicalize()
            })
            .unwrap_or_else(|| canonical_base.clone().canonicalize())
            .map_err(|_| StudioError::PathTraversalBlocked(path.into()))?;
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
    fn test_delete_project() {
        let (mgr, _dir) = make_manager();
        let project = mgr.create_project("test-proj").unwrap();
        mgr.write_file(&project.id, "main.py", "print('hi')").unwrap();
        assert!(project.dir.exists());

        mgr.delete_project(&project.id).unwrap();

        assert!(!project.dir.exists());
        let projects = mgr.list_projects().unwrap();
        assert!(!projects.iter().any(|p| p.id == project.id));
    }

    #[test]
    fn test_delete_nonexistent_project_errors() {
        let (mgr, _dir) = make_manager();
        let result = mgr.delete_project("nonexistent-id");
        assert!(result.is_err());
    }

    #[test]
    fn test_save_and_load_spec() {
        let (mgr, _dir) = make_manager();
        let project = mgr.create_project("test-proj").unwrap();
        let spec = Spec {
            agent_type: crate::spec::AgentType::Single,
            name: "test".into(),
            description: "test".into(),
            model: "gpt-4o".into(),
            system_prompt: "You are helpful.".into(),
            max_tokens: 4096,
            budget: None,
            tools: vec![],
            workflow: None,
            deploy: crate::spec::DeployMode::Cli,
            provider: crate::spec::ProviderSpec::default(),
        };
        mgr.save_spec(&project.id, &spec).unwrap();
        let loaded = mgr.load_current_spec(&project.id).unwrap();
        assert_eq!(loaded.name, "test");
        assert_eq!(loaded.agent_type, crate::spec::AgentType::Single);
    }
}
