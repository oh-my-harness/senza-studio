import { useEffect, useState } from 'react';
import { useProjectStore } from '../../store/projectStore';
import { ExternalLink, Radio, Bug, Square } from 'lucide-react';
import type { StudioEvent } from '../../types';

export function RunTab() {
  const project = useProjectStore((s) => s.project);
  const runStatus = useProjectStore((s) => s.runStatus);
  const stopRun = useProjectStore((s) => s.stopRun);
  const [debugEvents, setDebugEvents] = useState<StudioEvent[]>([]);

  // Listen for events from agent window via BroadcastChannel
  useEffect(() => {
    const ch = new BroadcastChannel('senza-studio-run');
    ch.onmessage = (e: MessageEvent<{ runId: string; event: StudioEvent }>) => {
      setDebugEvents((prev) => [...prev, e.data.event]);
    };
    return () => ch.close();
  }, []);

  const openAgentWindow = () => {
    if (!project) return;
    window.open(
      `/agent-window/${project.id}`,
      'agent-window',
      'width=600,height=800,scrollbars=yes',
    );
  };

  const openStandaloneWindow = () => {
    if (!project) return;
    window.open(
      `/agent-window/${project.id}`,
      'agent-window',
      'width=600,height=800,scrollbars=yes',
    );
  };

  const recentEvents = debugEvents.slice(-50);

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex gap-2 p-2 border-b shrink-0">
        <button
          onClick={openAgentWindow}
          disabled={runStatus === 'running'}
          className="px-3 py-1 text-sm bg-primary text-primary-foreground rounded flex items-center gap-1 disabled:opacity-50"
        >
          <Play size={16} /> Start & Open
        </button>
        <button
          onClick={openStandaloneWindow}
          className="px-3 py-1 text-sm border rounded flex items-center gap-1"
        >
          <ExternalLink size={16} /> Open Window
        </button>
        {(runStatus === 'running' || runStatus === 'waiting_input') && (
          <button
            onClick={() => stopRun()}
            className="px-3 py-1 text-sm bg-destructive text-destructive-foreground rounded flex items-center gap-1"
          >
            <Square size={16} /> Stop
          </button>
        )}
        <div className="flex-1" />
        <span className={`text-xs px-2 py-1 rounded flex items-center gap-1 ${
          runStatus === 'running' ? 'bg-blue-100 text-blue-700' :
          runStatus === 'waiting_input' ? 'bg-yellow-100 text-yellow-700' :
          runStatus === 'completed' ? 'bg-green-100 text-green-700' :
          runStatus === 'failed' ? 'bg-red-100 text-red-700' :
          'bg-muted text-muted-foreground'
        }`}>
          <Radio size={12} />
          {runStatus}
        </span>
      </div>

      {/* Debug panel */}
      <div className="flex-1 overflow-y-auto p-3 min-h-0">
        <div className="flex items-center gap-2 mb-2 text-xs text-muted-foreground">
          <Bug size={14} />
          Debug Event Stream
          {recentEvents.length > 0 && (
            <button
              onClick={() => setDebugEvents([])}
              className="ml-auto hover:text-foreground"
            >
              Clear
            </button>
          )}
        </div>

        {recentEvents.length === 0 ? (
          <div className="text-sm text-muted-foreground py-8 text-center">
            No events yet. Start an agent to see debug output.
          </div>
        ) : (
          <div className="space-y-1">
            {recentEvents.map((ev, i) => (
              <div
                key={i}
                className="text-xs font-mono p-1.5 rounded bg-muted/50 border border-border/50"
              >
                <span className={`inline-block w-2 h-2 rounded-full mr-2 ${
                  ev.type === 'error' || ev.type === 'failed' ? 'bg-red-500' :
                  ev.type === 'settled' || ev.type === 'done' ? 'bg-green-500' :
                  ev.type === 'input_request' || ev.type === 'paused' ? 'bg-yellow-500' :
                  ev.type === 'text_delta' ? 'bg-blue-400' :
                  ev.type === 'thinking_delta' ? 'bg-purple-400' :
                  'bg-gray-400'
                }`} />
                <span className="text-muted-foreground">{ev.type}</span>
                {ev.type === 'text_delta' || ev.type === 'stderr' ? (
                  <span className="ml-2 text-foreground truncate">
                    {String(ev.text ?? '').slice(0, 120)}
                  </span>
                ) : ev.type === 'thinking_delta' ? (
                  <span className="ml-2 text-purple-500 truncate">
                    {String(ev.text ?? '').slice(0, 120)}
                  </span>
                ) : (
                  <span className="ml-2 text-muted-foreground truncate">
                    {JSON.stringify(
                      Object.fromEntries(
                        Object.entries(ev).filter(([k]) => k !== 'type')
                      )
                    ).slice(0, 120)}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
