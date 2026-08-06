import { ChevronDown } from 'lucide-react';
import type { LeafBlock, MarkerBlock, MessageBlock, StepBlock, ToolCallBlock, TimelineBlock } from './timeline';

function dotColor(eventType: string, isError: boolean): string {
  if (isError || eventType === 'error' || eventType === 'failed') return 'bg-red-500';
  if (eventType === 'settled' || eventType === 'done') return 'bg-green-500';
  if (eventType === 'input_request' || eventType === 'paused') return 'bg-yellow-500';
  if (eventType === 'stdout' || eventType === 'stderr') return 'bg-cyan-400';
  return 'bg-gray-400';
}

function statusPill(status: 'running' | 'done' | 'error' | 'unknown', isError: boolean) {
  const effective = isError ? 'error' : status;
  const cls =
    effective === 'done'
      ? 'text-green-500'
      : effective === 'running'
      ? 'text-yellow-500'
      : effective === 'error'
      ? 'text-destructive'
      : 'text-muted-foreground';
  return <span className={`text-[0.625rem] ${cls}`}>{effective}</span>;
}

function MarkerBlockView({ block }: { block: MarkerBlock }) {
  const text =
    typeof block.event.text === 'string'
      ? block.event.text
      : typeof block.event.thinking === 'string'
      ? block.event.thinking
      : typeof block.event.message === 'string'
      ? block.event.message
      : undefined;

  return (
    <div className={`flex items-start gap-2 text-xs font-mono py-0.5 ${block.isError ? 'text-destructive' : ''}`}>
      <span className={`mt-1 inline-block size-2 shrink-0 rounded-full ${dotColor(block.eventType, block.isError)}`} />
      <span className="shrink-0 text-muted-foreground">{block.eventType}</span>
      {text && <span className="truncate">{text}</span>}
    </div>
  );
}

function MessageBlockView({ block }: { block: MessageBlock }) {
  return (
    <div className="py-1">
      {block.thinking && block.thinking.trim() && (
        <details className="group mb-1 text-muted-foreground">
          <summary className="flex cursor-pointer items-center gap-1 text-xs font-medium">
            <ChevronDown className="size-3 shrink-0 -rotate-90 transition-transform duration-200 group-open:rotate-0" />
            Thinking
          </summary>
          <div className="mt-1 border-l-2 border-border pl-3 text-xs whitespace-pre-wrap">
            {block.thinking}
          </div>
        </details>
      )}
      {block.text && <p className="text-sm whitespace-pre-wrap">{block.text}</p>}
    </div>
  );
}

function ToolCallBlockView({ block }: { block: ToolCallBlock }) {
  return (
    <details className={`group my-1 rounded border px-2 py-1 ${block.isError ? 'border-destructive/50' : 'border-border'}`}>
      <summary className="flex cursor-pointer items-center gap-2 text-xs font-mono">
        <ChevronDown className="size-3 shrink-0 -rotate-90 transition-transform duration-200 group-open:rotate-0" />
        <span className="font-semibold">🔧 {block.name ?? block.toolUseId}</span>
        {statusPill(block.status, block.isError)}
      </summary>
      <div className="mt-2 space-y-1.5 pl-5 text-xs">
        {block.args !== undefined && (
          <div>
            <div className="text-muted-foreground">args</div>
            <pre className="mt-0.5 overflow-auto rounded bg-muted p-1.5 font-mono">
              {JSON.stringify(block.args, null, 2)}
            </pre>
          </div>
        )}
        {block.resultText && (
          <div>
            <div className="text-muted-foreground">result</div>
            <pre className="mt-0.5 overflow-auto rounded bg-muted p-1.5 font-mono whitespace-pre-wrap">
              {block.resultText}
            </pre>
          </div>
        )}
        {block.resultDetails !== undefined && (
          <div>
            <div className="text-muted-foreground">details</div>
            <pre className="mt-0.5 overflow-auto rounded bg-muted p-1.5 font-mono">
              {JSON.stringify(block.resultDetails, null, 2)}
            </pre>
          </div>
        )}
        {block.errorMessage && (
          <div className="text-destructive">{block.errorMessage}</div>
        )}
      </div>
    </details>
  );
}

function LeafBlockView({ block }: { block: LeafBlock }) {
  if (block.kind === 'message') return <MessageBlockView block={block} />;
  if (block.kind === 'tool_call') return <ToolCallBlockView block={block} />;
  return <MarkerBlockView block={block} />;
}

function StepBlockView({ block }: { block: StepBlock }) {
  return (
    <details
      open
      className={`my-2 rounded border px-3 py-2 ${block.isError ? 'border-destructive/50' : 'border-border'}`}
    >
      <summary className="flex cursor-pointer items-center gap-2">
        <span className="font-mono text-xs font-semibold">{block.stepName ?? block.stepId}</span>
        {statusPill(block.status, block.isError)}
        {block.toolCallsCount != null && (
          <span className="text-[0.625rem] text-muted-foreground">{block.toolCallsCount} tool calls</span>
        )}
      </summary>
      <div className="mt-2 space-y-0.5">
        {block.children.map((child) => (
          <LeafBlockView key={child.key} block={child} />
        ))}
        {block.children.length === 0 && (
          <div className="text-xs text-muted-foreground">No events in this step yet.</div>
        )}
      </div>
      {block.output && (
        <div className="mt-2 text-xs">
          <div className="text-muted-foreground">output</div>
          <pre className="mt-0.5 max-h-32 overflow-auto rounded bg-muted p-1.5 font-mono whitespace-pre-wrap">
            {block.output}
          </pre>
        </div>
      )}
      {block.structured != null && (
        <div className="mt-2 text-xs">
          <div className="text-muted-foreground">structured</div>
          <pre className="mt-0.5 max-h-32 overflow-auto rounded bg-muted p-1.5 font-mono">
            {JSON.stringify(block.structured, null, 2)}
          </pre>
        </div>
      )}
    </details>
  );
}

export function EventTimeline({
  blocks,
  loading,
  error,
}: {
  blocks: TimelineBlock[];
  loading?: boolean;
  error?: string | null;
}) {
  if (error) {
    return <div className="text-destructive text-sm">{error}</div>;
  }
  if (loading) {
    return <div className="text-muted-foreground text-sm">Loading…</div>;
  }
  if (blocks.length === 0) {
    return <div className="text-muted-foreground text-sm">No events yet. Start a run.</div>;
  }
  return (
    <div className="space-y-0.5">
      {blocks.map((block) =>
        block.kind === 'step' ? (
          <StepBlockView key={block.key} block={block} />
        ) : (
          <LeafBlockView key={block.key} block={block} />
        ),
      )}
    </div>
  );
}
