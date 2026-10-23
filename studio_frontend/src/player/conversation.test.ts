import { describe, expect, it, vi } from 'vitest';
import { ConversationController, conversationInputs, newSession } from './conversation';
import type { AgentInfo } from './types';
export const info: AgentInfo = {
  title: 'Tutor', description: '', layout: 'conversation', theme: { accent: '#2563eb', mode: 'light', density: 'comfortable', logo: '' }, error: null,
  inputs: ['message', 'course', 'history'].map(name => ({ name, label: name, multiline: true, placeholder: '' })),
  conversation: { message_input: 'message', carry_inputs: ['course'], history_input: 'history', history_max_messages: 4, history_max_chars: 1000 },
  steps: { reply: { title: 'Reply', display: 'chat', fields: [], choices: [], terminal: false } },
};
const cards = [{ stepId: 'reply', stepName: 'reply', text: 'answer one', status: 'done' as const }];
describe('Conversation invocation boundary', () => {
  it('two sequential Play invocations carry current values and map bounded string history', () => {
    const invoke = vi.fn();
    const c = new ConversationController(info, newSession('project-a'), vi.fn());
    c.start({ message: 'first', course: 'math' }, invoke);
    expect(c.busy).toBe(true);
    expect(c.start({ message: 'duplicate', course: 'math' }, invoke)).toBe(false);
    c.observe('done', cards, null, 'succeeded', true);
    c.start({ message: 'second', course: 'physics' }, invoke);
    expect(invoke).toHaveBeenCalledTimes(2);
    expect(invoke.mock.calls[1][0]).toEqual({ message: 'second', course: 'physics', history: JSON.stringify([{ role: 'user', content: 'first' }, { role: 'assistant', content: 'answer one' }]) });
    c.observe('done', cards, null, 'succeeded', true);
    expect(c.session.messages.map(m => m.role)).toEqual(['user', 'agent', 'user', 'agent']);
    expect(c.session.carry).toEqual({ course: 'physics' });
  });
  it('rejects missing required fields before invoking; does not invent inputs', () => {
    expect(() => conversationInputs(info, { message: 'hello' }, newSession('a'))).toThrow('必填');
    const result = conversationInputs(info, { message: 'hello', course: 'math', secret: 'no' }, newSession('a'));
    expect(result).not.toHaveProperty('secret');
    expect(typeof result.history).toBe('string');
  });
  it('keeps old messages on errors; retries reuse the failed message instead of duplicating it', () => {
    const c = new ConversationController(info, newSession('a'), vi.fn());
    const invoke = vi.fn();
    c.start({ message: 'first', course: 'math' }, invoke);
    c.observe('done', cards, null, 'succeeded', true);
    c.start({ message: 'second', course: 'math' }, invoke);
    c.observe('done', cards, 'network error', 'failed', true);
    expect(c.session.messages.at(-1)?.status).toBe('failed');
    c.start({ course: 'math' }, invoke, true);
    expect(c.session.messages).toHaveLength(4);
    expect(invoke.mock.calls.at(-1)![0].message).toBe('second');
    c.observe('done', cards, null, 'failed', true);
    expect(c.session.messages.at(-1)?.status).toBe('failed');
  });
  it('treats request throws and disconnects as failures/unknown, never a successful answer', () => {
    const c = new ConversationController(info, newSession('a'), vi.fn());
    c.start({ message: 'first', course: 'math' }, () => { throw Error('request failed'); });
    expect(c.session.messages.at(-1)?.status).toBe('failed');
    c.start({ course: 'math' }, vi.fn(), true);
    c.observe('running', cards, null, null, false);
    expect(c.session.messages.at(-1)?.status).toBe('interrupted');
    c.observe('done', cards, null, 'succeeded', true);
    expect(c.session.messages.at(-1)?.status).toBe('interrupted');
  });
  it('bounds context without truncating stored UI history or including failures', () => {
    const limited = { ...info, conversation: { ...info.conversation!, history_max_messages: 2 } };
    const c = new ConversationController(limited, newSession('a'), vi.fn());
    for (let i = 0; i < 3; i++) { c.start({ message: String(i), course: 'math' }, vi.fn()); c.observe('done', cards, null, 'succeeded', true); }
    expect(JSON.parse(conversationInputs(limited, { message: 'next', course: 'math' }, c.session).history)).toHaveLength(2);
    expect(c.session.messages).toHaveLength(6);
    limited.conversation.history_max_chars = 2;
    expect(conversationInputs(limited, { message: 'next', course: 'math' }, c.session).history).toBe('[]');
  });
});

it('keeps retry locked after a stream error until the workflow terminal acknowledgement', () => {
  const invoke = vi.fn();
  const c = new ConversationController(info, newSession('a'), vi.fn());
  c.start({ message: 'first', course: 'math' }, invoke);
  c.observe('running', [], 'stream error', null, true);
  expect(c.busy).toBe(true);
  expect(c.start({ message: 'retry', course: 'math' }, invoke, true)).toBe(false);
  c.observe('done', [], 'stream error', 'failed', true);
  expect(c.busy).toBe(false);
  expect(c.session.messages.at(-1)?.status).toBe('failed');
});
