import { useState } from 'react';
import { useProjectStore } from '../../store/projectStore';
import { api } from '../../lib/api';
import { FolderOpen, Play, Code2, Library, Settings, MessageSquare, Waypoints, GitGraph } from 'lucide-react';
import { ExamplePicker } from '../examples/ExamplePicker';
import { SettingsPage } from '../settings/SettingsPage';

export function TopBar() {
  const project = useProjectStore((s) => s.project);
  const setProject = useProjectStore((s) => s.setProject);
  const setActiveTab = useProjectStore((s) => s.setActiveTab);
  const currentSpec = useProjectStore((s) => s.currentSpec);
  const isWorkflow = currentSpec?.agent_type?.includes('workflow') ?? false;
  const [showExamples, setShowExamples] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  const createProject = async () => {
    const name = prompt('Project name?');
    if (!name) return;
    const p = await api.createProject(name);
    setProject(p);
  };

  return (
    <div className="flex items-center gap-4 px-4 py-2 border-b bg-background">
      <span className="font-semibold">{project?.name || 'Senza Studio'}</span>
      <button onClick={createProject} className="text-sm flex items-center gap-1 hover:bg-accent px-2 py-1 rounded">
        <FolderOpen size={16} /> New
      </button>
      <button onClick={() => setShowExamples(true)} className="text-sm flex items-center gap-1 hover:bg-accent px-2 py-1 rounded">
        <Library size={16} /> Examples
      </button>
      <div className="flex-1" />
      <button onClick={() => setActiveTab('converse')} className="text-sm flex items-center gap-1 hover:bg-accent px-2 py-1 rounded">
        <MessageSquare size={16} /> Chat
      </button>
      <button onClick={() => setActiveTab('code')} className="text-sm flex items-center gap-1 hover:bg-accent px-2 py-1 rounded">
        <Code2 size={16} /> Code
      </button>
      <button onClick={() => setActiveTab('run')} className="text-sm flex items-center gap-1 hover:bg-accent px-2 py-1 rounded">
        <Play size={16} /> Run
      </button>
      {isWorkflow && (
        <button onClick={() => setActiveTab('dag')} className="text-sm flex items-center gap-1 hover:bg-accent px-2 py-1 rounded">
          <GitGraph size={16} /> DAG
        </button>
      )}
      <button onClick={() => setActiveTab('trace')} className="text-sm flex items-center gap-1 hover:bg-accent px-2 py-1 rounded">
        <Waypoints size={16} /> Trace
      </button>
      <button onClick={() => setShowSettings(true)} className="text-sm flex items-center gap-1 hover:bg-accent px-2 py-1 rounded">
        <Settings size={16} /> Settings
      </button>
      {showExamples && <ExamplePicker onClose={() => setShowExamples(false)} />}
      {showSettings && <SettingsPage onClose={() => setShowSettings(false)} />}
    </div>
  );
}
