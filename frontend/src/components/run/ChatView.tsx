import { useState, useRef, useEffect } from 'react';
import { useProjectStore } from '../../store/projectStore';
import { useRunWs } from '../../hooks/useRunWs';
import { MessageBubble } from '../converse/MessageBubble';

export function ChatView() {
  const [input, setInput] = useState('');
  const messages = useProjectStore((s) => s.runMessages);
  const runStatus = useProjectStore((s) => s.runStatus);
  const sendRunMessage = useProjectStore((s) => s.sendRunMessage);
  const { sendInput } = useRunWs();
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [messages]);

  const handleSubmit = () => {
    if (!input.trim()) return;
    sendRunMessage(input);
    sendInput(input);
    setInput('');
  };

  return (
    <div className="flex flex-col flex-1 overflow-hidden min-h-0">
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-2 min-h-0">
        {messages.length === 0 && (
          <div className="text-muted-foreground text-sm text-center py-8">
            Start a run to chat with your agent.
          </div>
        )}
        {messages.map((msg, i) => (
          <MessageBubble key={i} role={msg.role} content={msg.content} />
        ))}
        <div ref={endRef} />
      </div>
      <div className="shrink-0 border-t p-2 flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
          placeholder="Type a message…"
          className="flex-1 px-3 py-2 bg-[var(--input)] border rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-ring"
          disabled={runStatus !== 'waiting_input' && runStatus !== 'running'}
        />
        <button
          onClick={handleSubmit}
          className="px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm"
        >
          Send
        </button>
      </div>
    </div>
  );
}
