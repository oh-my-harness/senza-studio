import { useProjectStore } from '../../store/projectStore';
import { format } from 'timeago.js';

export function TraceTab() {
  const liveEvents = useProjectStore((s) => s.liveEvents);
  const stepStates = useProjectStore((s) => s.stepStates);
  const currentSpec = useProjectStore((s) => s.currentSpec);

  const eventCount = liveEvents.length;
  const stepCount = Object.keys(stepStates).length;
  const doneSteps = Object.values(stepStates).filter((s) => s.status === 'done').length;
  const failedSteps = Object.values(stepStates).filter((s) => s.status === 'failed').length;

  return (
    <div className="flex h-full min-h-0">
      <div className="w-64 border-r overflow-y-auto shrink-0">
        <div className="shrink-0 border-b px-3 py-2.5">
          <div className="flex items-center justify-between gap-2">
            <span className="font-mono text-xs">Run Summary</span>
            <span className="text-muted-foreground text-[0.625rem]">
              {eventCount} events
            </span>
          </div>
          <div className="text-muted-foreground mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.625rem]">
            <span>{stepCount} steps</span>
            <span>{doneSteps} done</span>
            {failedSteps > 0 && <span className="text-destructive">{failedSteps} failed</span>}
          </div>
        </div>

        {currentSpec?.system_prompt && (
          <details className="group shrink-0 border-b px-3 py-2">
            <summary className="text-muted-foreground hover:text-foreground cursor-pointer text-[0.625rem] font-medium">
              System Prompt
            </summary>
            <pre className="mt-2 max-h-36 overflow-auto rounded-md border bg-background/70 px-2 py-2 font-mono text-[0.6875rem] leading-relaxed whitespace-pre-wrap break-words">
              {currentSpec.system_prompt}
            </pre>
          </details>
        )}

        <div className="px-2 py-1 text-xs text-muted-foreground">STEPS</div>
        {Object.entries(stepStates).map(([id, state]) => (
          <div key={id} className="px-3 py-2 border-b text-sm">
            <div className="flex items-center justify-between">
              <span className="font-medium">{id}</span>
              <span
                className={`text-[0.625rem] ${
                  state.status === 'done'
                    ? 'text-green-500'
                    : state.status === 'running'
                    ? 'text-yellow-500'
                    : state.status === 'failed'
                    ? 'text-destructive'
                    : 'text-muted-foreground'
                }`}
              >
                {state.status}
              </span>
            </div>
            {state.output ? (
              <pre className="mt-1 max-h-24 overflow-auto rounded bg-muted p-1 text-xs">
                {typeof state.output === 'string' ? state.output : JSON.stringify(state.output, null, 2)}
              </pre>
            ) : null}
            {state.structured ? (
              <pre className="mt-1 max-h-24 overflow-auto rounded bg-muted p-1 text-xs">
                {JSON.stringify(state.structured, null, 2)}
              </pre>
            ) : null}
          </div>
        ))}
        {stepCount === 0 && (
          <div className="px-3 py-2 text-sm text-muted-foreground">No steps yet</div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-4 min-h-0">
        <div className="text-muted-foreground mb-2 text-xs">
          EVENT TIMELINE ({eventCount})
        </div>
        <div className="space-y-0.5">
          {liveEvents.map((ev, i) => {
            const entries = Object.entries(ev).filter(([k]) => k !== 'type');
            return (
              <div key={i} className="text-xs font-mono flex gap-2 items-start">
                <span className="text-muted-foreground w-8 shrink-0 text-right">{i}</span>
                <span className="font-semibold shrink-0">{ev.type}</span>
                <span className="text-muted-foreground break-all">
                  {entries
                    .map(([k, v]) =>
                      `${k}=${typeof v === 'string' ? v : JSON.stringify(v).slice(0, 80)}`,
                    )
                    .join(' ')}
                </span>
              </div>
            );
          })}
          {eventCount === 0 && (
            <div className="text-muted-foreground text-sm">No events yet. Start a run.</div>
          )}
        </div>
      </div>
    </div>
  );
}
