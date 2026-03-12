import { useState, useRef, useEffect } from 'react';
import { useChat } from '../../contexts/ChatContext';
import { useVoice } from '../../contexts/VoiceContext';
import VoicePanel from '../Voice/VoicePanel';

export default function ChatInput() {
  const { sendMessage, isStreaming, activeConversationId, messages } = useChat();
  const { voiceState, startVoice, stopVoice } = useVoice();
  const [text, setText] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const isVoiceActive = voiceState !== 'idle';
  const canSend = text.trim().length > 0 && !isStreaming && !!activeConversationId && !isVoiceActive;
  const canToggleVoice = !!activeConversationId && !isStreaming;

  const handleSubmit = () => {
    if (!canSend) return;
    sendMessage(text.trim());
    setText('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleVoiceToggle = () => {
    if (!canToggleVoice) return;
    if (isVoiceActive) {
      stopVoice();
    } else {
      startVoice(activeConversationId!, messages);
    }
  };

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 160) + 'px';
    }
  }, [text]);

  useEffect(() => {
    const handleGlobalKey = (e: KeyboardEvent) => {
      if (e.altKey && e.key.toLowerCase() === 'v') {
        e.preventDefault();
        handleVoiceToggle();
      }
    };
    window.addEventListener('keydown', handleGlobalKey);
    return () => window.removeEventListener('keydown', handleGlobalKey);
  }, [canToggleVoice, isVoiceActive, activeConversationId]);

  if (isVoiceActive) {
    return <VoicePanel />;
  }

  return (
    <div className="border-t border-cvs-border bg-white px-4 py-3 shrink-0">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-end gap-2 bg-cvs-surface rounded-2xl border border-cvs-border px-4 py-2 focus-within:border-cvs-primary focus-within:ring-2 focus-within:ring-cvs-primary-ring transition-all">
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              !activeConversationId
                ? 'Start a new conversation first...'
                : isStreaming
                  ? 'Waiting for response...'
                  : 'Type your message... (Enter to send, Shift+Enter for new line)'
            }
            disabled={!activeConversationId || isStreaming}
            rows={1}
            className="flex-1 bg-transparent text-sm text-cvs-text placeholder:text-cvs-text-tertiary resize-none outline-none disabled:opacity-50 py-1"
          />

          {/* Voice toggle button */}
          <button
            onClick={handleVoiceToggle}
            disabled={!canToggleVoice}
            className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center
                       text-cvs-text-secondary hover:text-cvs-primary hover:bg-cvs-primary-50
                       disabled:opacity-30 disabled:cursor-not-allowed transition-all active:scale-95"
            title="Start voice mode (Alt+V)"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4M12 1a3 3 0 00-3 3v4a3 3 0 006 0V4a3 3 0 00-3-3z" />
            </svg>
          </button>

          {/* Send button */}
          <button
            onClick={handleSubmit}
            disabled={!canSend}
            className="shrink-0 w-8 h-8 rounded-full bg-cvs-primary text-white flex items-center justify-center
                       hover:bg-cvs-primary-hover disabled:opacity-30 disabled:cursor-not-allowed
                       transition-all active:scale-95"
            title="Send message"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M5 12h14M12 5l7 7-7 7"
              />
            </svg>
          </button>
        </div>

        <p className="text-[10px] text-cvs-text-tertiary text-center mt-1.5">
          AI-powered assistant. Verify important details with CVS Pharmacy directly.
        </p>
      </div>
    </div>
  );
}
