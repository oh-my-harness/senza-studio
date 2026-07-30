use std::path::PathBuf;
use std::sync::Arc;
use studio_core::project::ProjectManager;
use studio_core::runner::Runner;

pub struct AppState {
    pub project_manager: ProjectManager,
    pub runner: Arc<Runner>,
    pub studio_api_key: String,
    pub studio_model: String,
    pub studio_base_url: Option<String>,
}

impl AppState {
    pub fn new(
        projects_root: PathBuf,
        api_key: String,
        model: String,
        base_url: Option<String>,
    ) -> Self {
        Self {
            project_manager: ProjectManager::new(projects_root),
            runner: Arc::new(Runner::new()),
            studio_api_key: api_key,
            studio_model: model,
            studio_base_url: base_url,
        }
    }
}
