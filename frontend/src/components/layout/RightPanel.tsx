import { useProjectStore } from '../../store/projectStore';

export function RightPanel() {
  const conversationStatus = useProjectStore((s) => s.conversationStatus);
  const currentSpec = useProjectStore((s) => s.currentSpec);
  const liveEvents = useProjectStore((s) => s.liveEvents);
  const activeTab = useProjectStore((s) => s.activeTab);

  return (
    <div className="w-72 h-full border-l overflow-y-auto">
      {activeTab === 'converse' && (
        <div className="p-2">
          <div className="text-xs text-muted-foreground mb-2">SPEC PREVIEW</div>
          {currentSpec ? (
            <pre className="text-xs bg-muted p-2 rounded whitespace-pre-wrap break-words">
              {JSON.stringify(currentSpec, null, 2)}
            </pre>
          ) : (
            <p className="text-sm text-muted-foreground">No spec yet. Status: {conversationStatus}</p>
          )}
        </div>
      )}
      {activeTab === 'run' && (
        <div className="p-2">
          <div className="text-xs text-muted-foreground mb-2">EVENTS ({liveEvents.length})</div>
          <div className="space-y-1">
            {liveEvents.slice(-20).map((ev, i) => (
              <div key={i} className="text-xs font-mono">
                {ev.type}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
