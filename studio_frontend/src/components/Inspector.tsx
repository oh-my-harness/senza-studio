// studio_frontend/src/components/Inspector.tsx
import { useEffect, useState } from "react";
import { useStudioStore } from "../store";
import { api } from "../api";
import type { Step } from "../types";

const UI_DISPLAY_OPTIONS = [
  "none",
  "chat",
  "status",
  "table",
  "chart",
  "approval_form",
];

export default function Inspector({ projectId }: { projectId: string }) {
  const selectedStepName = useStudioStore((s) => s.selectedStepName);
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

  if (!selectedStep || !draft) {
    return (
      <div className="w-80 border-l border-gray-200 bg-white p-4 text-sm text-gray-400">
        选择一个节点查看属性
      </div>
    );
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
    <div className="w-80 border-l border-gray-200 bg-white p-4 overflow-y-auto flex flex-col">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-medium text-gray-700">属性</h3>
        {isDirty && <span className="text-xs text-amber-600">有未保存的修改</span>}
      </div>
      <div className="space-y-3 flex-1">
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
      <div className="flex gap-2 pt-3 mt-3 border-t border-gray-200">
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
