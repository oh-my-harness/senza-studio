import { memo } from 'react';
import type { Message } from '../../types';

function _MessageBubble({ role, content }: { role: Message['role']; content: string }) {
  const isUser = role === 'user';
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[80%] rounded-lg border px-3 py-2 ${
          isUser
            ? 'bg-primary text-primary-foreground border-primary'
            : 'bg-card text-card-foreground border-border'
        }`}
      >
        <div className="text-[0.625rem] font-medium uppercase tracking-wide opacity-60 mb-1">
          {role}
        </div>
        <pre className="whitespace-pre-wrap text-sm font-sans leading-relaxed">
          {content}
        </pre>
      </div>
    </div>
  );
}

export const MessageBubble = memo(_MessageBubble);
