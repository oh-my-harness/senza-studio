//! Persistent settings store — JSON file backed with parking_lot::Mutex.
//!
//! Stores LLM configuration (API key, model, base URL) that users set
//! via the Settings page, instead of requiring environment variables at startup.

use std::path::PathBuf;
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use anyhow::Result;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StudioSettings {
    #[serde(default)]
    pub api_key: String,
    #[serde(default = "default_model")]
    pub model: String,
    #[serde(default)]
    pub base_url: String,
    #[serde(default)]
    pub user_api_key: String,
    #[serde(default)]
    pub user_base_url: String,
}

fn default_model() -> String {
    "gpt-4o".into()
}

impl Default for StudioSettings {
    fn default() -> Self {
        Self {
            api_key: String::new(),
            model: default_model(),
            base_url: String::new(),
            user_api_key: String::new(),
            user_base_url: String::new(),
        }
    }
}

impl StudioSettings {
    /// API key for user agent subprocesses: prefer user_api_key, fall back to api_key.
    pub fn effective_user_api_key(&self) -> &str {
        if !self.user_api_key.is_empty() {
            &self.user_api_key
        } else {
            &self.api_key
        }
    }

    /// Base URL for user agent subprocesses: prefer user_base_url, fall back to base_url.
    pub fn effective_user_base_url(&self) -> Option<&str> {
        if !self.user_base_url.is_empty() {
            Some(&self.user_base_url)
        } else if !self.base_url.is_empty() {
            Some(&self.base_url)
        } else {
            None
        }
    }

    /// Meta-agent base URL (None = use provider default).
    pub fn meta_base_url(&self) -> Option<&str> {
        if self.base_url.is_empty() { None } else { Some(&self.base_url) }
    }

    /// Env vars to inject into user agent subprocesses.
    pub fn user_env_vars(&self) -> Vec<(String, String)> {
        let mut vars = vec![(
            "OPENAI_API_KEY".into(),
            self.effective_user_api_key().into(),
        )];
        if let Some(base) = self.effective_user_base_url() {
            vars.push(("OPENAI_API_BASE".into(), base.into()));
        }
        vars
    }
}

pub struct SettingsStore {
    path: PathBuf,
    settings: Mutex<StudioSettings>,
}

impl SettingsStore {
    pub fn new(path: impl Into<PathBuf>) -> Self {
        let path = path.into();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).ok();
        }
        let settings = std::fs::read_to_string(&path)
            .ok()
            .and_then(|text| serde_json::from_str::<StudioSettings>(&text).ok())
            .unwrap_or_default();
        Self {
            path,
            settings: Mutex::new(settings),
        }
    }

    pub fn get(&self) -> StudioSettings {
        self.settings.lock().clone()
    }

    pub fn replace(&self, settings: StudioSettings) -> Result<StudioSettings> {
        let mut guard = self.settings.lock();
        *guard = settings.clone();
        std::fs::write(&self.path, serde_json::to_string_pretty(&settings)?)?;
        Ok(settings)
    }

    pub fn update(&self, patch: Value) -> Result<StudioSettings> {
        let current = serde_json::to_value(&*self.settings.lock())?;
        let merged = merge_json(current, patch);
        let settings: StudioSettings = serde_json::from_value(merged)?;
        self.replace(settings)
    }
}

fn merge_json(base: Value, patch: Value) -> Value {
    match (base, patch) {
        (Value::Object(mut base), Value::Object(patch)) => {
            for (key, value) in patch {
                if let Some(existing) = base.remove(&key) {
                    base.insert(key, merge_json(existing, value));
                } else {
                    base.insert(key, value);
                }
            }
            Value::Object(base)
        }
        (_, patch) => patch,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn settings_store_persists_and_reloads() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("settings.json");
        let store = SettingsStore::new(&path);
        store.replace(StudioSettings {
            api_key: "sk-test".into(),
            model: "gpt-4o-mini".into(),
            ..Default::default()
        }).unwrap();

        let reloaded = SettingsStore::new(&path);
        assert_eq!(reloaded.get().api_key, "sk-test");
        assert_eq!(reloaded.get().model, "gpt-4o-mini");
    }

    #[test]
    fn effective_user_api_key_falls_back() {
        let s = StudioSettings {
            api_key: "meta-key".into(),
            user_api_key: String::new(),
            ..Default::default()
        };
        assert_eq!(s.effective_user_api_key(), "meta-key");

        let s2 = StudioSettings {
            api_key: "meta-key".into(),
            user_api_key: "user-key".into(),
            ..Default::default()
        };
        assert_eq!(s2.effective_user_api_key(), "user-key");
    }

    #[test]
    fn user_env_vars_built_correctly() {
        let s = StudioSettings {
            api_key: "sk-123".into(),
            base_url: "https://api.example.com".into(),
            ..Default::default()
        };
        let vars = s.user_env_vars();
        assert_eq!(vars.len(), 2);
        assert_eq!(vars[0], ("OPENAI_API_KEY".into(), "sk-123".into()));
        assert_eq!(vars[1], ("OPENAI_API_BASE".into(), "https://api.example.com".into()));
    }

    #[test]
    fn update_merges_patch() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("settings.json");
        let store = SettingsStore::new(&path);
        store.update(serde_json::json!({ "api_key": "sk-new" })).unwrap();
        assert_eq!(store.get().api_key, "sk-new");
        assert_eq!(store.get().model, "gpt-4o"); // default preserved
    }
}
