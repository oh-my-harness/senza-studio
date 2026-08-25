// studio_frontend/src/components/Inspector.tsx
import { useStudioStore } from "../store";
import { api } from "../api";

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
        {selectedStep.tool && (
          <div>
            <label className="block text-xs text-gray-500 mb-1">tool</label>
            <input
              value={selectedStep.tool}
              readOnly
              className="w-full rounded border border-gray-200 px-2 py-1 text-sm bg-gray-50"
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
        {selectedStep.ui && (
          <div>
            <label className="block text-xs text-gray-500 mb-1">ui.display</label>
            <input
              value={selectedStep.ui.display}
              readOnly
              className="w-full rounded border border-gray-200 px-2 py-1 text-sm bg-gray-50"
            />
          </div>
        )}
      </div>
    </div>
  );
}
