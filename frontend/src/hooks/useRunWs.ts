import { useEffect, useRef } from 'react';
import { useProjectStore } from '@/store/projectStore';
import { WsClient } from '@/lib/ws';

export function useRunWs() {
  const project = useProjectStore((s) => s.project);
  const activeRunId = useProjectStore((s) => s.activeRunId);
  const onRunEvent = useProjectStore((s) => s.onRunEvent);
  const wsRef = useRef<WsClient | null>(null);

  useEffect(() => {
    if (!project || !activeRunId) return;

    const ws = new WsClient(
      `ws://${location.host}/ws/run/${project.id}`,
      onRunEvent,
    );
    wsRef.current = ws;

    // Send run_id as first message so the server knows which run to subscribe to.
    // Wait for the socket to be open.
    const sendRunId = () => {
      if (ws.isOpen()) {
        ws.sendJson({ run_id: activeRunId });
      } else {
        setTimeout(sendRunId, 50);
      }
    };
    setTimeout(sendRunId, 50);

    return () => ws.close();
  }, [project, activeRunId, onRunEvent]);

  return {
    sendInput: (text: string) => {
      if (activeRunId) {
        wsRef.current?.sendJson({ run_id: activeRunId, input: text });
      }
    },
  };
}
