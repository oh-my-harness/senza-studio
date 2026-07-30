import { useState, useEffect } from 'react';
import { api } from '../../lib/api';
import { useProjectStore } from '../../store/projectStore';
import type { ExampleProject } from '../../types';

export function ExamplePicker({ onClose }: { onClose: () => void }) {
  const [examples, setExamples] = useState<ExampleProject[]>([]);
  const [loading, setLoading] = useState(true);
  const setProject = useProjectStore((s) => s.setProject);
  const loadFiles = useProjectStore((s) => s.loadFiles);
  const setActiveTab = useProjectStore((s) => s.setActiveTab);

  useEffect(() => {
    api.listExamples().then((exs) => {
      setExamples(exs);
      setLoading(false);
    });
  }, []);

  const handleSelect = async (ex: ExampleProject) => {
    const name = prompt('Project name?', ex.name);
    if (!name) return;
    const res = await api.createFromExample(ex.id, name);
    const project = await api.getProject(res.project_id);
    setProject(project);
    await loadFiles();
    setActiveTab('code');
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-background rounded-lg p-4 max-w-2xl w-full max-h-[80vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-semibold mb-4">Example Projects</h2>
        {loading ? (
          <p className="text-muted-foreground">Loading...</p>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            {examples.map((ex) => (
              <button
                key={ex.id}
                onClick={() => handleSelect(ex)}
                className="text-left p-3 border rounded hover:bg-accent"
              >
                <div className="font-medium text-sm">{ex.name}</div>
                <div className="text-xs text-muted-foreground">{ex.description}</div>
                <div className="flex gap-1 mt-1">
                  {ex.tags.map((tag) => (
                    <span key={tag} className="text-xs bg-muted px-1 rounded">{tag}</span>
                  ))}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
