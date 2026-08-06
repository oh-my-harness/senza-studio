import type { StudioEvent } from '../../types';
import { strField, stepIdField, toolUseIdField, okField, progressField } from '../../types';

export interface ToolCallBlock {
  kind: 'tool_call';
  key: string;
  toolUseId: string;
  name?: string;
  args?: unknown;
  status: 'running' | 'done' | 'error';
  resultText?: string;
  resultDetails?: unknown;
  errorMessage?: string;
  isError: boolean;
  raw: StudioEvent[];
}

export interface MessageBlock {
  kind: 'message';
  key: string;
  text: string;
  thinking?: string;
  isError: false;
  raw: StudioEvent[];
}

export interface MarkerBlock {
  kind: 'marker';
  key: string;
  eventType: string;
  isError: boolean;
  event: StudioEvent;
}

export type LeafBlock = ToolCallBlock | MessageBlock | MarkerBlock;

export interface StepBlock {
  kind: 'step';
  key: string;
  stepId: string;
  stepName?: string;
  status: 'running' | 'done' | 'unknown';
  output?: string;
  structured?: unknown;
  toolCallsCount?: number;
  cost?: unknown;
  isError: boolean;
  children: LeafBlock[];
  startEvent?: StudioEvent;
  finishEvent?: StudioEvent;
}

export type TimelineBlock = StepBlock | LeafBlock;

/**
 * The design doc's failure-highlighting rule (`type: "error"` or
 * `tool_execution_end.result.isError`) describes fields that don't exist on
 * the real Senza SDK wire format (confirmed by reading Senza/src/{event_stream,
 * pyworkflow}.rs) — success/failure is a top-level `ok: boolean` with a plain
 * `error: string` on failure, no nested result object. This is the corrected,
 * functionally-equivalent predicate.
 */
function isErrorEvent(ev: StudioEvent): boolean {
  if (ev.type === 'error' || ev.type === 'failed') return true;
  if (ev.type === 'tool_execution_end' && okField(ev) === false) return true;
  return false;
}

