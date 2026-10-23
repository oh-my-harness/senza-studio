import { isStartReady } from './StartForm';
import type { AgentInfo, RunCard } from './types';

export interface ConversationConfig {
  message_input: string;
  carry_inputs: string[];
  history_input?: string;
  history_max_messages: number;
  history_max_chars: number;
}
export interface ConversationMessage {
  id: string;
  role: 'user' | 'agent';
  text: string;
  status: 'done' | 'pending' | 'failed' | 'interrupted';
  timestamp: string;
}
export interface ConversationSession {
  id: string;
  scope: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  carry: Record<string, string>;
  messages: ConversationMessage[];
}
const id = () => {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  // randomUUID is unavailable on HTTP LAN origins; IDs are identifiers, not credentials.
  if (globalThis.crypto?.getRandomValues) return Array.from(globalThis.crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
};
export function newSession(scope: string): ConversationSession {
  const now = new Date().toISOString();
  return { id: id(), scope, title: '新对话', createdAt: now, updatedAt: now, carry: {}, messages: [] };
}
export function inputDefaults(info: AgentInfo): Record<string, string> {
  return Object.fromEntries(info.inputs.filter(f => f.default !== undefined).map(f => [f.name, f.default!]));
}
export function conversationInputs(info: AgentInfo, values: Record<string, string>, session: ConversationSession) {
  const config = info.conversation!;
  const fields = info.inputs.filter(f => f.name !== config.history_input);
  if (!isStartReady(fields, values) || !values[config.message_input]?.trim()) {
    throw new Error('请填写所有必填输入和消息');
  }
  const inputs = Object.fromEntries(fields.filter(f => values[f.name] !== undefined).map(f => [f.name, values[f.name]]));
  if (config.history_input) {
    const selected: { role: string; content: string }[] = [];
    // Only completed turns are context. Failed/pending attempts remain in UI history.
    for (let i = session.messages.length - 2; i >= 0; i -= 2) {
      const user = session.messages[i], agent = session.messages[i + 1];
      if (user?.role !== 'user' || agent?.role !== 'agent' || agent.status !== 'done') continue;
      const pair = [{ role: 'user', content: user.text }, { role: 'assistant', content: agent.text }];
      if (selected.length + 2 > config.history_max_messages || JSON.stringify([...pair, ...selected]).length > config.history_max_chars) break;
      selected.unshift(...pair);
    }
    inputs[config.history_input] = JSON.stringify(selected);
  }
  return inputs;
}

/** A single invocation gate, shared by both hosts. The UI never infers success from text. */
export class ConversationController {
  session: ConversationSession;
  busy = false;
  private active: string | null = null;
  constructor(public info: AgentInfo, session: ConversationSession, private changed: () => void, private persist?: (session: ConversationSession) => void) {
    this.session = session;
  }
  private update(session: ConversationSession) {
    const next = { ...session, updatedAt: new Date().toISOString() };
    this.persist?.(next);
    this.session = next;
    this.changed();
  }
  rename(title: string) { this.update({ ...this.session, title }); }
  carry(values: Record<string, string>) {
    const carry = Object.fromEntries(this.info.conversation!.carry_inputs.filter(k => values[k] !== undefined).map(k => [k, values[k]]));
    if (JSON.stringify(carry) !== JSON.stringify(this.session.carry)) this.update({ ...this.session, carry });
  }
  start(values: Record<string, string>, invoke: (inputs: Record<string, string>) => void, retry = false) {
    if (this.busy) return false;
    const last = this.session.messages.at(-1);
    if (retry && (!last || !['failed', 'interrupted'].includes(last.status))) return false;
    const message = retry ? this.session.messages.at(-2)!.text : values[this.info.conversation!.message_input];
    const inputs = conversationInputs(this.info, { ...values, [this.info.conversation!.message_input]: message }, this.session);
    this.carry(values);
    this.busy = true;
    const agentId = retry ? last!.id : id();
    this.active = agentId;
    const now = new Date().toISOString();
    const messages = retry
      ? this.session.messages.map(m => m.id === agentId ? { ...m, text: '', status: 'pending' as const } : m)
      : [...this.session.messages,
          { id: id(), role: 'user' as const, text: message, status: 'done' as const, timestamp: now },
          { id: agentId, role: 'agent' as const, text: '', status: 'pending' as const, timestamp: now }];
    try { this.update({ ...this.session, title: this.session.messages.length || this.session.title !== '新对话' ? this.session.title : message.slice(0, 60), messages }); }
    catch (e) { this.busy = false; this.active = null; throw e; }
    try { invoke(inputs); } catch (e) { this.finish('failed', String(e)); }
    return true;
  }
  observe(phase: string, cards: RunCard[], error: string | null, finishedState: string | null, connected: boolean) {
    if (!this.busy) return;
    if (!connected) { this.finish('interrupted', '连接中断，执行结果未知；重试可能重复业务操作。'); return; }
    // A stream error may precede workflow_done. Keep the gate closed until
    // the host acknowledges termination, so a retry cannot consume a late result.
    if (phase !== 'done') return;
    if (error) { this.finish('failed', error); return; }
    if (finishedState !== 'succeeded') { this.finish('failed', `执行未成功：${finishedState ?? '未知状态'}`); return; }
    const visible = cards.filter(c => c.status === 'done' && this.info.steps[c.stepId]?.display !== 'none' && c.text.trim());
    const answer = [...visible].reverse().find(c => !this.info.steps[c.stepId]?.terminal) ?? visible.at(-1);
    this.finish('done', answer?.text ?? '执行完成（无文本输出）');
  }
  private finish(status: ConversationMessage['status'], text: string) {
    if (!this.active) return;
    const active = this.active;
    this.busy = false;
    this.active = null;
    const next = { ...this.session, messages: this.session.messages.map(m => m.id === active ? { ...m, status, text } : m) };
    try { this.update(next); }
    catch (e) { this.session = next; this.changed(); throw e; }
  }
}
