// studio_frontend/src/components/Inspector.tsx
import { useEffect, useState } from "react";
import { useStudioStore } from "../store";
import { api } from "../api";
import Markdown from "./Markdown";
import type { GameCard, Step } from "../types";

const UI_DISPLAY_OPTIONS = [
  "none",
  "chat",
  "status",
  "table",
  "chart",
  "approval_form",
];

const RUNTIME_STATUS_LABEL: Record<string, string> = {
  running: "运行中…",
  done: "完成",
  error: "出错",
};

// Play 运行态下 Inspector 的展示——input/output/route/工具调用/指标，全部
// 来自 play.py 塞进 structured._debug 的数据（GameView 已经在用同一个
// gameCards 数组，这里只是换一种更详细的方式展示同一份数据，不是另一条
// 数据通路）。跟编辑态的属性表单是完全不同的渲染分支，不共享 draft 状态。
function RuntimeInspector({ card, stepType }: { card: GameCard | undefined; stepType: string }) {
  if (!card) {
    return <div className="p-4 text-sm text-gray-400">该 step 本次运行还未执行</div>;
  }

  const debug = card.debug ?? null;
  const usage = (debug?.usage as Record<string, unknown> | null | undefined) ?? null;
  const toolCallsCount = debug?.tool_calls_count as number | undefined;

  return (
    <div className="p-4 space-y-3 text-sm">
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-500">状态</span>
        <span className="text-xs font-medium">{RUNTIME_STATUS_LABEL[card.status] ?? card.status}</span>
      </div>

      <div>
        <label className="block text-xs text-gray-500 mb-1">输入</label>
        {stepType === "agent" && typeof debug?.prompt === "string" ? (
          <pre className="w-full rounded border border-gray-200 bg-gray-50 px-2 py-1 text-xs whitespace-pre-wrap break-words">
            {debug.prompt}
          </pre>
        ) : stepType === "tool" && debug?.tool ? (
          <div className="rounded border border-gray-200 bg-gray-50 px-2 py-1 text-xs space-y-1">
            <div>
              工具: <span className="font-mono">{String(debug.tool)}</span>
            </div>
            <pre className="whitespace-pre-wrap break-words">
              {JSON.stringify(debug.args ?? {}, null, 2)}
            </pre>
          </div>
        ) : (
          <div className="text-xs text-gray-400">（无输入信息）</div>
        )}
      </div>

      <div>
        <label className="block text-xs text-gray-500 mb-1">输出</label>
        <div className="rounded border border-gray-200 bg-gray-50 px-2 py-1">
          <Markdown text={card.text} />
        </div>
      </div>

      {card.route && (
        <div>
          <label className="block text-xs text-gray-500 mb-1">路由</label>
          <div className="text-xs font-mono">{card.route}</div>
        </div>
      )}

      {(toolCallsCount !== undefined || usage) && (
        <div className="pt-2 border-t border-gray-100">
          <label className="block text-xs text-gray-500 mb-1">指标</label>
          {toolCallsCount !== undefined && (
            <div className="text-xs text-gray-600">工具调用次数: {toolCallsCount}</div>
          )}
          {usage && (
            <div className="text-xs text-gray-600 space-y-0.5 mt-1">
              {Object.entries(usage).map(([k, v]) => (
                <div key={k}>
                  {k}: {typeof v === "object" && v !== null ? JSON.stringify(v) : String(v)}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function Inspector({ projectId }: { projectId: string }) {
  const selectedStepName = useStudioStore((s) => s.selectedStepName);
  const status = useStudioStore((s) => s.status);
  const gameCards = useStudioStore((s) => s.gameCards);
  const spec = useStudioStore((s) => s.spec);
  const setSpec = useStudioStore((s) => s.setSpec);
  // 每次都从当前 spec 里现查，跟 spec 保持同步——不缓存快照
  const selectedStep = spec.stages.find((s) => s.name === selectedStepName) ?? null;

  // 编辑先落在本地草稿里，不直接改 spec——只有点了 Save 才提交。切换选中
  // 节点时用该节点当前已保存的值重置草稿（未保存的编辑不跨节点带过去）。
  const [draft, setDraft] = useState<Step | null>(selectedStep);
  useEffect(() => {
    setDraft(selectedStep);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedStepName]);

  if (!selectedStep) {
    return (
      <div className="h-full w-full border-l border-gray-200 bg-white flex flex-col">
        <div className="px-4 py-3 border-b border-gray-200 font-medium text-gray-700 shrink-0">
          Inspector
        </div>
        <div className="p-4 text-sm text-gray-400">选择一个节点查看属性</div>
      </div>
    );
  }

  if (status === "playing") {
    // 同一个 step 在一次 Play 里可能跑多次（checker 暂停/resume 会重新
    // 执行）——取最后一张卡片，跟 GameView 展示的是同一份最新状态。
    const cards = gameCards.filter((c) => c.stepId === selectedStepName);
    const latestCard = cards[cards.length - 1];
    return (
      <div className="h-full w-full border-l border-gray-200 bg-white flex flex-col">
        <div className="px-4 py-3 border-b border-gray-200 font-medium text-gray-700 shrink-0">
          Inspector — {selectedStep.name}
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto">
          <RuntimeInspector card={latestCard} stepType={selectedStep.type} />
        </div>
      </div>
    );
  }

  if (!draft) {
    return null;
  }

  const isDirty = JSON.stringify(draft) !== JSON.stringify(selectedStep);

  const updateField = (key: string, value: unknown) => {
    setDraft((d) => (d ? { ...d, [key]: value } : d));
  };

  const updateUi = (key: "display" | "fields", value: unknown) => {
    setDraft((d) =>
      d ? { ...d, ui: { ...(d.ui || { display: "none" }), [key]: value } } : d
    );
  };

  const save = () => {
    const newStages = spec.stages.map((s) => (s.name === draft.name ? draft : s));
    const newSpec = { ...spec, stages: newStages };
    setSpec(newSpec);
    api.updateSpec(projectId, newSpec).catch(console.error);
  };

  const reset = () => setDraft(selectedStep);

  const edges = Object.entries(draft)
    .filter(([k, v]) => k.startsWith("next_on_") && typeof v === "string")
    .map(([k, v]) => ({ condition: k.replace("next_on_", ""), to: v as string }));

  return (
    <div className="h-full w-full border-l border-gray-200 bg-white flex flex-col">
      <div className="px-4 py-3 border-b border-gray-200 font-medium text-gray-700 flex items-center justify-between gap-2 shrink-0">
        <span>Inspector</span>
        {isDirty && <span className="text-xs text-amber-600 font-normal">有未保存的修改</span>}
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto p-4">
        <div className="space-y-3">
        <div>
          <label className="block text-xs text-gray-500 mb-1">name</label>
          <input
            value={draft.name}
            readOnly
            className="w-full rounded border border-gray-200 px-2 py-1 text-sm bg-gray-50"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">type</label>
          <input
            value={draft.type}
            readOnly
            className="w-full rounded border border-gray-200 px-2 py-1 text-sm bg-gray-50"
          />
        </div>
        {draft.prompt_template !== undefined && (
          <div>
            <label className="block text-xs text-gray-500 mb-1">prompt_template</label>
            <textarea
              value={draft.prompt_template || ""}
              onChange={(e) => updateField("prompt_template", e.target.value)}
              rows={5}
              className="w-full rounded border border-gray-200 px-2 py-1 text-sm font-mono"
            />
          </div>
        )}
        {draft.type === "tool" && (
          <div>
            <label className="block text-xs text-gray-500 mb-1">tool</label>
            <input
              value={(draft.tool as string) || ""}
              onChange={(e) => updateField("tool", e.target.value)}
              placeholder="工具名称"
              className="w-full rounded border border-gray-200 px-2 py-1 text-sm"
            />
          </div>
        )}
        {draft.message !== undefined && (
          <div>
            <label className="block text-xs text-gray-500 mb-1">message</label>
            <input
              value={draft.message || ""}
              onChange={(e) => updateField("message", e.target.value)}
              className="w-full rounded border border-gray-200 px-2 py-1 text-sm"
            />
          </div>
        )}
        {draft.type !== "terminal" && (
          <div>
            <label className="block text-xs text-gray-500 mb-1">output_key</label>
            <input
              value={(draft.output_key as string) || ""}
              onChange={(e) => updateField("output_key", e.target.value)}
              placeholder="结果存入的 context 变量名"
              className="w-full rounded border border-gray-200 px-2 py-1 text-sm"
            />
          </div>
        )}
        <div className="pt-2 border-t border-gray-100">
          <label className="block text-xs text-gray-500 mb-1">ui.display</label>
          <select
            value={draft.ui?.display || "none"}
            onChange={(e) => updateUi("display", e.target.value)}
            className="w-full rounded border border-gray-200 px-2 py-1 text-sm bg-white"
          >
            {UI_DISPLAY_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">ui.fields</label>
          <input
            value={(draft.ui?.fields || []).join(", ")}
            onChange={(e) =>
              updateUi(
                "fields",
                e.target.value
                  .split(",")
                  .map((f) => f.trim())
                  .filter(Boolean)
              )
            }
            placeholder="逗号分隔的字段名"
            className="w-full rounded border border-gray-200 px-2 py-1 text-sm"
          />
        </div>
        {edges.length > 0 && (
          <div className="pt-2 border-t border-gray-100">
            <label className="block text-xs text-gray-500 mb-1">edges</label>
            <div className="space-y-1">
              {edges.map(({ condition, to }) => (
                <div
                  key={condition}
                  className="text-xs text-gray-600 bg-gray-50 rounded px-2 py-1"
                >
                  {condition} → {to}
                </div>
              ))}
            </div>
          </div>
        )}
        </div>
      </div>
      <div className="flex gap-2 p-4 border-t border-gray-200 shrink-0">
        <button
          onClick={save}
          disabled={!isDirty}
          className="flex-1 rounded-lg bg-blue-500 px-3 py-1.5 text-sm text-white hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          保存
        </button>
        <button
          onClick={reset}
          disabled={!isDirty}
          className="flex-1 rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          重置
        </button>
      </div>
    </div>
  );
}
