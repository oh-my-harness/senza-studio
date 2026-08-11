import { useState, useEffect, useRef } from 'react';
import { useProjectStore } from '../../store/projectStore';
import { useProjectListStore } from '../../store/projectListStore';
import { api } from '../../lib/api';
import { X, Check, Brain, Globe, FolderOpen } from 'lucide-react';

interface StudioSettings {
  api_key: string;
  model: string;
  base_url: string;
  user_api_key: string;
  user_base_url: string;
  working_directory: string;
}

export function SettingsPage({ onClose }: { onClose: () => void }) {
  const [settings, setSettings] = useState<StudioSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const setActiveTab = useProjectStore((s) => s.setActiveTab);
  const loadProjects = useProjectListStore((s) => s.loadProjects);
  const loadedWorkingDir = useRef<string | null>(null);

  useEffect(() => {
    fetch('/api/settings')
      .then((r) => r.json())
      .then((s) => {
        setSettings(s);
        loadedWorkingDir.current = s.working_directory ?? '';
      })
      .catch((e) => setError(e.message));
  }, []);

  const handleSave = async () => {
    if (!settings) return;
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const res = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.error ?? `HTTP ${res.status}`);
      }
      const updated = await res.json();
      setSettings(updated);

      // Working directory changed — the project list (and whatever project
      // is currently open) now points at a different filesystem location.
      // Refresh the list and drop the open project rather than silently
      // leaving stale state visible: it almost certainly doesn't resolve
      // under the new root.
      if (updated.working_directory !== loadedWorkingDir.current) {
        loadedWorkingDir.current = updated.working_directory;
        loadProjects();
        useProjectStore.setState({
          project: null,
          files: {},
          dirtyFiles: new Set(),
          conversation: [],
          conversationStatus: 'idle',
          currentSpec: null,
          pendingDiff: null,
          generating: false,
          generateError: null,
          activeRunId: null,
          runStatus: 'idle',
          runView: 'chat',
          runMessages: [],
          liveEvents: [],
          stepStates: {},
          activeStepId: null,
          activeTab: 'converse',
        });
      }

      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  if (!settings) {
    return (
      <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
        <div className="bg-background rounded-lg p-4">Loading settings…</div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-background rounded-lg p-6 max-w-lg w-full max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Settings</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X size={20} />
          </button>
        </div>

        {/* Meta-agent config */}
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-3 text-sm font-medium">
            <Brain size={16} /> Meta-Agent Configuration
          </div>
          <p className="text-xs text-muted-foreground mb-3">
            Used by the Converser and Coding Agent. These run on the Rust runtime.
          </p>
          <Field
            label="API Key"
            type="password"
            value={settings.api_key}
            onChange={(v) => setSettings({ ...settings, api_key: v })}
            placeholder="sk-…"
          />
          <Field
            label="Model"
            value={settings.model}
            onChange={(v) => setSettings({ ...settings, model: v })}
            placeholder="gpt-4o"
          />
          <Field
            label="Base URL (optional)"
            value={settings.base_url}
            onChange={(v) => setSettings({ ...settings, base_url: v })}
            placeholder="https://api.openai.com"
          />
        </div>

        {/* User agent config */}
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-3 text-sm font-medium">
            <Globe size={16} /> User Agent Configuration
          </div>
          <p className="text-xs text-muted-foreground mb-3">
            Used by generated Senza Python projects when running in Studio mode.
            Leave empty to fall back to the meta-agent key above.
          </p>
          <Field
            label="API Key (optional)"
            type="password"
            value={settings.user_api_key}
            onChange={(v) => setSettings({ ...settings, user_api_key: v })}
            placeholder="Leave empty to use meta-agent key"
          />
          <Field
            label="Base URL (optional)"
            value={settings.user_base_url}
            onChange={(v) => setSettings({ ...settings, user_base_url: v })}
            placeholder="Leave empty to use meta-agent base URL"
          />
        </div>

        {/* Project storage */}
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-3 text-sm font-medium">
            <FolderOpen size={16} /> Project Storage
          </div>
          <p className="text-xs text-muted-foreground mb-3">
            Where new projects are created. Each project gets its own folder
            named after the project. Leave empty to use the server's default.
            Existing projects stay where they are — this only affects new ones
            and where the project list looks from now on.
          </p>
          <Field
            label="Working Directory (optional)"
            value={settings.working_directory}
            onChange={(v) => setSettings({ ...settings, working_directory: v })}
            placeholder="Default: ./projects (relative to server)"
          />
        </div>

        {error && (
          <div className="text-destructive text-sm mb-3">{error}</div>
        )}

        <div className="flex items-center gap-3">
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm disabled:opacity-50 flex items-center gap-1"
          >
            {saved ? <Check size={16} /> : null}
            {saving ? 'Saving…' : saved ? 'Saved' : 'Save'}
          </button>
          <button
            onClick={() => { onClose(); setActiveTab('converse'); }}
            className="px-4 py-2 border rounded-lg text-sm"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  type = 'text',
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <div className="mb-3">
      <label className="block text-xs text-muted-foreground mb-1">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full px-3 py-2 bg-[var(--input)] border rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-ring"
      />
    </div>
  );
}
