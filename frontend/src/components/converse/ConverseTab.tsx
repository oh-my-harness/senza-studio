import { useState, useRef, useEffect } from 'react';
import { useProjectStore } from '../../store/projectStore';
import { useConverseWs } from '../../hooks/useConverseWs';
import { MessageBubble } from './MessageBubble';

export function ConverseTab() {
  const [input, setInput] = useState('');
  const conversation = useProjectStore((s) => s.conversation);
  const status = useProjectStore((s) => s.conversationStatus);
  const sendMessage = useProjectStore((s) => s.sendMessage);
  const { send } = useConverseWs();
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [conversation]);

  const handleSubmit = () => {
    if (!input.trim() || status === 'streaming') return;
    sendMessage(input);
    send(input);
    setInput('');
  };

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-2 min-h-0">
        {conversation.length === 0 && (
          <div className="text-muted-foreground text-sm text-center py-8">
            Describe the agent you want to build. The converser will refine your
            idea into a spec, then the coding agent generates the Senza project.
          </div>
        )}
        {conversation.map((msg, i) => (
          <MessageBubble key={i} role={msg.role} content={msg.content} />
        ))}
        {status === 'streaming' && (
          <div className="text-muted-foreground text-xs px-3 animate-pulse">streaming…</div>
        )}
        <div ref={endRef} />
      </div>
      <div className="shrink-0 border-t p-2 flex gap-2">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              handleSubmit();
            }
          }}
          placeholder="Describe the agent you want to build…"
          rows={2}
          className="flex-1 px-3 py-2 bg-[var(--input)] border rounded-lg resize-none focus:outline-none focus:ring-1 focus:ring-ring text-sm"
          disabled={status === 'streaming'}
        />
        <button
          onClick={handleSubmit}
          disabled={status === 'streaming' || !input.trim()}
          className="px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm disabled:opacity-50"
        >
          Send
        </button>
      </div>
    </div>
  );
}
