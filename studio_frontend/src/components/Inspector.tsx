// studio_frontend/src/components/Inspector.tsx
import { useStudioStore } from "../store";
import { api } from "../api";

const UI_DISPLAY_OPTIONS = [
  "none",
  "chat",
  "status",
  "table",
  "chart",
  "approval_form",
];

export default function Inspector({ projectId }: { projectId: string }) {
  const selectedStep = useStudioStore((s) => s.selectedStep);
  const spec = useStudioStore((s) => s.spec);
  const setSpec = useStudioStore((s) => s.setSpec);

  if (!selectedStep) {
    return (
      <div className="w-80 border-l border-gray-200 bg-white p-4 text-sm text-gray-400">
        选择一个节点查看属性
      </div>
    );
  }

  const updateField = (key: string, value: unknown) => {
    const newStages = spec.stages.map((s) =>
      s.name === selectedStep.name ? { ...s, [key]: value } : s
    );
    const newSpec = { ...spec, stages: newStages };
    setSpec(newSpec);
    api.updateSpec(projectId, newSpec).catch(console.error);
  };

  const updateUi = (key: "display" | "fields", value: unknown) => {
    const ui = { ...(selectedStep.ui || { display: "none" }), [key]: value };
    updateField("ui", ui);
  };

  const edges = Object.entries(selectedStep)
    .filter(([k, v]) => k.startsWith("next_on_") && typeof v === "string")
    .map(([k, v]) => ({ condition: k.replace("next_on_", ""), to: v as string }));

  return (
    <div className="w-80 border-l border-gray-200 bg-white p-4 overflow-y-auto">
      <h3 className="font-medium text-gray-700 mb-3">属性</h3>
      <div className="space-y-3">
        <div>
          <label className="block text-xs text-gray-500 mb-1">name</label>
          <input
            value={selectedStep.name}
            readOnly
            className="w-full rounded border border-gray-200 px-2 py-1 text-sm bg-gray-50"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">type</label>
          <input
            value={selectedStep.type}
            readOnly
            className="w-full rounded border border-gray-200 px-2 py-1 text-sm bg-gray-50"
          />
        </div>
        {selectedStep.prompt_template !== undefined && (
          <div>
            <label className="block text-xs text-gray-500 mb-1">prompt_template</label>
            <textarea
              value={selectedStep.prompt_template || ""}
              onChange={(e) => updateField("prompt_template", e.target.value)}
              rows={5}
              className="w-full rounded border border-gray-200 px-2 py-1 text-sm font-mono"
            />
          </div>
        )}
        {selectedStep.type === "tool" && (
          <div>
            <label className="block text-xs text-gray-500 mb-1">tool</label>
            <input
              value={(selectedStep.tool as string) || ""}
              onChange={(e) => updateField("tool", e.target.value)}
              placeholder="工具名称"
              className="w-full rounded border border-gray-200 px-2 py-1 text-sm"
            />
          </div>
        )}
        {selectedStep.message !== undefined && (
          <div>
            <label className="block text-xs text-gray-500 mb-1">message</label>
            <input
              value={selectedStep.message || ""}
              onChange={(e) => updateField("message", e.target.value)}
              className="w-full rounded border border-gray-200 px-2 py-1 text-sm"
            />
          </div>
        )}
        {selectedStep.type !== "terminal" && (
          <div>
            <label className="block text-xs text-gray-500 mb-1">output_key</label>
            <input
              value={(selectedStep.output_key as string) || ""}
              onChange={(e) => updateField("output_key", e.target.value)}
              placeholder="结果存入的 context 变量名"
              className="w-full rounded border border-gray-200 px-2 py-1 text-sm"
            />
          </div>
        )}
        <div className="pt-2 border-t border-gray-100">
          <label className="block text-xs text-gray-500 mb-1">ui.display</label>
          <select
            value={selectedStep.ui?.display || "none"}
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
            value={(selectedStep.ui?.fields || []).join(", ")}
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
  );
}
