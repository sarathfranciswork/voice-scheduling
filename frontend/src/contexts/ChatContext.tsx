import {
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
  useEffect,
  type ReactNode,
} from 'react';
import type { Conversation, Message, WSEvent } from '../types';
import * as api from '../api/conversations';

interface ToolStatus {
  name: string;
  display: string;
  summary?: string;
  done: boolean;
}

interface ChatContextValue {
  conversations: Conversation[];
  activeConversationId: string | null;
  messages: Message[];
  streamingContent: string;
  isStreaming: boolean;
  toolStatuses: ToolStatus[];
  loadConversations: () => Promise<void>;
  createConversation: () => Promise<string>;
  selectConversation: (id: string) => Promise<void>;
  deleteConversation: (id: string) => Promise<void>;
  sendMessage: (content: string) => void;
}

const ChatContext = createContext<ChatContextValue | null>(null);

export function ChatProvider({ children }: { children: ReactNode }) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [streamingContent, setStreamingContent] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [toolStatuses, setToolStatuses] = useState<ToolStatus[]>([]);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadConversations = useCallback(async () => {
    const list = await api.listConversations();
    setConversations(list);
  }, []);

  const selectConversation = useCallback(async (id: string) => {
    // Close existing WebSocket
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    setActiveConversationId(id);
    setStreamingContent('');
    setIsStreaming(false);
    setToolStatuses([]);

    // Load messages
    const conv = await api.getConversation(id);
    setMessages(conv.messages.filter(m => m.role === 'user' || m.role === 'assistant'));

    // Connect WebSocket
    connectWebSocket(id);
  }, []);

  const connectWebSocket = useCallback((conversationId: string) => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const ws = new WebSocket(`${protocol}//${host}/ws/chat/${conversationId}`);

    ws.onopen = () => {
      console.log('WebSocket connected');
    };

    ws.onmessage = (event) => {
      const data: WSEvent = JSON.parse(event.data);
      handleWSEvent(data);
    };

    ws.onclose = () => {
      console.log('WebSocket disconnected');
      // Auto-reconnect if still on this conversation
      reconnectTimeout.current = setTimeout(() => {
        if (wsRef.current === ws) {
          connectWebSocket(conversationId);
        }
      }, 3000);
    };

    ws.onerror = (err) => {
      console.error('WebSocket error:', err);
    };

    wsRef.current = ws;
  }, []);

  const handleWSEvent = useCallback((event: WSEvent) => {
    switch (event.type) {
      case 'chunk':
        setStreamingContent((prev) => prev + event.content);
        break;

      case 'tool_start':
        setToolStatuses((prev) => [
          ...prev,
          { name: event.name, display: event.display, done: false },
        ]);
        break;

      case 'tool_result':
        setToolStatuses((prev) =>
          prev.map((t) =>
            t.name === event.name && !t.done
              ? { ...t, summary: event.summary, done: true }
              : t,
          ),
        );
        break;

      case 'done': {
        const assistantMsg: Message = {
          id: event.message_id,
          conversation_id: '',
          role: 'assistant',
          content: event.full_content,
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, assistantMsg]);
        setStreamingContent('');
        setIsStreaming(false);
        setToolStatuses([]);
        // Refresh conversation list to update titles/timestamps
        loadConversations();
        break;
      }

      case 'error':
        console.error('Server error:', event.message);
        setIsStreaming(false);
        setStreamingContent('');
        setToolStatuses([]);
        break;
    }
  }, [loadConversations]);

  const createConversation = useCallback(async () => {
    const conv = await api.createConversation();
    await loadConversations();
    await selectConversation(conv.id);
    return conv.id;
  }, [loadConversations, selectConversation]);

  const deleteConversation = useCallback(async (id: string) => {
    await api.deleteConversation(id);
    if (activeConversationId === id) {
      setActiveConversationId(null);
      setMessages([]);
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    }
    await loadConversations();
  }, [activeConversationId, loadConversations]);

  const sendMessage = useCallback((content: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      console.error('WebSocket not connected');
      return;
    }

    // Optimistically add user message
    const userMsg: Message = {
      id: `temp-${Date.now()}`,
      conversation_id: activeConversationId || '',
      role: 'user',
      content,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsStreaming(true);
    setStreamingContent('');
    setToolStatuses([]);

    wsRef.current.send(JSON.stringify({ type: 'user_message', content }));
  }, [activeConversationId]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (wsRef.current) wsRef.current.close();
      if (reconnectTimeout.current) clearTimeout(reconnectTimeout.current);
    };
  }, []);

  return (
    <ChatContext.Provider
      value={{
        conversations,
        activeConversationId,
        messages,
        streamingContent,
        isStreaming,
        toolStatuses,
        loadConversations,
        createConversation,
        selectConversation,
        deleteConversation,
        sendMessage,
      }}
    >
      {children}
    </ChatContext.Provider>
  );
}

export function useChat() {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error('useChat must be used within ChatProvider');
  return ctx;
}
