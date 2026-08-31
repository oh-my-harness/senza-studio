// studio_frontend/src/App.tsx
import { useEffect, useState } from "react";
import { useStudioStore } from "./store";
import { api } from "./api";
import ChatPanel from "./components/ChatPanel";
import Canvas from "./components/Canvas";
import ControlBar from "./components/ControlBar";
import GameView from "./components/GameView";
import Inspector from "./components/Inspector";
import StatusBar from "./components/StatusBar";
import type { ProjectMeta } from "./types";

export default function App() {
  const [projectId, setProjectId] = useState<string | null>(null);
  const project = useStudioStore((s) => s.project);
  const setProject = useStudioStore((s) => s.setProject);
  const setSpec = useStudioStore((s) => s.setSpec);
  const setMessages = useStudioStore((s) => s.setMessages);
  const status = useStudioStore((s) => s.status);
  const setStatus = useStudioStore((s) => s.setStatus);
  const selectStep = useStudioStore((s) => s.selectStep);
  const resetPlay = useStudioStore((s) => s.resetPlay);
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

  // 返回项目列表——清空当前项目相关状态，避免切换项目时残留上一个项目的画布/对话
  const backToProjects = () => {
    setProjectId(null);
    setProject(null);
    setSpec({ stages: [] });
    setMessages([]);
    selectStep(null);
    resetPlay();
    setStatus("idle");
    api.listProjects().then(setProjects).catch(console.error);
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

  const playing = status === "playing";

  return (
    <div className="h-full w-full flex flex-col">
      <div className="flex items-center gap-3 px-4 py-2 border-b border-gray-200 bg-white">
        <button
          onClick={backToProjects}
          disabled={playing}
          title={playing ? "运行中无法切换项目" : "返回项目列表"}
          className="text-sm text-gray-600 hover:text-gray-900 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          ← 返回项目列表
        </button>
        {project && (
          <span className="text-sm font-medium text-gray-700">{project.name}</span>
        )}
      </div>
      <ControlBar />
      <div className="flex-1 flex overflow-hidden">
        <ChatPanel projectId={projectId} collapsed={playing} />
        {playing && <GameView />}
        <Canvas />
        <Inspector projectId={projectId} />
      </div>
      <StatusBar />
    </div>
  );
}
