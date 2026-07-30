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
    /// Environment variables injected into user agent subprocesses.
    pub user_env_vars: Vec<(String, String)>,
}
impl AppState {
    pub fn new(
        projects_root: PathBuf,
        api_key: String,
        model: String,
        base_url: Option<String>,
    ) -> Self {
        // Build env vars for user agent subprocesses from the same key or
        // from OPENAI_API_KEY / OPENAI_API_BASE if set in the server's env.
        let openai_key = std::env::var("OPENAI_API_KEY")
            .unwrap_or_else(|_| api_key.clone());
        let openai_base = std::env::var("OPENAI_API_BASE")
            .ok()
            .or_else(|| base_url.clone());

        let mut user_env_vars = vec![("OPENAI_API_KEY".into(), openai_key)];
        if let Some(base) = openai_base {
            if !base.is_empty() {
                user_env_vars.push(("OPENAI_API_BASE".into(), base));
            }
        }

        Self {
            project_manager: ProjectManager::new(projects_root),
            runner: Arc::new(Runner::new()),
            studio_api_key: api_key,
            studio_model: model,
            studio_base_url: base_url,
            user_env_vars,
        }
    }
}
