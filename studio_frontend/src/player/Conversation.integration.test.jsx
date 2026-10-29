import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { create, act } from 'react-test-renderer';
import AgentRunView from './AgentRunView';
import StartForm from './StartForm';
import AgentApp from '../../agent/AgentApp';
import GameView from '../components/GameView';
import { useProjectSocket } from '../hooks/useProjectSocket';
import { useStudioStore } from '../store';
import { api } from '../api';

const info = {
  title: 'Tutor', description: '', layout: 'conversation', error: null, theme: {},
  inputs: [
    { name: 'message', label: 'Message', multiline: true, placeholder: '' },
    { name: 'course', label: 'Course', multiline: false, placeholder: '', default: 'math' },
    { name: 'history', label: 'History', multiline: true, placeholder: '' },
  ],
  conversation: { message_input: 'message', carry_inputs: ['course'], history_input: 'history', history_max_messages: 20, history_max_chars: 12000 },
  steps: { reply: { title: 'Reply', display: 'chat', terminal: false, fields: [], choices: [] } },
};
let sockets, data, tree;
class Socket {
  static OPEN = 1;
  readyState = 1;
  sent = [];
  constructor() { sockets.push(this); }
  send(raw) { this.sent.push(JSON.parse(raw)); }
  close() { this.readyState = 3; }
  event(event) { this.onmessage({ data: JSON.stringify(event) }); }
}
function text() { return JSON.stringify(tree.toJSON()); }
function fill(message, course = 'math') {
  act(() => tree.root.findByType(StartForm).props.onValuesChange({ message, course }));
}
function submitTwice() {
  act(() => {
    const form = tree.root.findByType('form');
    form.props.onSubmit({ preventDefault() {} });
    form.props.onSubmit({ preventDefault() {} });
  });
}
function complete(socket, answer) {
  act(() => {
    socket.event({ type: 'step_started', step_id: 'reply', step_name: 'reply' });
    socket.event({ type: 'text_delta', step_id: 'reply', text: answer });
    socket.event({ type: 'step_finished', step_id: 'reply', output: '' });
    socket.event({ type: 'workflow_done', state: 'succeeded' });
  });
}
beforeEach(() => {
  data = new Map(); sockets = [];
  vi.stubGlobal('window', { localStorage: {
    get length() { return data.size; }, key: n => [...data.keys()][n] ?? null,
    getItem: k => data.get(k) ?? null, setItem: (k, v) => data.set(k, v),
  } });
  vi.stubGlobal('document', { title: '' });
  vi.stubGlobal('location', { protocol: 'http:', host: 'example.test' });
  vi.stubGlobal('WebSocket', Socket);
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, headers: { get: () => 'export:agent-a' }, json: async () => info })));
  useStudioStore.getState().resetPlay();
});
afterEach(() => { if (tree) act(() => tree.unmount()); tree = null; vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('real React lifecycle and host wiring (controlled transport, no model)', () => {
  it('export: two sends, duplicate gate, reload four messages, resume with context, switch independent sessions', async () => {
    await act(async () => { tree = create(<AgentApp />); });
    act(() => sockets[0].onopen());
    fill('first'); submitTwice();
    expect(sockets[0].sent).toHaveLength(1);
    expect(text()).toContain('正在执行');
    complete(sockets[0], 'answer one');
    expect(text()).toContain('answer one');
    fill('second', 'physics'); submitTwice();
    expect(sockets[0].sent).toHaveLength(2);
    expect(sockets[0].sent[1].inputs.course).toBe('physics');
    complete(sockets[0], 'answer two');
    const a = tree.root.findByProps({ 'aria-label': '选择会话' }).props.value;
    act(() => tree.unmount());
    await act(async () => { tree = create(<AgentApp />); });
    act(() => sockets[1].onopen());
    expect(text()).toContain('answer one'); expect(text()).toContain('answer two');
    expect(tree.root.findByType(StartForm).props.values.course).toBe('physics');
    fill('third', 'physics'); submitTwice();
    expect(JSON.parse(sockets[1].sent[0].inputs.history)).toEqual([
      { role: 'user', content: 'first' }, { role: 'assistant', content: 'answer one' },
      { role: 'user', content: 'second' }, { role: 'assistant', content: 'answer two' },
    ]);
    complete(sockets[1], 'answer three');
    act(() => tree.root.findAllByType('button').find(b => b.children.includes('新建会话')).props.onClick());
    expect(text()).not.toContain('answer one');
    act(() => tree.root.findByProps({ 'aria-label': '选择会话' }).props.onChange({ target: { value: a } }));
    expect(text()).toContain('answer three');
    expect(JSON.parse([...data.values()].find(raw => JSON.parse(raw).id === a)).messages).toHaveLength(6);
  });
  it('export: request error can retry without duplicating messages; in-flight reload is unknown', async () => {
    await act(async () => { tree = create(<AgentApp />); }); act(() => sockets[0].onopen());
    fill('first'); submitTwice();
    act(() => sockets[0].event({ type: 'error', terminal: true, message: 'cannot start' }));
    expect(text()).toContain('执行失败');
    act(() => tree.root.findAllByType('button').find(b => b.children.includes('重试上一条消息')).props.onClick());
    expect(sockets[0].sent).toHaveLength(2);
    expect(JSON.parse([...data.values()][0]).messages).toHaveLength(2);
    act(() => tree.unmount());
    await act(async () => { tree = create(<AgentApp />); }); act(() => sockets[1].onopen());
    expect(text()).toContain('结果未知'); expect(sockets[1].sent).toHaveLength(0);
  });
  it('Studio: actual socket hook forwards two plays and startup errors stay actionable', async () => {
    vi.spyOn(api, 'getAgent').mockResolvedValue(info);
    function Studio() { useProjectSocket('project-a'); return <GameView projectId="project-a" />; }
    await act(async () => { tree = create(<Studio />); });
    fill('first'); submitTwice();
    expect(sockets[0].sent[0]).toMatchObject({ type: 'play', inputs: { message: 'first', course: 'math', history: '[]' } });
    complete(sockets[0], 'answer one');
    fill('second'); submitTwice();
    expect(sockets[0].sent.filter(e => e.type === 'play')).toHaveLength(2);
    act(() => sockets[0].event({ type: 'error', source: 'play', terminal: true, message: 'cannot build' }));
    expect(text()).toContain('cannot build'); expect(text()).toContain('重试上一条消息');
    expect(text()).toContain('answer one');
  });
  it('shared layout: unavailable storage blocks calls and tells the user', () => {
    vi.stubGlobal('window', { get localStorage() { throw Error('storage disabled'); } });
    const start = vi.fn();
    act(() => { tree = create(<AgentRunView sessionScope="studio:a" info={info} cards={[]} phase="idle" pendingStep={null} error={null} finishedState={null} connected onStart={start} onReset={vi.fn()} onDecide={vi.fn()} onCancel={vi.fn()} />); });
    expect(text()).toContain('会话存储不可用');
    expect(tree.root.findByType(StartForm).props.disabled).toBe(true);
    expect(start).not.toHaveBeenCalled();
  });
});
