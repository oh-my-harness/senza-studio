import { useEffect, useMemo, useRef, useState, type UIEvent } from 'react';
import { ConversationController, inputDefaults, newSession } from '../conversation';
import { LocalConversationStorage } from '../conversationStorage';
import DecisionPanel from '../DecisionPanel';
import PlayerShell from '../PlayerShell';
import StartForm from '../StartForm';
import type { LayoutProps } from './types';

/** 距底部多少像素以内算"用户还在看最新消息"。留一点余量，避免滚动惯性和
 *  子像素误差把自动滚动误判成"用户主动上翻"。 */
const STICK_THRESHOLD = 32;

export default function ConversationLayout(props: LayoutProps) {
  const { info, phase, cards, error, finishedState, connected, pendingStep, onReset, onStart, onDecide, compact = false } = props;
  const [version, refresh] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const scope = props.sessionScope;
  const boot = useMemo(() => {
    try {
      if (!scope) throw new Error('缺少 Agent/Project 会话标识');
      const store = new LocalConversationStorage(window.localStorage, scope, info.conversation?.carry_inputs ?? []);
      const sessions = store.list();
      const session = sessions.length ? store.load(sessions[0].id) : newSession(scope);
      return { store, session, error: null };
    } catch (e) { return { store: null, session: newSession(scope ?? 'unavailable'), error: String(e) }; }
  }, [scope, info]);
  const [selected, setSelected] = useState(boot.session);
  const [values, setValues] = useState(() => ({ ...inputDefaults(info), ...boot.session.carry }));
  const controller = useMemo(() => new ConversationController(info, selected, () => refresh(n => n + 1), session => {
    if (!boot.store) throw new Error(boot.error ?? '会话存储不可用');
    boot.store.save(session);
  }), [info, selected, boot]);
  useEffect(() => {
    try { boot.store?.save(controller.session); }
    catch (e) { setProblem(`会话保存失败：${String(e)}`); }
  }, [boot, controller]);
  useEffect(() => {
    try { controller.observe(phase, cards, error, finishedState, connected); }
    catch (e) { setProblem(`会话保存失败：${String(e)}。当前回答仍在页面中，请勿刷新。`); }
  }, [controller, phase, cards, error, finishedState, connected]);
  const sessions = useMemo(() => {
    try { return boot.store?.list() ?? []; } catch { return []; }
  }, [boot, version]);
  const config = info.conversation;
  const session = controller.session;

  // 消息区是这里**唯一**的滚动容器：页头、会话控件、输入区都由 flex 固定，
  // 长历史只在这个 min-h-0 + overflow-y-auto 的盒子里滚。
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // 用户主动上翻后不要再把界面拽回底部；只有本来就在底部（或主动发送）才跟。
  const pinnedToBottom = useRef(true);
  useEffect(() => {
    if (!pinnedToBottom.current) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [session.id, session.messages, controller.busy, pendingStep, problem, error, finishedState]);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    // 全屏/返回编辑器、窗口缩放都会改变可视高度；贴着底部时保持贴底。
    const observer = new ResizeObserver(() => {
      if (pinnedToBottom.current) el.scrollTop = el.scrollHeight;
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [controller]);
  const onScroll = (event: UIEvent<HTMLDivElement>) => {
    const el = event.currentTarget;
    pinnedToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight <= STICK_THRESHOLD;
  };

  if (!config || info.error) return <PlayerShell info={info} connected={connected} compact={compact}><p>请先配置合法的对话输入映射。</p></PlayerShell>;
  const send = (retry = false) => {
    setProblem(null);
    // 发送是用户明确的"我要看最新"动作——即使之前在上翻，也回到底部。
    pinnedToBottom.current = true;
    try {
      if (controller.start(values, inputs => { onReset(); onStart(inputs); }, retry)) {
        setValues(v => ({ ...v, [config.message_input]: '' }));
      }
    } catch (e) { setProblem(String(e)); }
  };
  const inputInfo = { ...info, inputs: info.inputs.filter(f => f.name !== config.history_input) };
  return <PlayerShell info={info} connected={connected} compact={compact} fill>
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <select aria-label="选择会话" className="min-w-0 max-w-full" value={session.id} disabled={controller.busy} onChange={e => {
          try {
            const next = boot.store!.load(e.target.value);
            pinnedToBottom.current = true;
            setSelected(next); setValues({ ...inputDefaults(info), ...next.carry }); setProblem(null); onReset();
          } catch (e) { setProblem(String(e)); }
        }}>
          {!sessions.some(s => s.id === session.id) && <option value={session.id}>{session.title}</option>}
          {sessions.map(s => <option key={s.id} value={s.id}>{s.title} · {s.updatedAt}</option>)}
        </select>
        <button type="button" disabled={controller.busy || !!boot.error} onClick={() => {
          try {
            const next = newSession(scope!); boot.store!.save(next);
            pinnedToBottom.current = true;
            setSelected(next); setValues(inputDefaults(info)); setProblem(null); onReset();
          } catch (e) { setProblem(String(e)); }
        }}>新建会话</button>
        <label className="flex min-w-0 items-center gap-1">会话名称 <input aria-label="会话名称" className="max-w-full" value={session.title} disabled={controller.busy || !!boot.error} onChange={e => {
          try { controller.rename(e.target.value); } catch (e) { setProblem(String(e)); }
        }} /></label>
      </div>
      <div
        ref={scrollRef}
        data-testid="conversation-scroll"
        onScroll={onScroll}
        className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain"
      >
        <div className="space-y-2 pb-1">
          <p className="text-xs text-[var(--text-muted)]">自动保存在当前浏览器和站点。不会跨设备同步，也不会在 Studio 与导出部署间自动共享。</p>
          {config.history_input && <p role="note" className="text-xs text-[var(--text-muted)]">上下文仅传最近 {config.history_max_messages} 条成功消息，最多 {config.history_max_chars} 字符；更早内容可能不传入。Player 不自动恢复 Agent 业务状态。</p>}
          {!config.history_input && <p role="note" className="text-sm text-[var(--warn-text)]">此 Agent 未配置历史输入。界面对话记录不代表 Agent 具有跨轮记忆；Player 不会自动恢复业务状态。</p>}
          <ol aria-label="对话记录" className="space-y-3">
            {session.messages.map(message => <li key={message.id} className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
              <div className="text-xs text-[var(--text-muted)]">{message.role === 'user' ? '你' : 'Agent'} · {new Date(message.timestamp).toLocaleString()}</div>
              <p className="whitespace-pre-wrap break-words">{message.status === 'pending' ? '正在执行…' : message.text}</p>
              {['failed', 'interrupted'].includes(message.status) && <span role="alert" className="text-sm text-[var(--danger-text)]">{message.status === 'interrupted' ? '结果未知' : '执行失败'}</span>}
            </li>)}
          </ol>
        </div>
      </div>
      <div className="shrink-0 space-y-3 border-t border-[var(--border)] pt-3">
        {boot.error && <p role="alert" className="break-words">会话存储不可用：{boot.error}</p>}
        {controller.busy && error && <p role="alert" className="break-words">{error}（等待执行结束）</p>}
        {controller.busy && <p role="status">正在执行，请稍候…</p>}
        {controller.busy && pendingStep && <DecisionPanel stepId={pendingStep} step={info.steps[pendingStep]} card={[...cards].reverse().find(c => c.stepId === pendingStep)} onDecide={onDecide} />}
        {problem && <p role="alert" className="break-words">{problem}</p>}
        {['failed', 'interrupted'].includes(session.messages.at(-1)?.status ?? '') && <button type="button" disabled={controller.busy || !connected || !!boot.error} onClick={() => send(true)}>重试上一条消息</button>}
        <StartForm info={inputInfo} values={values} dense onValuesChange={next => {
          setValues(next);
          try { controller.carry(next); } catch (e) { setProblem(`会话保存失败：${String(e)}`); }
        }} disabled={controller.busy || !connected || !!boot.error} onStart={() => send()} submitLabel="发送" />
      </div>
    </div>
  </PlayerShell>;
}
