import { create } from 'zustand';
import type { ProjectMeta } from '../types';
import { api } from '../lib/api';
import { useProjectStore } from './projectStore';

interface ProjectListStore {
  projects: ProjectMeta[];
  loading: boolean;
  error: string | null;
  loadProjects: () => Promise<void>;
  deleteProject: (id: string) => Promise<void>;
}

export const useProjectListStore = create<ProjectListStore>((set, get) => ({
  projects: [],
  loading: false,
  error: null,

  loadProjects: async () => {
    set({ loading: true, error: null });
    try {
      const projects = await api.listProjects();
      set({ projects, loading: false });
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e), loading: false });
    }
  },

  deleteProject: async (id) => {
    await api.deleteProject(id);
    set({ projects: get().projects.filter((p) => p.id !== id) });

    const current = useProjectStore.getState().project;
    if (current?.id === id) {
      useProjectStore.setState({
        project: null,
        files: {},
        dirtyFiles: new Set(),
        conversation: [],
        conversationStatus: 'idle',
        currentSpec: null,
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
  },
}));
