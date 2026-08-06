import { describe, expect, it } from 'vitest';
import { buildTimeline, deriveRunSummary } from './timeline';
import type { StudioEvent } from '../../types';

describe('buildTimeline — single-agent stream', () => {
  it('accumulates text/thinking deltas into one message block and correlates a successful tool call', () => {
    const events: StudioEvent[] = [
      { type: 'thinking_delta', message_id: 'm1', thinking: 'Let me ' },
      { type: 'thinking_delta', message_id: 'm1', thinking: 'check.' },
      { type: 'tool_call_start', message_id: 'm1', tool_use_id: 't1', tool_name: 'lookup_order' },
      { type: 'tool_call_end', tool_use_id: 't1', args: { order_id: 'A123' } },
      { type: 'tool_execution_start', tool_use_id: 't1', tool_name: 'lookup_order', args: { order_id: 'A123' } },
      {
        type: 'tool_execution_end',
        tool_use_id: 't1',
        ok: true,
        result: { terminate: false, text: 'found it', details: { status: 'shipped' } },
      },
      { type: 'text_delta', message_id: 'm2', text: 'Your order ' },
      { type: 'text_delta', message_id: 'm2', text: 'has shipped.' },
      { type: 'message_end', message_id: 'm2', text: 'Your order has shipped.' },
      { type: 'settled' },
    ];

    const blocks = buildTimeline(events);

    // thinking message, tool call, text message, settled marker
    expect(blocks.map((b) => b.kind)).toEqual(['message', 'tool_call', 'message', 'marker']);

    const thinkingBlock = blocks[0];
    if (thinkingBlock.kind !== 'message') throw new Error('expected message');
    expect(thinkingBlock.thinking).toBe('Let me check.');

    const toolBlock = blocks[1];
    if (toolBlock.kind !== 'tool_call') throw new Error('expected tool_call');
    expect(toolBlock.toolUseId).toBe('t1');
    expect(toolBlock.name).toBe('lookup_order');
    expect(toolBlock.status).toBe('done');
    expect(toolBlock.isError).toBe(false);
    expect(toolBlock.resultText).toBe('found it');
    expect(toolBlock.resultDetails).toEqual({ status: 'shipped' });

    const textBlock = blocks[2];
    if (textBlock.kind !== 'message') throw new Error('expected message');
    // message_end replaces with the final text
    expect(textBlock.text).toBe('Your order has shipped.');

    const settledMarker = blocks[3];
    if (settledMarker.kind !== 'marker') throw new Error('expected marker');
    expect(settledMarker.isError).toBe(false);

    const summary = deriveRunSummary(blocks);
    expect(summary.mode).toBe('single');
    expect(summary.stepCount).toBe(0);
    expect(summary.toolCallCount).toBe(1);
    expect(summary.errorCount).toBe(0);
  });

  it('flags a failing tool call as an error via the corrected ok:false predicate', () => {
    const events: StudioEvent[] = [
      { type: 'tool_call_start', tool_use_id: 't1', tool_name: 'flaky_tool' },
      { type: 'tool_execution_start', tool_use_id: 't1', tool_name: 'flaky_tool' },
      { type: 'tool_execution_end', tool_use_id: 't1', ok: false, error: 'boom' },
      { type: 'error', message: 'agent gave up' },
    ];

    const blocks = buildTimeline(events);
    const toolBlock = blocks[0];
    if (toolBlock.kind !== 'tool_call') throw new Error('expected tool_call');
    expect(toolBlock.status).toBe('error');
    expect(toolBlock.isError).toBe(true);
    expect(toolBlock.errorMessage).toBe('boom');

    const errorMarker = blocks[1];
    if (errorMarker.kind !== 'marker') throw new Error('expected marker');
    expect(errorMarker.isError).toBe(true);

    const summary = deriveRunSummary(blocks);
    // one error from the tool call, one from the top-level error marker
    expect(summary.errorCount).toBe(2);
  });

  it('synthesizes a block for a tool_execution_end with no preceding tool_call_start', () => {
    const events: StudioEvent[] = [
      { type: 'tool_execution_end', tool_use_id: 'orphan', ok: true, result: { text: 'ok' } },
    ];

    const blocks = buildTimeline(events);
    expect(blocks).toHaveLength(1);
    const toolBlock = blocks[0];
    if (toolBlock.kind !== 'tool_call') throw new Error('expected tool_call');
    expect(toolBlock.toolUseId).toBe('orphan');
    expect(toolBlock.status).toBe('done');
    expect(toolBlock.name).toBeUndefined();
  });
});

