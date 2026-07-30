import { memo, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import type { Message } from '../../types';

function _MessageBubble({ role, content, thinking }: { role: Message['role']; content: string; thinking?: string }) {
  const isUser = role === 'user';
  const [thinkingExpanded, setThinkingExpanded] = useState(false);

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

        {/* Thinking section — collapsible */}
        {thinking && thinking.trim() && (
          <div
            className="mb-2 cursor-pointer text-muted-foreground"
            onClick={() => setThinkingExpanded(!thinkingExpanded)}
          >
            <div className="flex items-center gap-1 text-xs font-medium">
              <ChevronDown
                className={`size-3 shrink-0 transition-transform duration-200 ${thinkingExpanded ? '' : '-rotate-90'}`}
              />
              Thinking
            </div>
            {thinkingExpanded && (
              <div className="mt-1 border-l-2 border-border pl-3 text-xs whitespace-pre-wrap">
                {thinking}
              </div>
            )}
            {!thinkingExpanded && (
              <div className="text-xs overflow-hidden text-ellipsis whitespace-nowrap">
                {thinking.slice(0, 80)}…
              </div>
            )}
          </div>
        )}

        {/* Answer */}
        {content && (
          <pre className="whitespace-pre-wrap text-sm font-sans leading-relaxed">
            {content}
          </pre>
        )}
      </div>
    </div>
  );
}

export const MessageBubble = memo(_MessageBubble);
