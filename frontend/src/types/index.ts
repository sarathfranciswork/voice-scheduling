export type Theme = 'red' | 'blue';

export interface Conversation {
  id: string;
  title: string;
  theme: Theme;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant' | 'tool_call' | 'tool_result';
  content: string;
  tool_name?: string | null;
  tool_call_id?: string | null;
  tool_args?: Record<string, unknown> | null;
  tool_result?: string | null;
  created_at: string;
}

export interface ConversationWithMessages extends Conversation {
  messages: Message[];
}

// WebSocket message types sent from server
export type WSEvent =
  | { type: 'chunk'; content: string }
  | { type: 'tool_start'; name: string; display: string }
  | { type: 'tool_result'; name: string; summary: string }
  | { type: 'done'; message_id: string; full_content: string }
  | { type: 'error'; message: string }
  | { type: 'pong' }
  | { type: 'conversation_created'; conversation: Conversation };

// WebSocket message types sent from client
export type WSClientMessage =
  | { type: 'user_message'; content: string }
  | { type: 'ping' };

// Voice mode types
export type VoiceState = 'idle' | 'connecting' | 'active' | 'error';

export interface TranscriptEntry {
  role: 'user' | 'assistant';
  text: string;
  timestamp: string;
  isFinal: boolean;
}
