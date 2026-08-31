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
  const [pendingFields, setPendingFields] = useState<string[] | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});

  const playing = status === "playing";

  // Play 前先看看入口 step 需要哪些种子输入（比如 customer_message）——
  // Studio 不接真实生产流量，没有真人填这些字段，prompt_template 里的
  // {{field}} 占位符就永远是空的。
  const play = async () => {
    if (!ws || playing) return;
    const { fields } = await api.getEntryInputs(projectId);
    if (fields.length === 0) {
      startPlay({});
      return;
    }
    setValues(Object.fromEntries(fields.map((f) => [f, ""])));
    setPendingFields(fields);
  };

  const startPlay = (inputs: Record<string, string>) => {
    if (!ws) return;
    resetPlay();
    setStatus("playing");
    ws.send(JSON.stringify({ type: "play", inputs }));
    setPendingFields(null);
  };

  const stop = () => {
    if (!ws || !playing) return;
    ws.send(JSON.stringify({ type: "stop" }));
  };

  return (
    <div className="border-b border-gray-200 bg-gray-50">
      <div className="flex items-center gap-2 px-4 py-2">
        <button
          onClick={play}
          disabled={playing}
          className="rounded-lg bg-green-500 px-4 py-1.5 text-sm text-white hover:bg-green-600 disabled:opacity-50"
        >
          ▶ Play
        </button>
        <button
          onClick={stop}
          disabled={!playing}
          className="rounded-lg bg-red-500 px-4 py-1.5 text-sm text-white hover:bg-red-600 disabled:opacity-50"
        >
          ■ Stop
        </button>
        {playing && (
          <span className="text-xs text-gray-500 ml-2">
            {runFinishedState === "succeeded"
              ? "✅ 已完成 — 点击 Stop 返回编辑"
              : runFinishedState === "failed"
              ? "❌ 运行失败 — 点击 Stop 返回编辑"
              : runFinishedState
              ? `已结束 (${runFinishedState}) — 点击 Stop 返回编辑`
              : "运行中…"}
          </span>
        )}
      </div>
      {pendingFields && (
        <div className="px-4 pb-3 space-y-2 border-t border-gray-200 pt-3">
          <div className="text-xs text-gray-500">
            填写测试用的初始输入（模拟真实触发数据）：
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
