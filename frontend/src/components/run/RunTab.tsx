import { useEffect, useState } from 'react';
import { useProjectStore } from '../../store/projectStore';
import { ExternalLink, Radio, Bug, Square } from 'lucide-react';
import type { StudioEvent, RunStatus } from '../../types';

export function RunTab() {
  const project = useProjectStore((s) => s.project);
  const [debugEvents, setDebugEvents] = useState<StudioEvent[]>([]);
  const [agentStatus, setAgentStatus] = useState<RunStatus>('idle');

  // Listen for events from agent window via BroadcastChannel
  useEffect(() => {
    const ch = new BroadcastChannel('senza-studio-run');
    ch.onmessage = (e: MessageEvent<{ runId: string; event: StudioEvent }>) => {
      const ev = e.data.event;
      setDebugEvents((prev) => [...prev, ev]);
      // Derive status from event type
      if (ev.type === 'input_request' || ev.type === 'paused') {
        setAgentStatus('waiting_input');
      } else if (ev.type === 'failed' || ev.type === 'cancelled' || ev.type === 'error') {
        setAgentStatus('failed');
      } else if (ev.type === 'done') {
        setAgentStatus('completed');
      } else if (ev.type === 'settled') {
        setAgentStatus('running');
      }
    };
    return () => ch.close();
  }, []);

  const openAgentWindow = () => {
    if (!project) return;
    window.open(
      `/agent-window/${encodeURIComponent(project.id)}`,
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
          className="px-3 py-1 text-sm bg-primary text-primary-foreground rounded flex items-center gap-1"
        >
          <ExternalLink size={16} /> Open Agent Window
        </button>
        {(agentStatus === 'running' || agentStatus === 'waiting_input') && (
          <button
            onClick={() => {
              const ch = new BroadcastChannel('senza-studio-run');
              ch.postMessage({ command: 'stop' });
              ch.close();
              setAgentStatus('idle');
            }}
            className="px-3 py-1 text-sm bg-destructive text-destructive-foreground rounded flex items-center gap-1"
          >
            <Square size={16} /> Stop
          </button>
        )}
        <div className="flex-1" />
        <span className={`text-xs px-2 py-1 rounded flex items-center gap-1 ${
          agentStatus === 'running' ? 'bg-blue-100 text-blue-700' :
          agentStatus === 'waiting_input' ? 'bg-yellow-100 text-yellow-700' :
          agentStatus === 'completed' ? 'bg-green-100 text-green-700' :
          agentStatus === 'failed' ? 'bg-red-100 text-red-700' :
          'bg-muted text-muted-foreground'
        }`}>
          <Radio size={12} />
          {agentStatus}
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
                  ev.type === 'text_delta' || ev.type === 'message_update' || ev.type === 'message_end' ? 'bg-blue-400' :
                  ev.type === 'thinking_delta' ? 'bg-purple-400' :
                  ev.type === 'stdout' ? 'bg-cyan-400' :
                  'bg-gray-400'
                }`} />
                <span className="text-muted-foreground">{ev.type}</span>
                {ev.type === 'text_delta' || ev.type === 'stderr' || ev.type === 'stdout' || ev.type === 'message_update' || ev.type === 'message_end' ? (
                  <span className="ml-2 text-foreground truncate">
                    {String(ev.text ?? '').slice(0, 120)}
                  </span>
                ) : ev.type === 'thinking_delta' ? (
                  <span className="ml-2 text-purple-500 truncate">
                    {String(ev.thinking ?? '').slice(0, 120)}
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
