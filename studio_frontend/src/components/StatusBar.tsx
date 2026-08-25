// studio_frontend/src/components/StatusBar.tsx
import { useStudioStore } from "../store";

export default function StatusBar() {
  const project = useStudioStore((s) => s.project);
  const status = useStudioStore((s) => s.status);
  const spec = useStudioStore((s) => s.spec);

  const stepCount = spec.stages.length;

  return (
    <div className="flex items-center justify-between px-4 py-2 border-t border-gray-200 bg-gray-50 text-xs text-gray-600">
      <div className="flex items-center gap-4">
        {project && <span>{project.name}</span>}
        <span>状态: {status}</span>
        <span>{stepCount} 步骤</span>
      </div>
      <div>{project?.model || ""}</div>
    </div>
  );
}
