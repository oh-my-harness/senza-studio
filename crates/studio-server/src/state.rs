use std::path::PathBuf;
use std::sync::Arc;
use studio_core::project::ProjectManager;
use studio_core::runner::Runner;
use crate::settings_store::{SettingsStore, StudioSettings};

pub struct AppState {
    pub project_manager: ProjectManager,
    pub runner: Arc<Runner>,
    pub settings_store: Arc<SettingsStore>,
}

impl AppState {
    pub fn new(projects_root: PathBuf, settings_path: PathBuf) -> Self {
        let settings_store = Arc::new(SettingsStore::new(settings_path));
        Self {
            project_manager: ProjectManager::new(projects_root),
            runner: Arc::new(Runner::new()),
            settings_store,
        }
    }

    pub fn settings(&self) -> StudioSettings {
        self.settings_store.get()
    }
}
