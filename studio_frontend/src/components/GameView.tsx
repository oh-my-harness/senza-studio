// studio_frontend/src/components/GameView.tsx
import { useEffect, useRef, useState } from "react";
import { useStudioStore } from "../store";
import Markdown from "./Markdown";

const STATUS_LABEL: Record<string, string> = {
  running: "运行中…",
  done: "完成",
  error: "出错",
};

// checker step 的审批选项就是它自己的 next_on_* 标签（跟 play.py 的
// build_route_maps 读法一致）——不是写死的"批准/拒绝"，spec 作者可以自己
// 定义任意标签（比如 approve/escalate/reject）。
function routeLabelsFor(spec: { stages: { name: string; [k: string]: unknown }[] }, stepName: string): string[] {
  const stage = spec.stages.find((s) => s.name === stepName);
  if (!stage) return [];
  return Object.keys(stage)
    .filter((k) => k.startsWith("next_on_") && typeof stage[k] === "string")
    .map((k) => k.slice("next_on_".length));
}

export default function GameView() {
  const gameCards = useStudioStore((s) => s.gameCards);
  const spec = useStudioStore((s) => s.spec);
  const ws = useStudioStore((s) => s.ws);
  const pausedStepId = useStudioStore((s) => s.pausedStepId);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [gameCards, pausedStepId]);

  // 换成一个新的等待审批的 step（或者审批完清空）时，重置按钮的禁用态。
  useEffect(() => {
    setSubmitting(false);
  }, [pausedStepId]);

  const submitDecision = (decision: string) => {
    if (!ws || !pausedStepId || submitting) return;
    setSubmitting(true);
    ws.send(
      JSON.stringify({ type: "submit_decision", step_id: pausedStepId, decision })
    );
  };

  const routeLabels = pausedStepId ? routeLabelsFor(spec, pausedStepId) : [];

  return (
    <div className="flex flex-col h-full w-full bg-white">
      <div className="px-4 py-3 border-b border-gray-200 font-medium text-gray-700 shrink-0">
        Game View
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-3">
        {gameCards.length === 0 && (
          <div className="text-sm text-gray-400">等待运行开始…</div>
        )}
        {gameCards.map((card, i) => (
          <div
            key={`${card.stepId}-${i}`}
            className={`rounded-lg p-3 text-sm mr-8 ${
              card.status === "error"
                ? "bg-red-50 text-red-800"
                : "bg-gray-50 text-gray-800"
            }`}
          >
            <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
              <span className="font-medium">{card.stepName}</span>
              <span>{STATUS_LABEL[card.status]}</span>
            </div>
            <Markdown text={card.text} />
          </div>
        ))}
        {pausedStepId && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm mr-8">
            <div className="text-amber-800 font-medium mb-2">
              ⏸ 等待人工审批 — {pausedStepId}
            </div>
            <div className="flex gap-2 flex-wrap">
              {routeLabels.length === 0 && (
                <span className="text-xs text-amber-700">
                  这个 checker step 没有配置 next_on_* 路由，无法提交决定
                </span>
              )}
              {routeLabels.map((label) => (
                <button
                  key={label}
                  onClick={() => submitDecision(label)}
                  disabled={submitting}
                  className="rounded-lg bg-amber-500 px-3 py-1 text-sm text-white hover:bg-amber-600 disabled:opacity-50"
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
