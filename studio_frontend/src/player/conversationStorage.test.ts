import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ConversationController, newSession, inputDefaults } from './conversation';
import { LocalConversationStorage } from './conversationStorage';
import type { AgentInfo } from './types';
export class MemoryStorage implements Storage {
  data = new Map<string, string>();
  get length() { return this.data.size; }
  clear() { this.data.clear(); }
  key(n: number) { return [...this.data.keys()][n] ?? null; }
  getItem(k: string) { return this.data.get(k) ?? null; }
  setItem(k: string, v: string) { this.data.set(k, v); }
  removeItem(k: string) { this.data.delete(k); }
}
const info: AgentInfo = {
  title: 'Tutor', description: '', layout: 'conversation', theme: { accent: '#2563eb', mode: 'light', density: 'comfortable', logo: '' }, error: null,
  inputs: ['message', 'course', 'history'].map(name => ({ name, label: name, multiline: true, placeholder: '', ...(name === 'course' ? { default: 'math' } : {}) })),
  conversation: { message_input: 'message', carry_inputs: ['course'], history_input: 'history', history_max_messages: 20, history_max_chars: 12000 }, steps: {},
};
const cards = [{ stepId: 'reply', stepName: 'reply', text: 'remember this', status: 'done' as const }];
describe('durable conversations', () => {
  let storage: MemoryStorage;
  beforeEach(() => { storage = new MemoryStorage(); });
  it('saves two rounds, recreates the adapter/controller, restores four messages and resumes round three with context', () => {
    const store = new LocalConversationStorage(storage, 'studio:a', ['course']);
    const c = new ConversationController(info, newSession('studio:a'), vi.fn(), s => store.save(s));
    c.rename('Session A');
    for (const message of ['first', 'second']) {
      c.start({ ...inputDefaults(info), message }, vi.fn());
      c.observe('done', cards, null, 'succeeded', true);
    }
    const storeAfterReload = new LocalConversationStorage(storage, 'studio:a', ['course']);
    const restored = storeAfterReload.load(storeAfterReload.list()[0].id);
    expect(restored.title).toBe('Session A');
    expect(restored.messages).toHaveLength(4);
    expect(restored.carry).toEqual({ course: 'math' });
    const resumed = new ConversationController(info, restored, vi.fn(), s => storeAfterReload.save(s));
    const invoke = vi.fn();
    resumed.start({ ...restored.carry, message: 'third' }, invoke);
    expect(invoke.mock.calls[0][0].course).toBe('math');
    expect(JSON.parse(invoke.mock.calls[0][0].history)).toHaveLength(4);
    resumed.observe('done', cards, null, 'succeeded', true);
    expect(storeAfterReload.load(restored.id).messages).toHaveLength(6);
    const b = newSession('studio:a'); storeAfterReload.save(b);
    expect(storeAfterReload.load(b.id).messages).toHaveLength(0);
    expect(storeAfterReload.load(restored.id).messages).toHaveLength(6);
  });
  it('isolates project/export scopes and persists only configured carry fields', () => {
    const store = new LocalConversationStorage(storage, 'studio:a', ['course']);
    const a = { ...newSession('studio:a'), carry: { course: 'math', api_key: 'SECRET', message: 'not carry' } };
    store.save(a);
    expect(JSON.stringify([...storage.data.values()])).not.toContain('SECRET');
    for (const scope of ['studio:b', 'export:a']) expect(new LocalConversationStorage(storage, scope, ['course']).list()).toEqual([]);
    expect(() => store.save(newSession('studio:b'))).toThrow('不属于');
  });
  it('restores in-flight invocation as unknown and never retries automatically', () => {
    const store = new LocalConversationStorage(storage, 'a', ['course']);
    const c = new ConversationController(info, newSession('a'), vi.fn(), s => store.save(s));
    c.start({ message: 'first', course: 'math' }, vi.fn());
    const restored = new LocalConversationStorage(storage, 'a', ['course']).load(c.session.id);
    expect(restored.messages.at(-1)?.status).toBe('interrupted');
    expect(restored.messages.at(-1)?.text).toContain('结果未知');
  });
  it('does not invoke when durable saving fails; preserves previous history', () => {
    const store = new LocalConversationStorage(storage, 'a', ['course']);
    const c = new ConversationController(info, newSession('a'), vi.fn(), s => store.save(s));
    c.start({ message: 'first', course: 'math' }, vi.fn()); c.observe('done', cards, null, 'succeeded', true);
    const before = storage.getItem(storage.key(0)!);
    vi.spyOn(storage, 'setItem').mockImplementation(() => { throw Error('quota exceeded'); });
    const invoke = vi.fn();
    expect(() => c.start({ message: 'second', course: 'math' }, invoke)).toThrow('quota');
    expect(invoke).not.toHaveBeenCalled(); expect(c.busy).toBe(false);
    expect(storage.getItem(storage.key(0)!)).toBe(before);
    expect(c.session.messages).toHaveLength(2);
  });
  it('keeps completed output in memory with a visible save failure to its caller', () => {
    const store = new LocalConversationStorage(storage, 'a', ['course']);
    const c = new ConversationController(info, newSession('a'), vi.fn(), s => store.save(s));
    c.start({ message: 'first', course: 'math' }, vi.fn());
    vi.spyOn(storage, 'setItem').mockImplementation(() => { throw Error('quota'); });
    expect(() => c.observe('done', cards, null, 'succeeded', true)).toThrow('quota');
    expect(c.session.messages.at(-1)?.text).toBe('remember this');
  });
  it('detects stale updates from another tab and refuses to overwrite', () => {
    const first = new LocalConversationStorage(storage, 'a', []);
    const a = newSession('a'); first.save(a);
    const second = new LocalConversationStorage(storage, 'a', []); second.load(a.id);
    first.save({ ...a, title: 'updated' });
    expect(() => second.save({ ...a, title: 'stale' })).toThrow('其他页面');
    expect(first.load(a.id).title).toBe('updated');
  });
  it('reports corrupt data rather than deleting it or hiding prior sessions', () => {
    storage.setItem('senza:conversation:v1:a:bad', '{broken');
    expect(() => new LocalConversationStorage(storage, 'a', []).list()).toThrow();
    expect(storage.length).toBe(1);
  });
});
