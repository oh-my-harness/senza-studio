import { useEffect } from 'react';
import { format } from 'timeago.js';
import { Trash2 } from 'lucide-react';
import { useProjectStore } from '../../store/projectStore';
import { useProjectListStore } from '../../store/projectListStore';
import type { ProjectMeta } from '../../types';

export function ProjectList() {
  const project = useProjectStore((s) => s.project);
  const openProject = useProjectStore((s) => s.openProject);
  const projects = useProjectListStore((s) => s.projects);
  const loading = useProjectListStore((s) => s.loading);
  const loadProjects = useProjectListStore((s) => s.loadProjects);
  const deleteProject = useProjectListStore((s) => s.deleteProject);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  const handleDelete = (e: React.MouseEvent, p: ProjectMeta) => {
    e.stopPropagation();
    if (!window.confirm(`Delete "${p.name}"? This cannot be undone.`)) return;
    deleteProject(p.id);
  };

  return (
    <div className="border-b shrink-0">
      <div className="px-2 py-1 text-xs text-muted-foreground">PROJECTS</div>
      {loading && projects.length === 0 && (
        <div className="px-3 py-2 text-sm text-muted-foreground">Loading…</div>
      )}
      {!loading && projects.length === 0 && (
        <div className="px-3 py-2 text-xs text-muted-foreground">
          No projects yet — click New to create one.
        </div>
      )}
      <div className="max-h-48 overflow-y-auto">
        {projects.map((p) => (
          <button
            key={p.id}
            onClick={() => openProject(p)}
            className={`group flex w-full items-center justify-between gap-1 px-3 py-1.5 text-left text-sm hover:bg-accent ${
              p.id === project?.id ? 'bg-accent' : ''
            }`}
          >
            <span className="min-w-0 flex-1">
              <span className="block truncate">{p.name}</span>
              <span className="block text-[0.625rem] text-muted-foreground">
                {format(p.created_at)}
              </span>
            </span>
            <span
              onClick={(e) => handleDelete(e, p)}
              className="shrink-0 rounded p-1 text-muted-foreground opacity-0 hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100"
              title="Delete project"
            >
              <Trash2 size={14} />
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
