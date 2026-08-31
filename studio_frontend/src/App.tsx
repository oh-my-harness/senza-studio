// studio_frontend/src/App.tsx
import { useEffect, useState } from "react";
import { Group, Panel, Separator } from "react-resizable-panels";
import { useStudioStore } from "./store";
import { api } from "./api";
import ChatPanel from "./components/ChatPanel";
import Canvas from "./components/Canvas";
import ControlBar from "./components/ControlBar";
import GameView from "./components/GameView";
import Inspector from "./components/Inspector";
import BottomPanel from "./components/BottomPanel";
import StatusBar from "./components/StatusBar";
import type { ProjectMeta } from "./types";
import { splitToolCalls } from "./utils";

export default function App() {
  const [projectId, setProjectId] = useState<string | null>(null);
  const project = useStudioStore((s) => s.project);
  const setProject = useStudioStore((s) => s.setProject);
  const setSpec = useStudioStore((s) => s.setSpec);
  const setMessages = useStudioStore((s) => s.setMessages);
  const setToolCalls = useStudioStore((s) => s.setToolCalls);
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
    const { chat, tools } = splitToolCalls(messages);
    setProject(meta);
    setSpec(spec);
    setMessages(chat);
    setToolCalls(tools);
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
    setToolCalls([]);
    setProjectId(id);
  };

  // 删除项目——不可撤销，先确认
  const deleteProject = async (id: string, name: string) => {
    if (!window.confirm(`确定要删除项目"${name}"吗？此操作不可撤销。`)) return;
    try {
      await api.deleteProject(id);
      setProjects((prev) => prev.filter((p) => p.id !== id));
    } catch (err) {
      console.error(err);
      window.alert("删除失败，请重试");
    }
  };

  // 返回项目列表——清空当前项目相关状态，避免切换项目时残留上一个项目的画布/对话
  const backToProjects = () => {
    setProjectId(null);
    setProject(null);
    setSpec({ stages: [] });
    setMessages([]);
    setToolCalls([]);
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
                <div
                  key={p.id}
                  className="flex items-center rounded-lg border border-gray-200 hover:bg-gray-100"
                >
                  <button
                    onClick={() => openProject(p.id)}
                    className="flex-1 text-left px-4 py-2 text-sm"
                  >
                    {p.name}
                  </button>
                  <button
                    onClick={() => deleteProject(p.id, p.name)}
                    title="删除项目"
                    className="px-3 py-2 text-gray-400 hover:text-red-600"
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth={1.5}
                      className="w-4 h-4"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0"
                      />
                    </svg>
                  </button>
                </div>
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
      <ControlBar projectId={projectId} />
      <Group orientation="horizontal" className="flex-1 min-h-0">
        <Panel id="chat" defaultSize={playing ? "20%" : "25%"} minSize="15%">
          <ChatPanel projectId={projectId} />
        </Panel>
        <Separator className="w-1 bg-gray-200 hover:bg-blue-400 transition-colors cursor-col-resize" />
        {playing && (
          <>
            <Panel id="game" defaultSize="25%" minSize="15%">
              <GameView />
            </Panel>
            <Separator className="w-1 bg-gray-200 hover:bg-blue-400 transition-colors cursor-col-resize" />
          </>
        )}
        <Panel id="canvas" defaultSize={playing ? "35%" : "50%"} minSize="20%">
          <Canvas />
        </Panel>
        <Separator className="w-1 bg-gray-200 hover:bg-blue-400 transition-colors cursor-col-resize" />
        <Panel id="inspector" defaultSize="20%" minSize="15%">
          <Inspector projectId={projectId} />
        </Panel>
      </Group>
      <BottomPanel />
      <StatusBar />
    </div>
  );
}
