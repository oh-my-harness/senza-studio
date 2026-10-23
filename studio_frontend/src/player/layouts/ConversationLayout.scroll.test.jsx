// ConversationLayout 的布局/滚动回归测试：不需要 jsdom。
// 用 createNodeMock 提供一个可写的滚动盒，验证"只有贴着底部才自动滚"。
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { act, create } from 'react-test-renderer';
import AgentRunView from '../AgentRunView';
import StartForm from '../StartForm';

const scope = 'scroll-test';
const info = {
  title: 'Scrollable Conversation', description: '', layout: 'conversation', theme: {}, error: null,
  inputs: [
    { name: 'message', label: 'Message', multiline: true, placeholder: '' },
    { name: 'course', label: 'Course', multiline: false, placeholder: '', default: 'math' },
    { name: 'history', label: 'History', multiline: true, placeholder: '' },
  ],
  conversation: { message_input: 'message', carry_inputs: ['course'], history_input: 'history', history_max_messages: 20, history_max_chars: 12000 },
  steps: { reply: { title: 'Reply', display: 'chat', terminal: false, fields: [], choices: [] } },
};
let data;
function seed(count) {
  const messages = Array.from({ length: count }, (_, i) => ({
    id: `m${i}`, role: i % 2 === 0 ? 'user' : 'agent', status: 'done',
    text: `message ${i}`, timestamp: new Date(2026, 0, 1, 0, 0, i).toISOString(),
  }));
  const session = {
    id: 's1', scope, title: 'Seeded', createdAt: '2026-01-01T00:00:00.000Z',
    updatedAt: '2026-01-01T00:00:01.000Z', carry: {}, messages,
  };
  data.set(`senza:conversation:v1:${encodeURIComponent(scope)}:s1`, JSON.stringify({ version: 1, ...session }));
}
function element(extra = {}) {
  return (
    <AgentRunView
      sessionScope={scope} info={info} cards={[]} phase="idle" pendingStep={null}
      error={null} finishedState={null} connected onStart={vi.fn()} onReset={vi.fn()}
      onDecide={vi.fn()} onCancel={vi.fn()} {...extra}
    />
  );
}
function submit(tree, message) {
  act(() => tree.root.findByType(StartForm).props.onValuesChange({ message, course: 'math' }));
  act(() => tree.root.findByType('form').props.onSubmit({ preventDefault() {} }));
}
let tree;
beforeEach(() => {
  data = new Map();
  vi.stubGlobal('window', { localStorage: {
    get length() { return data.size; }, key: i => [...data.keys()][i] ?? null,
    getItem: k => data.get(k) ?? null, setItem: (k, v) => data.set(k, v),
  } });
});
afterEach(() => { if (tree) act(() => tree.unmount()); tree = null; vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('conversation viewport layout', () => {
  it('pins the composer outside the only scroll container, even with 100 messages', () => {
    seed(100);
    act(() => {
      tree = create(element(), { createNodeMock: () => ({}) });
    });
    const shell = tree.toJSON();
    expect(shell.props.className).toContain('flex');
    expect(shell.props.className).toContain('min-h-0');
    expect(shell.props.className).toContain('overflow-hidden');

    const scroller = tree.root.findByProps({ 'data-testid': 'conversation-scroll' });
    expect(scroller.props.className).toContain('min-h-0');
    expect(scroller.props.className).toContain('flex-1');
    expect(scroller.props.className).toContain('overflow-y-auto');
    expect(scroller.findAllByType(StartForm)).toHaveLength(0);
    expect(tree.root.findAllByType(StartForm)).toHaveLength(1);
    expect(JSON.stringify(tree.toJSON())).toContain('message 99');
  });

  it('auto-scrolls on send/update only while the user is at the bottom', () => {
    seed(2);
    const box = { scrollHeight: 1000, clientHeight: 400, scrollTop: 0 };
    act(() => {
      tree = create(element(), {
        createNodeMock: node => (node.props['data-testid'] === 'conversation-scroll' ? box : {}),
      });
    });
    const scroller = tree.root.findByProps({ 'data-testid': 'conversation-scroll' });
    expect(box.scrollTop).toBe(1000);

    submit(tree, 'first');
    expect(box.scrollTop).toBe(1000);
    expect(JSON.stringify(tree.toJSON())).toContain('正在执行');

    // 用户上翻：之后的完成事件不得把界面拽回底部。
    box.scrollTop = 100;
    act(() => scroller.props.onScroll({ currentTarget: box }));
    act(() => {
      tree.update(element({
        phase: 'done', finishedState: 'succeeded',
        cards: [{ stepId: 'reply', stepName: 'reply', text: 'answer one', status: 'done' }],
      }));
    });
    expect(JSON.stringify(tree.toJSON())).toContain('answer one');
    expect(box.scrollTop).toBe(100);
  });

  it('scrolls back down when the user sends from an older position', () => {
    seed(2);
    const box = { scrollHeight: 1000, clientHeight: 400, scrollTop: 0 };
    act(() => {
      tree = create(element(), {
        createNodeMock: node => (node.props['data-testid'] === 'conversation-scroll' ? box : {}),
      });
    });
    const scroller = tree.root.findByProps({ 'data-testid': 'conversation-scroll' });
    box.scrollTop = 0;
    act(() => scroller.props.onScroll({ currentTarget: box }));
    submit(tree, 'from history');
    expect(box.scrollTop).toBe(1000);
  });
});