describe('buildTimeline — workflow stream', () => {
  it('groups step_progress tool calls under their step and derives step-level error from children', () => {
    const events: StudioEvent[] = [
      { type: 'step_started', step_id: 's1', step_name: 'classify' },
      {
        type: 'step_progress',
        step_id: 's1',
        progress: { type: 'tool_call_start', tool_use_id: 't1', name: 'classify_tool' },
      },
      {
        type: 'step_progress',
        step_id: 's1',
        progress: { type: 'tool_execution_end', tool_use_id: 't1', ok: false, error: 'timeout' },
      },
      { type: 'step_finished', step_id: 's1', output: 'failed', structured: { status: 'fail' }, tool_calls_count: 1 },
      { type: 'step_started', step_id: 's2', step_name: 'report' },
      { type: 'step_finished', step_id: 's2', output: 'done', structured: null, tool_calls_count: 0 },
    ];

    const blocks = buildTimeline(events);
    expect(blocks).toHaveLength(2);

    const step1 = blocks[0];
    if (step1.kind !== 'step') throw new Error('expected step');
    expect(step1.stepId).toBe('s1');
    expect(step1.status).toBe('done');
    expect(step1.output).toBe('failed');
    expect(step1.structured).toEqual({ status: 'fail' });
    expect(step1.children).toHaveLength(1);
    expect(step1.isError).toBe(true);

    const step2 = blocks[1];
    if (step2.kind !== 'step') throw new Error('expected step');
    expect(step2.isError).toBe(false);
    expect(step2.children).toHaveLength(0);

    const summary = deriveRunSummary(blocks);
    expect(summary.mode).toBe('workflow');
    expect(summary.stepCount).toBe(2);
    expect(summary.doneSteps).toBe(2);
    expect(summary.errorCount).toBe(2); // one from the failing tool call, one from the step it belongs to
  });

  it('synthesizes an unknown-status step for an unmatched step_finished', () => {
    const events: StudioEvent[] = [
      { type: 'step_finished', step_id: 'orphan', output: 'x', structured: null },
    ];

    const blocks = buildTimeline(events);
    expect(blocks).toHaveLength(1);
    const step = blocks[0];
    if (step.kind !== 'step') throw new Error('expected step');
    expect(step.stepId).toBe('orphan');
    expect(step.status).toBe('done');
    expect(step.children).toHaveLength(0);
  });

  it('leaves an unmatched step_started open with status running (e.g. process killed mid-step, or a live in-progress step)', () => {
    const events: StudioEvent[] = [
      { type: 'step_started', step_id: 's1', step_name: 'classify' },
      { type: 'text_delta', text: 'still working...' },
    ];

    const blocks = buildTimeline(events);
    expect(blocks).toHaveLength(1);
    const step = blocks[0];
    if (step.kind !== 'step') throw new Error('expected step');
    expect(step.status).toBe('running');
    expect(step.children).toHaveLength(1);
  });
});

describe('deriveRunSummary', () => {
  it('reports mode "empty" for an empty event stream', () => {
    expect(deriveRunSummary(buildTimeline([]))).toMatchObject({
      mode: 'empty',
      eventCount: 0,
      stepCount: 0,
    });
  });
});