export function buildTimeline(events: StudioEvent[]): TimelineBlock[] {
  const topLevel: TimelineBlock[] = [];
  let container: TimelineBlock[] = topLevel;
  let openStep: StepBlock | null = null;
  const toolCallsByUseId = new Map<string, ToolCallBlock>();

  let seq = 0;
  const nextKey = (prefix: string): string => {
    seq += 1;
    return `${prefix}-${seq}`;
  };

  const pushLeaf = (block: LeafBlock) => container.push(block);
  const lastBlock = (): TimelineBlock | undefined => container[container.length - 1];

  const handleToolEvent = (type: string, ev: StudioEvent, payload: StudioEvent) => {
    const toolUseId = toolUseIdField(payload);
    if (!toolUseId) return;

    if (type === 'tool_call_start') {
      const block: ToolCallBlock = {
        kind: 'tool_call',
        key: nextKey('tool'),
        toolUseId,
        name: strField(payload, 'name') || strField(payload, 'tool_name') || undefined,
        status: 'running',
        isError: false,
        raw: [ev],
      };
      toolCallsByUseId.set(toolUseId, block);
      pushLeaf(block);
      return;
    }

    let block = toolCallsByUseId.get(toolUseId);
    if (!block) {
      // Truncated stream (event for a tool call we never saw start) —
      // synthesize a block at the current position rather than dropping it.
      block = {
        kind: 'tool_call',
        key: nextKey('tool'),
        toolUseId,
        status: 'running',
        isError: false,
        raw: [],
      };
      toolCallsByUseId.set(toolUseId, block);
      pushLeaf(block);
    }
    block.raw.push(ev);

    if (type === 'tool_call_end') {
      block.args = payload.args;
    } else if (type === 'tool_execution_start') {
      block.name = block.name ?? (strField(payload, 'tool_name') || undefined);
      block.args = block.args ?? payload.args;
    } else if (type === 'tool_execution_end') {
      if (okField(payload) === false) {
        block.status = 'error';
        block.isError = true;
        block.errorMessage = strField(payload, 'error') || undefined;
      } else {
        block.status = 'done';
        const result = payload.result;
        if (result && typeof result === 'object' && !Array.isArray(result)) {
          const r = result as Record<string, unknown>;
          block.resultText = typeof r.text === 'string' ? r.text : undefined;
          block.resultDetails = r.details;
        }
      }
    }
  };

  const handleTextEvent = (type: string, ev: StudioEvent) => {
    const last = lastBlock();
    const asMessage = last && last.kind === 'message' ? last : undefined;

    if (type === 'thinking_delta') {
      const thinking = strField(ev, 'thinking');
      if (asMessage) {
        asMessage.thinking = (asMessage.thinking ?? '') + thinking;
        asMessage.raw.push(ev);
      } else {
        pushLeaf({ kind: 'message', key: nextKey('msg'), text: '', thinking, isError: false, raw: [ev] });
      }
    } else if (type === 'text_delta') {
      const text = strField(ev, 'text');
      if (asMessage) {
        asMessage.text += text;
        asMessage.raw.push(ev);
      } else {
        pushLeaf({ kind: 'message', key: nextKey('msg'), text, isError: false, raw: [ev] });
      }
    } else if (type === 'message_update') {
      // Carries accumulated partial text — only replace if longer, matching
      // the same rule already used in projectStore/agentStore's onRunEvent.
      const text = strField(ev, 'text');
      if (asMessage) {
        if (text.length > asMessage.text.length) asMessage.text = text;
        asMessage.raw.push(ev);
      } else if (text) {
        pushLeaf({ kind: 'message', key: nextKey('msg'), text, isError: false, raw: [ev] });
      }
    } else if (type === 'message_end') {
      // Carries the final text — replace.
      const text = strField(ev, 'text');
      if (asMessage) {
        if (text) asMessage.text = text;
        asMessage.raw.push(ev);
      } else if (text) {
        pushLeaf({ kind: 'message', key: nextKey('msg'), text, isError: false, raw: [ev] });
      }
    }
  };

  for (const ev of events) {
    const type = ev.type;

    if (type === 'step_started') {
      const step: StepBlock = {
        kind: 'step',
        key: nextKey('step'),
        stepId: stepIdField(ev) ?? nextKey('step-id'),
        stepName: strField(ev, 'step_name') || undefined,
        status: 'running',
        isError: false,
        children: [],
        startEvent: ev,
      };
      topLevel.push(step);
      openStep = step;
      container = step.children;
      continue;
    }

    if (type === 'step_finished') {
      let step = openStep;
      if (!step) {
        // Unmatched step_finished (e.g. truncated stream) — synthesize a
        // childless step instead of dropping the event.
        step = {
          kind: 'step',
          key: nextKey('step'),
          stepId: stepIdField(ev) ?? nextKey('step-id'),
          status: 'unknown',
          isError: false,
          children: [],
        };
        topLevel.push(step);
      }
      step.status = 'done';
      step.output = strField(ev, 'output') || undefined;
      step.structured = ev.structured;
      step.toolCallsCount = typeof ev.tool_calls_count === 'number' ? ev.tool_calls_count : undefined;
      step.cost = ev.cost;
      step.finishEvent = ev;
      step.isError = step.children.some((c) => c.isError);
      openStep = null;
      container = topLevel;
      continue;
    }

    if (type === 'step_progress') {
      const progress = progressField(ev);
      const progressType = progress && typeof progress.type === 'string' ? progress.type : undefined;
      if (progressType?.startsWith('tool_')) {
        handleToolEvent(progressType, ev, progress!);
      } else if (progressType) {
        pushLeaf({
          kind: 'marker',
          key: nextKey('marker'),
          eventType: progressType,
          isError: isErrorEvent(progress!),
          event: ev,
        });
      }
      continue;
    }

    if (
      type === 'tool_call_start' ||
      type === 'tool_call_end' ||
      type === 'tool_execution_start' ||
      type === 'tool_execution_end'
    ) {
      handleToolEvent(type, ev, ev);
      continue;
    }

    if (
      type === 'text_delta' ||
      type === 'thinking_delta' ||
      type === 'message_update' ||
      type === 'message_end'
    ) {
      handleTextEvent(type, ev);
      continue;
    }

    // Everything else: error, settled, aborted, paused, resumed, cancelled,
    // failed, done, input_request, stdout, stderr, ...
    pushLeaf({
      kind: 'marker',
      key: nextKey('marker'),
      eventType: type,
      isError: isErrorEvent(ev),
      event: ev,
    });
  }

  // Any step still open at the end of the stream (process killed mid-step,
  // or simply the currently-running step of a live view) is left as-is with
  // status 'running' and whatever children arrived so far — this is correct
  // behavior for live viewing, not just an edge case.
  return topLevel;
}

export interface RunSummary {
  eventCount: number;
  stepCount: number;
  doneSteps: number;
  toolCallCount: number;
  errorCount: number;
  mode: 'workflow' | 'single' | 'empty';
}

function countEvents(block: TimelineBlock): number {
  if (block.kind === 'step') {
    const own = (block.startEvent ? 1 : 0) + (block.finishEvent ? 1 : 0);
    return own + block.children.reduce((n, c) => n + countEvents(c), 0);
  }
  if (block.kind === 'tool_call' || block.kind === 'message') {
    return block.raw.length;
  }
  return 1;
}

export function deriveRunSummary(blocks: TimelineBlock[]): RunSummary {
  let stepCount = 0;
  let doneSteps = 0;
  let toolCallCount = 0;
  let errorCount = 0;

  const countLeaf = (leaf: LeafBlock) => {
    if (leaf.kind === 'tool_call') toolCallCount += 1;
    if (leaf.isError) errorCount += 1;
  };

  for (const block of blocks) {
    if (block.kind === 'step') {
      stepCount += 1;
      if (block.status === 'done') doneSteps += 1;
      if (block.isError) errorCount += 1;
      block.children.forEach(countLeaf);
    } else {
      countLeaf(block);
    }
  }

  return {
    eventCount: blocks.reduce((n, b) => n + countEvents(b), 0),
    stepCount,
    doneSteps,
    toolCallCount,
    errorCount,
    mode: blocks.length === 0 ? 'empty' : stepCount > 0 ? 'workflow' : 'single',
  };
}
