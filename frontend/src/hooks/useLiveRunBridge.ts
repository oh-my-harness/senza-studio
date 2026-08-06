import { useEffect } from 'react';
import { useProjectStore } from '../store/projectStore';
import type { StudioEvent } from '../types';

/**
 * Bridges run events forwarded from the pop-out AgentWindow (via
 * BroadcastChannel) into the main window's projectStore, so tabs that read
 * live run state (Trace, DAG, StatusBar) stay populated during a run.
 * Mounted once, unconditionally, in App.tsx — not inside RunTab, since
 * only one tab is mounted at a time and Trace needs live data while
 * RunTab is unmounted.
 */
export function useLiveRunBridge() {
  const onRunEvent = useProjectStore((s) => s.onRunEvent);

  useEffect(() => {
    const ch = new BroadcastChannel('senza-studio-run');
    ch.onmessage = (e: MessageEvent<{ runId?: string; event?: StudioEvent; command?: string }>) => {
      const { runId, event } = e.data;
      if (!runId || !event) return;

      const current = useProjectStore.getState().activeRunId;
      if (runId !== current) {
        useProjectStore.setState({
          activeRunId: runId,
          runStatus: 'running',
          liveEvents: [],
          stepStates: {},
          activeStepId: null,
        });
      }
      onRunEvent(event);
    };
    return () => ch.close();
  }, [onRunEvent]);
}
