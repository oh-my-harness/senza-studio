import { useEffect, useRef } from 'react';
import { useAgentStore } from '@/store/agentStore';
import { WsClient } from '@/lib/ws';
import type { StudioEvent } from '@/types';

export function useAgentRunWs() {
  const projectId = useAgentStore((s) => s.projectId);
  const activeRunId = useAgentStore((s) => s.activeRunId);
  const onRunEvent = useAgentStore((s) => s.onRunEvent);
  const stopRun = useAgentStore((s) => s.stopRun);
  const wsRef = useRef<WsClient | null>(null);

  // Listen for stop commands from Studio window
  useEffect(() => {
    const ch = new BroadcastChannel('senza-studio-run');
    ch.onmessage = (e: MessageEvent<{ command?: string }>) => {
      if (e.data?.command === 'stop') {
        stopRun();
      }
    };
    return () => ch.close();
  }, [stopRun]);

  useEffect(() => {
    if (!projectId || !activeRunId) return;

    const handler = (event: StudioEvent) => {
      onRunEvent(event);
      // Forward to Studio window via BroadcastChannel for debug panel
      try {
        const ch = new BroadcastChannel('senza-studio-run');
        ch.postMessage({ runId: activeRunId, event });
        ch.close();
      } catch {
        // BroadcastChannel not available — ignore
      }
    };

    const ws = new WsClient(
      `ws://${location.host}/ws/run/${projectId}`,
      handler,
    );
    wsRef.current = ws;

    const sendRunId = () => {
      if (ws.isOpen()) {
        ws.sendJson({ run_id: activeRunId });
      } else {
        setTimeout(sendRunId, 50);
      }
    };
    setTimeout(sendRunId, 50);

    return () => ws.close();
  }, [projectId, activeRunId, onRunEvent]);

  return {
    sendInput: (text: string) => {
      if (activeRunId) {
        wsRef.current?.sendJson({ run_id: activeRunId, input: text });
      }
    },
  };
}
