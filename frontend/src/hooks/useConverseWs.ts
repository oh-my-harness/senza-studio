import { useEffect, useRef } from 'react';
import { useProjectStore } from '@/store/projectStore';
import { WsClient } from '@/lib/ws';

export function useConverseWs() {
  const project = useProjectStore((s) => s.project);
  const onConverseEvent = useProjectStore((s) => s.onConverseEvent);
  const wsRef = useRef<WsClient | null>(null);

  useEffect(() => {
    if (!project) return;
    const ws = new WsClient(
      `ws://${location.host}/ws/converse/${encodeURIComponent(project.id)}`,
      onConverseEvent,
    );
    wsRef.current = ws;
    return () => ws.close();
  }, [project, onConverseEvent]);

  return {
    send: (text: string) => wsRef.current?.send(text),
  };
}
