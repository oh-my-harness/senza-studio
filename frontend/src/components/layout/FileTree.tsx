import { useProjectStore } from '../../store/projectStore';
import { useEffect } from 'react';

export function FileTree() {
  const project = useProjectStore((s) => s.project);
  const files = useProjectStore((s) => s.files);
  const loadFiles = useProjectStore((s) => s.loadFiles);
  const setActiveTab = useProjectStore((s) => s.setActiveTab);

  useEffect(() => {
    if (project) loadFiles();
  }, [project, loadFiles]);

  return (
    <div className="w-48 border-r overflow-y-auto">
      <div className="px-2 py-1 text-xs text-muted-foreground">FILES</div>
      {Object.keys(files).map((path) => (
        <button
          key={path}
          onClick={() => setActiveTab('code')}
          className="block w-full text-left px-3 py-1 text-sm hover:bg-accent"
        >
          {path}
        </button>
      ))}
    </div>
  );
}
