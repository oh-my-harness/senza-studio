import { useProjectStore } from '../../store/projectStore';

export function StatusBar() {
  const runStatus = useProjectStore((s) => s.runStatus);
  const activeRunId = useProjectStore((s) => s.activeRunId);
  return (
    <div className="border-t px-4 py-1 text-xs flex gap-4">
      <span>Status: {runStatus}</span>
      {activeRunId && <span>Run: {activeRunId.slice(0, 8)}</span>}
    </div>
  );
}
