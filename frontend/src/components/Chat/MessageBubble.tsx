import { renderMarkdown } from '../../lib/markdown';
import type { Message } from '../../types';

interface MessageBubbleProps {
  message: Message;
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} px-4 py-1.5`}>
      <div
        className={`
          max-w-[80%] md:max-w-[70%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed
          ${isUser
            ? 'bg-cvs-primary text-white rounded-br-md'
            : 'bg-cvs-surface text-cvs-text border border-cvs-border rounded-bl-md'
          }
        `}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div
            className="markdown-content"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }}
          />
        )}
      </div>
    </div>
  );
}

interface StreamingBubbleProps {
  content: string;
}

export function StreamingBubble({ content }: StreamingBubbleProps) {
  if (!content) return null;

  return (
    <div className="flex justify-start px-4 py-1.5">
      <div className="max-w-[80%] md:max-w-[70%] rounded-2xl rounded-bl-md px-4 py-2.5 text-sm leading-relaxed bg-cvs-surface text-cvs-text border border-cvs-border">
        <div
          className="markdown-content"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }}
        />
        <span className="inline-block w-0.5 h-4 bg-cvs-primary animate-pulse ml-0.5 align-text-bottom" />
      </div>
    </div>
  );
}
