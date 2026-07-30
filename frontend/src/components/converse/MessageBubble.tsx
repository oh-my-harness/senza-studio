import { memo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ChevronDown } from 'lucide-react';
import type { Message } from '../../types';

function _MessageBubble({ role, content, thinking }: { role: Message['role']; content: string; thinking?: string }) {
  const isUser = role === 'user';
  const [thinkingExpanded, setThinkingExpanded] = useState(false);

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] rounded-lg border px-3 py-2 ${
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
              <div className="mt-1 border-l-2 border-border pl-3 text-xs whitespace-pre-wrap overflow-hidden">
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
          <div className="text-sm/relaxed">
            {isUser ? (
              <p className="whitespace-pre-wrap">{content}</p>
            ) : (
              <div className="
                [&_h1]:text-xl [&_h1]:font-semibold [&_h1]:mt-3 [&_h1]:mb-2
                [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:mt-3 [&_h2]:mb-2
                [&_h3]:text-base [&_h3]:font-semibold [&_h3]:mt-2 [&_h3]:mb-1
                [&_p]:my-2
                [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:my-2
                [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:my-2
                [&_li]:my-0.5
                [&_a]:text-primary [&_a]:underline [&_a]:underline-offset-2
                [&_blockquote]:text-muted-foreground [&_blockquote]:border-l [&_blockquote]:pl-3 [&_blockquote]:my-2
                [&_code]:bg-muted [&_code]:rounded [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[0.875em]
                [&_pre]:bg-muted [&_pre]:my-3 [&_pre]:overflow-auto [&_pre]:rounded-md [&_pre]:p-3
                [&_pre_code]:bg-transparent [&_pre_code]:p-0
                [&_table]:my-3 [&_table]:w-full [&_table]:border-collapse
                [&_th]:border [&_th]:border-border [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_th]:font-semibold
                [&_td]:border [&_td]:border-border [&_td]:px-2 [&_td]:py-1
                [&_hr]:border-border [&_hr]:my-4
              ">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export const MessageBubble = memo(_MessageBubble);
