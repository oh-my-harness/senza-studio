import type { ConversationSession } from './conversation';

export interface ConversationStorage {
  list(): ConversationSession[];
  load(id: string): ConversationSession;
  save(session: ConversationSession): void;
}

/** Browser-local, per host/project. No runtime keys, spec or non-carry inputs. */
export class LocalConversationStorage implements ConversationStorage {
  private prefix: string;
  private versions = new Map<string, string | null>();
  constructor(private storage: Storage, private scope: string, private carryFields: string[]) {
    this.prefix = `senza:conversation:v1:${encodeURIComponent(scope)}:`;
  }
  private decode(raw: string): ConversationSession {
    const data = JSON.parse(raw);
    if (data.version !== 1 || data.scope !== this.scope || typeof data.id !== 'string' ||
        typeof data.title !== 'string' || typeof data.createdAt !== 'string' || typeof data.updatedAt !== 'string' ||
        !data.carry || typeof data.carry !== 'object' || !Array.isArray(data.messages) ||
        data.messages.some((m: Record<string, unknown>, i: number) => !m || typeof m.id !== 'string' ||
          m.role !== (i % 2 === 0 ? 'user' : 'agent') || typeof m.text !== 'string' || typeof m.timestamp !== 'string' ||
          !['done', 'pending', 'failed', 'interrupted'].includes(String(m.status))) || data.messages.length % 2 !== 0) {
      throw new Error('会话数据格式无效；已保留原始数据，请勿覆盖。');
    }
    return {
      id: data.id, scope: this.scope, title: data.title, createdAt: data.createdAt, updatedAt: data.updatedAt,
      carry: Object.fromEntries(this.carryFields.filter(k => typeof data.carry[k] === 'string').map(k => [k, data.carry[k]])),
      messages: data.messages.map((m: Record<string, string>) => ({ id: m.id, role: m.role, text: m.status === 'pending' ? '页面已关闭或刷新，执行结果未知；重试可能重复业务操作。' : m.text,
        status: m.status === 'pending' ? 'interrupted' : m.status, timestamp: m.timestamp })),
    };
  }
  list() {
    const sessions: ConversationSession[] = [];
    for (let i = 0; i < this.storage.length; i++) {
      const key = this.storage.key(i);
      if (!key?.startsWith(this.prefix)) continue;
      const raw = this.storage.getItem(key);
      if (raw) sessions.push(this.decode(raw));
    }
    return sessions.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  }
  load(id: string) {
    const raw = this.storage.getItem(this.prefix + id);
    if (!raw) throw new Error('找不到此会话');
    const session = this.decode(raw);
    if (session.id !== id) throw new Error('会话标识不匹配');
    this.versions.set(id, raw);
    return session;
  }
  save(session: ConversationSession) {
    if (session.scope !== this.scope) throw new Error('会话不属于当前 Agent/Project');
    const key = this.prefix + session.id;
    const previous = this.storage.getItem(key);
    if (previous !== (this.versions.get(session.id) ?? null)) {
      throw new Error('此会话已在其他页面更新，请刷新后继续，避免覆盖历史。');
    }
    const safe = { version: 1, ...session,
      carry: Object.fromEntries(this.carryFields.filter(k => typeof session.carry[k] === 'string').map(k => [k, session.carry[k]])),
    };
    const raw = JSON.stringify(safe);
    this.storage.setItem(key, raw); // Quota/security errors must reach the UI before invocation.
    this.versions.set(session.id, raw);
  }
}
