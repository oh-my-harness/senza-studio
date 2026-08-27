// studio_frontend/src/App.tsx
import { useEffect, useState } from "react";
import { useStudioStore } from "./store";
import { api } from "./api";
import ChatPanel from "./components/ChatPanel";
import Canvas from "./components/Canvas";
import Inspector from "./components/Inspector";
import StatusBar from "./components/StatusBar";
import type { ProjectMeta } from "./types";

export default function App() {
  const [projectId, setProjectId] = useState<string | null>(null);
  const setProject = useStudioStore((s) => s.setProject);
  const setSpec = useStudioStore((s) => s.setSpec);
  const setMessages = useStudioStore((s) => s.setMessages);
  const [projects, setProjects] = useState<ProjectMeta[]>([]);
  const [newName, setNewName] = useState("");

  // 加载项目列表
  useEffect(() => {
    api.listProjects().then(setProjects).catch(console.error);
  }, []);

  // 打开项目
  const openProject = async (id: string) => {
    const meta = await api.getProject(id);
    const spec = await api.getSpec(id);
    const messages = await api.getMessages(id);
    setProject(meta);
    setSpec(spec);
    setMessages(messages);
    setProjectId(id);
  };

  // 创建项目
  const createProject = async () => {
    if (!newName.trim()) return;
    const { id } = await api.createProject(newName);
    setNewName("");
    const meta = await api.getProject(id);
    const spec = await api.getSpec(id);
    setProject(meta);
    setSpec(spec);
    setMessages([]);
    setProjectId(id);
  };

  if (!projectId) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center bg-gray-50 gap-6">
        <h1 className="text-2xl font-bold text-gray-700">Senza Studio</h1>
        <div className="flex gap-2">
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && createProject()}
            placeholder="项目名称…"
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm"
          />
          <button
            onClick={createProject}
            className="rounded-lg bg-blue-500 px-4 py-2 text-sm text-white hover:bg-blue-600"
          >
            创建项目
          </button>
        </div>
        {projects.length > 0 && (
          <div className="w-96">
            <h2 className="text-sm text-gray-500 mb-2">已有项目</h2>
            <div className="space-y-1">
              {projects.map((p) => (
                <button
                  key={p.id}
                  onClick={() => openProject(p.id)}
                  className="block w-full text-left rounded-lg border border-gray-200 px-4 py-2 text-sm hover:bg-gray-100"
                >
                  {p.name}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="h-full w-full flex flex-col">
      <div className="flex-1 flex overflow-hidden">
        <ChatPanel projectId={projectId} />
        <Canvas />
        <Inspector projectId={projectId} />
      </div>
      <StatusBar />
    </div>
  );
}
