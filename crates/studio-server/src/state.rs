use std::path::PathBuf;
use std::sync::Arc;
use studio_core::project::ProjectManager;
use studio_core::runner::Runner;
use crate::settings_store::{SettingsStore, StudioSettings};

pub struct AppState {
    /// Fallback projects root, used when settings' `working_directory` is
    /// unset (empty). Set once at server startup from
    /// `SENZA_STUDIO_PROJECTS_DIR`/`./projects`.
    default_projects_root: PathBuf,
    pub runner: Arc<Runner>,
    pub settings_store: Arc<SettingsStore>,
}

impl AppState {
    pub fn new(projects_root: PathBuf, settings_path: PathBuf) -> Self {
        let settings_store = Arc::new(SettingsStore::new(settings_path));
        Self {
            default_projects_root: projects_root,
            runner: Arc::new(Runner::new()),
            settings_store,
        }
    }

    pub fn settings(&self) -> StudioSettings {
        self.settings_store.get()
    }

    /// The effective projects root: settings' `working_directory` if set,
    /// else the server's startup default. Re-read fresh on every call, same
    /// "no stale caching" pattern as `settings()` — so a Settings change
    /// takes effect immediately, without a server restart.
    pub fn projects_root(&self) -> PathBuf {
        let dir = self.settings_store.get().working_directory;
        if dir.trim().is_empty() {
            self.default_projects_root.clone()
        } else {
            PathBuf::from(dir.trim())
        }
    }

    /// Construct a `ProjectManager` pointed at the current effective
    /// projects root. Cheap — `ProjectManager::new` is a zero-cost
    /// constructor (no I/O), so building one fresh per call requires no
    /// `RwLock`/interior mutability.
    pub fn project_manager(&self) -> ProjectManager {
        ProjectManager::new(self.projects_root())
    }
}
