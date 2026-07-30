import { useProjectStore } from '../../store/projectStore';
import { ChatView } from './ChatView';
import { ExecutionView } from './ExecutionView';
import { Play, Square } from 'lucide-react';

export function RunTab() {
  const runView = useProjectStore((s) => s.runView);
  const runStatus = useProjectStore((s) => s.runStatus);
  const startRun = useProjectStore((s) => s.startRun);
  const stopRun = useProjectStore((s) => s.stopRun);

  if (runStatus === 'idle') {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <p className="text-muted-foreground mb-4">No active run</p>
          <div className="flex gap-2 justify-center">
            <button
              onClick={() => startRun('studio')}
              className="px-3 py-1 text-sm bg-primary text-primary-foreground rounded flex items-center gap-1"
            >
              <Play size={16} /> Studio Run
            </button>
            <button
              onClick={() => startRun('standalone')}
              className="px-3 py-1 text-sm border rounded"
            >
              Standalone
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex gap-2 p-2 border-b">
        <button
          onClick={() => startRun('studio')}
          disabled={runStatus === 'running'}
          className="px-3 py-1 text-sm bg-primary text-primary-foreground rounded flex items-center gap-1 disabled:opacity-50"
        >
          <Play size={16} /> Studio Run
        </button>
        <button
          onClick={() => startRun('standalone')}
          disabled={runStatus === 'running'}
          className="px-3 py-1 text-sm border rounded disabled:opacity-50"
        >
          Standalone
        </button>
        {runStatus === 'running' && (
          <button
            onClick={stopRun}
            className="px-3 py-1 text-sm bg-destructive text-destructive-foreground rounded flex items-center gap-1"
          >
            <Square size={16} /> Stop
          </button>
        )}
      </div>
      {runView === 'chat' ? <ChatView /> : <ExecutionView />}
    </div>
  );
}
