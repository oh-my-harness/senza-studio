import { useState } from 'react';
import { useProjectStore } from '../../store/projectStore';
import { useRunWs } from '../../hooks/useRunWs';
import { Play, Square } from 'lucide-react';

export function ExecutionView() {
  const [taskInput, setTaskInput] = useState('');
  const stepStates = useProjectStore((s) => s.stepStates);
  const activeStepId = useProjectStore((s) => s.activeStepId);
  const runMessages = useProjectStore((s) => s.runMessages);
  const runStatus = useProjectStore((s) => s.runStatus);
  const submitTask = useProjectStore((s) => s.submitTask);
  const stopRun = useProjectStore((s) => s.stopRun);
  const { sendInput } = useRunWs();

  const handleSubmit = () => {
    if (!taskInput.trim()) return;
    submitTask(taskInput);
    sendInput(taskInput);
    setTaskInput('');
  };

  const steps = Object.entries(stepStates);

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      <div className="flex gap-2 p-2 border-b">
        <input
          value={taskInput}
          onChange={(e) => setTaskInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
          placeholder="Submit task..."
          className="flex-1 px-3 py-2 bg-background border rounded"
          disabled={runStatus === 'running'}
        />
        <button onClick={handleSubmit} disabled={runStatus === 'running'} className="px-4 py-2 bg-primary text-primary-foreground rounded flex items-center gap-1 disabled:opacity-50">
          <Play size={16} /> Run
        </button>
        {runStatus === 'running' && (
          <button onClick={stopRun} className="px-3 py-2 bg-destructive text-destructive-foreground rounded flex items-center gap-1">
            <Square size={16} /> Stop
          </button>
        )}
      </div>

      <div className="p-4 border-b">
        <div className="flex items-center gap-2 flex-wrap">
          {steps.map(([stepId, state], i) => (
            <div key={stepId} className="flex items-center gap-2">
              {i > 0 && <span className="text-muted-foreground">→</span>}
              <div className={`px-3 py-1 rounded border ${
                state.status === 'done' ? 'bg-green-100 border-green-500' :
                state.status === 'running' ? 'bg-yellow-100 border-yellow-500 animate-pulse' :
                state.status === 'failed' ? 'bg-red-100 border-red-500' :
                'bg-background'
              }`}>
                <div className="text-sm font-medium">{stepId}</div>
                <div className="text-xs text-muted-foreground">{state.status}</div>
                {state.structured ? (
                  <pre className="text-xs mt-1">{JSON.stringify(state.structured, null, 2).slice(0, 100)}</pre>
                ) : null}
              </div>
            </div>
          ))}
          {steps.length === 0 && <span className="text-sm text-muted-foreground">Submit a task to start</span>}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        <div className="text-xs text-muted-foreground mb-2">
          {activeStepId ? `Step: ${activeStepId}` : 'Output'}
        </div>
        {runMessages
          .filter((m) => m.role === 'assistant')
          .slice(-1)
          .map((msg, i) => (
            <pre key={i} className="text-sm whitespace-pre-wrap">{msg.content}</pre>
          ))}
      </div>
    </div>
  );
}
