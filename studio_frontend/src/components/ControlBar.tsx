// studio_frontend/src/components/ControlBar.tsx
import { useState } from "react";
import { useStudioStore } from "../store";
import { api } from "../api";

export default function ControlBar({ projectId }: { projectId: string }) {
  const ws = useStudioStore((s) => s.ws);
  const status = useStudioStore((s) => s.status);
  const resetPlay = useStudioStore((s) => s.resetPlay);
  const setStatus = useStudioStore((s) => s.setStatus);
  const runFinishedState = useStudioStore((s) => s.runFinishedState);
  const enginePaused = useStudioStore((s) => s.enginePaused);
  const pausedStepId = useStudioStore((s) => s.pausedStepId);
  const setPlayStartPaused = useStudioStore((s) => s.setPlayStartPaused);
  const [exporting, setExporting] = useState(false);
  const addLog = useStudioStore((s) => s.addLog);

  const playing = status === "playing";
  // Resume/Step 只在"手动暂停"时露出——checker 审批暂停已经有 GameView
  // 自己的审批横幅了，同时露出这两套"继续"控制会让人不知道点哪个
  // （点 Resume/Step 对 checker 暂停也不会出错，只是它会立刻因为还没有
  // 决定而重新暂停，纯属多余，索性藏起来）。
  const showResumeStep = playing && enginePaused && !pausedStepId;
  const showPause = playing && !enginePaused && !runFinishedState;

  const runExport = async () => {
    setExporting(true);
    try {
      const result = await api.exportProject(projectId);
      addLog("info", `已导出到 ${result.path}`);
      if (result.note) addLog("error", result.note);
      window.alert(
        `已导出到：\n${result.path}` +
          (result.note ? `\n\n注意：${result.note}` : ""),
      );
    } catch (e) {
      // fetchJson 抛出来的是 `400: {"detail":"..."}`——把 detail 抠出来，
      // 别把一串 JSON 甩给用户。导出失败最常见的原因就是 spec 有问题
      // （组件名写错之类），那句话本身是能看懂的。
      const raw = e instanceof Error ? e.message : String(e);
      let detail = raw;
      const brace = raw.indexOf("{");
      if (brace >= 0) {
        try {
          detail = JSON.parse(raw.slice(brace)).detail ?? raw;
        } catch {
          /* 解析不出来就用原文 */
        }
      }
      addLog("error", `导出失败：${detail}`);
      window.alert(`导出失败：\n${detail}`);
    } finally {
      setExporting(false);
    }
  };

  // Play 只负责**进入运行视图**，不再自己收种子输入——入口表单搬进了 Game
  // view，因为那一屏就是最终用户打开导出产品看到的第一屏，得能在 Studio 里
  // 预览到（以前它在 Studio 里根本没法看：控制条这条窄栏和产品表单长得毫无
  // 关系）。真正的 play 消息由那个表单发。
  //
  // startPaused 是"从头单步"，调试用，不属于产品界面，所以按钮留在这儿，
  // 标志经 store 传给 Game view。
  const play = (startPaused = false) => {
    if (!ws || playing) return;
    setPlayStartPaused(startPaused);
    resetPlay();
    setStatus("playing");
  };

  const stop = () => {
    if (!ws || !playing) return;
    ws.send(JSON.stringify({ type: "stop" }));
  };

  const pause = () => {
    if (!ws || !showPause) return;
    ws.send(JSON.stringify({ type: "pause" }));
  };

  const resume = () => {
    if (!ws || !showResumeStep) return;
    ws.send(JSON.stringify({ type: "resume" }));
  };

  const step = () => {
    if (!ws || !showResumeStep) return;
    ws.send(JSON.stringify({ type: "step" }));
  };

  return (
    <div className="border-b border-gray-200 bg-gray-50">
      <div className="flex items-center gap-2 px-4 py-2">
        <button
          onClick={() => play(false)}
          disabled={playing}
          className="rounded-lg bg-green-500 px-4 py-1.5 text-sm text-white hover:bg-green-600 disabled:opacity-50"
        >
          ▶ Play
        </button>
        <button
          onClick={() => play(true)}
          disabled={playing}
          title="从第一步开始就暂停，逐步点 Step 往下走"
          className="rounded-lg border border-gray-300 px-4 py-1.5 text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-50"
        >
          ⏸▶ Play Paused
        </button>
        <button
          onClick={stop}
          disabled={!playing}
          className="rounded-lg bg-red-500 px-4 py-1.5 text-sm text-white hover:bg-red-600 disabled:opacity-50"
        >
          ■ Stop
        </button>
        <button
          onClick={runExport}
          disabled={playing || exporting}
          title={playing ? "运行中不能导出" : "打包成不依赖 Studio 的独立项目"}
          className="rounded-lg border border-gray-300 px-4 py-1.5 text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-50"
        >
          {exporting ? "导出中…" : "⬇ 导出"}
        </button>
        {showPause && (
          <button
            onClick={pause}
            className="rounded-lg bg-amber-500 px-4 py-1.5 text-sm text-white hover:bg-amber-600"
          >
            ⏸ Pause
          </button>
        )}
        {showResumeStep && (
          <>
            <button
              onClick={resume}
              className="rounded-lg bg-green-500 px-4 py-1.5 text-sm text-white hover:bg-green-600"
            >
              ▶ Resume
            </button>
            <button
              onClick={step}
              className="rounded-lg border border-gray-300 px-4 py-1.5 text-sm text-gray-700 hover:bg-gray-100"
            >
              ⏭ Step
            </button>
          </>
        )}
        {playing && (
          <span className="text-xs text-gray-500 ml-2">
            {runFinishedState === "succeeded"
              ? "✅ 已完成 — 点击 Stop 返回编辑"
              : runFinishedState === "failed"
              ? "❌ 运行失败 — 点击 Stop 返回编辑"
              : runFinishedState
              ? `已结束 (${runFinishedState}) — 点击 Stop 返回编辑`
              : enginePaused && !pausedStepId
              ? "⏸ 已暂停 — 点击 Resume 继续或 Step 单步执行"
              : "运行中…"}
          </span>
        )}
      </div>
    </div>
  );
}
