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
  const [pendingFields, setPendingFields] = useState<string[] | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  // 记住这次 Play 是不是"从头单步"发起的——entry-input 对话框跟正常 Play
  // 共用，"开始运行"按钮点下去的时候要知道该不该带上 start_paused。
  const [pendingStartPaused, setPendingStartPaused] = useState(false);

  const playing = status === "playing";
  // Resume/Step 只在"手动暂停"时露出——checker 审批暂停已经有 GameView
  // 自己的审批横幅了，同时露出这两套"继续"控制会让人不知道点哪个
  // （点 Resume/Step 对 checker 暂停也不会出错，只是它会立刻因为还没有
  // 决定而重新暂停，纯属多余，索性藏起来）。
  const showResumeStep = playing && enginePaused && !pausedStepId;
  const showPause = playing && !enginePaused && !runFinishedState;

  // Play 前先看看入口 step 需要哪些种子输入（比如 customer_message）——
  // Studio 不接真实生产流量，没有真人填这些字段，prompt_template 里的
  // {{field}} 占位符就永远是空的。startPaused 为 true 时（"从头单步"按钮）
  // 记下来，entry-input 对话框的"开始运行"按钮最终会带上这个标志。
  const play = async (startPaused = false) => {
    if (!ws || playing) return;
    setPendingStartPaused(startPaused);
    const { fields } = await api.getEntryInputs(projectId);
    if (fields.length === 0) {
      startPlay({}, startPaused);
      return;
    }
    setValues(Object.fromEntries(fields.map((f) => [f, ""])));
    setPendingFields(fields);
  };

  const startPlay = (inputs: Record<string, string>, startPaused = pendingStartPaused) => {
    if (!ws) return;
    resetPlay();
    setStatus("playing");
    ws.send(JSON.stringify({ type: "play", inputs, start_paused: startPaused }));
    setPendingFields(null);
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
      {pendingFields && (
        <div className="px-4 pb-3 space-y-2 border-t border-gray-200 pt-3">
          <div className="text-xs text-gray-500">
            填写测试用的初始输入（模拟真实触发数据）：
            {pendingStartPaused && (
              <span className="text-amber-600"> （将在第一步后暂停，逐步执行）</span>
            )}
          </div>
          {pendingFields.map((field) => (
            <div key={field} className="flex items-center gap-2">
              <label className="text-xs text-gray-600 w-40 shrink-0">{field}</label>
              <input
                value={values[field] || ""}
                onChange={(e) =>
                  setValues((v) => ({ ...v, [field]: e.target.value }))
                }
                autoFocus={field === pendingFields[0]}
                className="flex-1 rounded border border-gray-300 px-2 py-1 text-sm"
                placeholder={`${field} 的示例值…`}
              />
            </div>
          ))}
          <div className="flex gap-2 pt-1">
            <button
              onClick={() => startPlay(values)}
              className="rounded-lg bg-green-500 px-3 py-1 text-sm text-white hover:bg-green-600"
            >
              开始运行
            </button>
            <button
              onClick={() => setPendingFields(null)}
              className="rounded-lg border border-gray-300 px-3 py-1 text-sm text-gray-600 hover:bg-gray-100"
            >
              取消
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
