import { useMemo } from 'react';
import { format } from 'timeago.js';
import { useProjectStore } from '../../store/projectStore';
import { buildTimeline, deriveRunSummary } from './timeline';
import { EventTimeline } from './EventTimeline';
import { useRunPicker, uuidv7ToDate } from '../../hooks/useRunPicker';

function runLabel(runId: string, isActive: boolean): string {
  const date = uuidv7ToDate(runId);
  const when = date ? format(date) : runId.slice(0, 8);
  return isActive ? `${when} (live)` : when;
}

export function TraceTab() {
  const project = useProjectStore((s) => s.project);
  const activeRunId = useProjectStore((s) => s.activeRunId);
  const currentSpec = useProjectStore((s) => s.currentSpec);
  const { runIds, selectedRunId, selectRun, events, loadingEvents, fetchError } = useRunPicker(project?.id);

  const blocks = useMemo(() => buildTimeline(events), [events]);
  const summary = useMemo(() => deriveRunSummary(blocks), [blocks]);
  const steps = useMemo(() => blocks.filter((b) => b.kind === 'step'), [blocks]);

  return (
    <div className="flex h-full min-h-0">
      <div className="w-64 border-r overflow-y-auto shrink-0">
        <div className="shrink-0 border-b px-3 py-2.5">
          <select
            className="w-full rounded border bg-background px-2 py-1 text-xs font-mono"
            value={selectedRunId ?? 'live'}
            onChange={(e) => selectRun(e.target.value === 'live' ? null : e.target.value)}
          >
            <option value="live">Live{activeRunId ? '' : ' (no active run)'}</option>
            {runIds
              .filter((id) => id !== activeRunId)
              .map((id) => (
                <option key={id} value={id}>
                  {runLabel(id, false)}
                </option>
              ))}
          </select>
          <div className="mt-2 flex items-center justify-between gap-2">
            <span className="font-mono text-xs">Run Summary</span>
            <span className="text-muted-foreground text-[0.625rem]">
              {summary.eventCount} events
            </span>
          </div>
          <div className="text-muted-foreground mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.625rem]">
            {summary.mode === 'workflow' && (
              <>
                <span>{summary.stepCount} steps</span>
                <span>{summary.doneSteps} done</span>
              </>
            )}
            {summary.toolCallCount > 0 && <span>{summary.toolCallCount} tool calls</span>}
            {summary.errorCount > 0 && (
              <span className="text-destructive">{summary.errorCount} errors</span>
            )}
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

        {summary.mode === 'workflow' && (
          <>
            <div className="px-2 py-1 text-xs text-muted-foreground">STEPS</div>
            {steps.map((step) =>
              step.kind === 'step' ? (
                <div key={step.key} className="px-3 py-2 border-b text-sm">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{step.stepName ?? step.stepId}</span>
                    <span
                      className={`text-[0.625rem] ${
                        step.isError
                          ? 'text-destructive'
                          : step.status === 'done'
                          ? 'text-green-500'
                          : step.status === 'running'
                          ? 'text-yellow-500'
                          : 'text-muted-foreground'
                      }`}
                    >
                      {step.isError ? 'failed' : step.status}
                    </span>
                  </div>
                </div>
              ) : null,
            )}
          </>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-4 min-h-0">
        <div className="text-muted-foreground mb-2 text-xs">
          EVENT TIMELINE ({summary.eventCount})
        </div>
        <EventTimeline blocks={blocks} loading={loadingEvents} error={fetchError} />
      </div>
    </div>
  );
}
