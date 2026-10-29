import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import AgentRunView from '../AgentRunView';
import type { AgentInfo } from '../types';
beforeEach(() => {
  const data = new Map<string, string>();
  vi.stubGlobal('window', { localStorage: { get length() { return data.size; }, key: (i: number) => [...data.keys()][i], getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => data.set(k, v) } });
});
const info: AgentInfo = {
  title: 'Generic Conversation', description: '', layout: 'conversation', theme: { accent: '#2563eb', mode: 'light', density: 'comfortable', logo: '' }, error: null,
  inputs: ['message', 'course', 'history'].map(name => ({ name, label: name, multiline: true, placeholder: '' })),
  conversation: { message_input: 'message', carry_inputs: ['course'], history_input: 'history', history_max_messages: 20, history_max_chars: 12000 }, steps: {},
};
describe('shared layout dispatch', () => {
  const render = (agent: AgentInfo) => renderToStaticMarkup(<AgentRunView sessionScope="test" info={agent} phase="idle" cards={[]} pendingStep={null} error={null} finishedState={null} connected onStart={vi.fn()} onDecide={vi.fn()} onCancel={vi.fn()} onReset={vi.fn()} />);
  it('dispatches conversation and uses shared input controls while hiding mapped history', () => {
    const html = render(info);
    expect(html).toContain('对话记录');
    expect(html).toContain('input-course');
    expect(html).not.toContain('input-history');
    expect(html).toContain('发送');
  });
  it('does not pretend to remember when history mapping is absent', () => {
    const html = render({ ...info, conversation: { ...info.conversation!, history_input: undefined } });
    expect(html).toContain('未配置历史输入');
  });
  it.each(['form', 'dashboard'])('preserves %s input dispatch', layout => {
    const html = render({ ...info, layout });
    expect(html).toContain('input-message');
    expect(html).not.toContain('对话记录');
  });
});
