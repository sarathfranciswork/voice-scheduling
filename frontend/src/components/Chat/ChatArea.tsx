import { useRef, useEffect } from 'react';
import { useChat } from '../../contexts/ChatContext';
import MessageBubble, { StreamingBubble } from './MessageBubble';
import ToolIndicator from './ToolIndicator';
import TypingIndicator from './TypingIndicator';

export default function ChatArea() {
  const { messages, streamingContent, isStreaming, toolStatuses, activeConversationId } = useChat();
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const shouldAutoScroll = useRef(true);

  // Track if user has scrolled up
  const handleScroll = () => {
    if (!containerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
    shouldAutoScroll.current = scrollHeight - scrollTop - clientHeight < 80;
  };

  // Auto-scroll to bottom
  useEffect(() => {
    if (shouldAutoScroll.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, streamingContent, toolStatuses]);

  if (!activeConversationId) {
    return (
      <div className="flex-1 flex items-center justify-center bg-white">
        <div className="text-center px-6">
          <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-cvs-primary-50 flex items-center justify-center">
            <svg className="w-8 h-8 text-cvs-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
              />
            </svg>
          </div>
          <h2 className="text-lg font-semibold text-cvs-text mb-2">
            Welcome to CVS Vaccine Scheduling
          </h2>
          <p className="text-sm text-cvs-text-secondary max-w-sm">
            I can help you schedule a vaccine appointment at your nearest CVS Pharmacy.
            Start a new conversation to get started!
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      onScroll={handleScroll}
      className="flex-1 overflow-y-auto scrollbar-thin bg-white"
    >
      <div className="max-w-3xl mx-auto py-4">
        {messages.length === 0 && !isStreaming && (
          <div className="text-center py-12 px-6">
            <p className="text-sm text-cvs-text-secondary">
              Hi! Tell me which vaccine you'd like to schedule and your date of birth to get started.
            </p>
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {/* Tool status indicators */}
        {toolStatuses.map((tool, i) => (
          <ToolIndicator key={`${tool.name}-${i}`} {...tool} />
        ))}

        {/* Streaming content */}
        {streamingContent && <StreamingBubble content={streamingContent} />}

        {/* Typing indicator when waiting for first token */}
        {isStreaming && !streamingContent && toolStatuses.length === 0 && (
          <TypingIndicator />
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}
