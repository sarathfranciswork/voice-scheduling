import {
  createContext,
  useContext,
  useState,
  useRef,
  useCallback,
  type ReactNode,
} from 'react';
import { RealtimeAgent, RealtimeSession } from '@openai/agents/realtime';
import type { RealtimeItem } from '@openai/agents/realtime';
import { allVoiceTools } from '../voice/tools';
import type { VoiceState, TranscriptEntry, Message } from '../types';

interface VoiceContextValue {
  voiceState: VoiceState;
  isMuted: boolean;
  transcript: TranscriptEntry[];
  currentToolName: string | null;
  startVoice: (conversationId: string, textHistory?: Message[]) => Promise<void>;
  stopVoice: () => void;
  toggleMute: () => void;
}

const VoiceContext = createContext<VoiceContextValue | null>(null);

interface VoiceProviderProps {
  children: ReactNode;
  onSessionEnd?: (conversationId: string) => void;
}

function extractTranscript(history: RealtimeItem[]): TranscriptEntry[] {
  const entries: TranscriptEntry[] = [];
  for (const item of history) {
    if (item.type !== 'message') continue;
    if (item.role === 'system') continue;

    const role = item.role as 'user' | 'assistant';
    const isFinal = 'status' in item ? item.status === 'completed' : true;

    for (const content of item.content) {
      let text = '';
      if ('text' in content && content.text) {
        text = content.text;
      } else if ('transcript' in content && content.transcript) {
        text = content.transcript;
      }
      if (text) {
        entries.push({
          role,
          text,
          timestamp: new Date().toISOString(),
          isFinal,
        });
      }
    }
  }
  return entries;
}

export function VoiceProvider({ children, onSessionEnd }: VoiceProviderProps) {
  const [voiceState, setVoiceState] = useState<VoiceState>('idle');
  const [isMuted, setIsMuted] = useState(false);
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [currentToolName, setCurrentToolName] = useState<string | null>(null);

  const sessionRef = useRef<RealtimeSession | null>(null);
  const conversationIdRef = useRef<string | null>(null);

  const startVoice = useCallback(async (conversationId: string, textHistory?: Message[]) => {
    if (sessionRef.current) return;

    setVoiceState('connecting');
    setTranscript([]);
    setCurrentToolName(null);
    setIsMuted(false);
    conversationIdRef.current = conversationId;

    try {
      const tokenRes = await fetch('/api/realtime/token');
      if (!tokenRes.ok) {
        throw new Error(`Failed to get voice token: ${tokenRes.status}`);
      }
      const { key, instructions, voice } = await tokenRes.json();

      const agent = new RealtimeAgent({
        name: 'CVS Vaccine Assistant',
        instructions,
        voice,
        tools: allVoiceTools,
      });

      const session = new RealtimeSession(agent, {
        model: 'gpt-realtime',
        config: {
          inputAudioTranscription: {
            model: 'gpt-4o-mini-transcribe',
          },
          turnDetection: {
            type: 'semantic_vad',
            eagerness: 'medium',
            createResponse: true,
            interruptResponse: true,
          },
        },
      });

      session.on('history_updated', (history: RealtimeItem[]) => {
        setTranscript(extractTranscript(history));
      });

      session.on('agent_tool_start', (_ctx, _agent, tool) => {
        setCurrentToolName(tool.name);
      });

      session.on('agent_tool_end', () => {
        setCurrentToolName(null);
      });

      session.on('error', (err) => {
        console.error('Voice session error:', err);
        setVoiceState('error');
      });

      await session.connect({ apiKey: key });

      if (textHistory && textHistory.length > 0) {
        const historyItems: RealtimeItem[] = textHistory
          .filter((m) => m.role === 'user' || m.role === 'assistant')
          .slice(-10)
          .map((m, i) => {
            if (m.role === 'user') {
              return {
                itemId: `text-${i}`,
                type: 'message' as const,
                role: 'user' as const,
                status: 'completed' as const,
                content: [{ type: 'input_text' as const, text: m.content }],
              };
            }
            return {
              itemId: `text-${i}`,
              type: 'message' as const,
              role: 'assistant' as const,
              status: 'completed' as const,
              content: [{ type: 'output_text' as const, text: m.content }],
            };
          });
        session.updateHistory(historyItems);
      }

      sessionRef.current = session;
      setVoiceState('active');
    } catch (err) {
      console.error('Failed to start voice session:', err);
      setVoiceState('error');
      sessionRef.current = null;
    }
  }, []);

  const stopVoice = useCallback(() => {
    const session = sessionRef.current;
    const convId = conversationIdRef.current;

    if (session) {
      const finalTranscript = extractTranscript(session.history);
      session.close();
      sessionRef.current = null;

      if (convId && finalTranscript.length > 0) {
        const msgs = finalTranscript
          .filter((e) => e.isFinal && e.text.trim())
          .map((e) => ({ role: e.role, content: e.text }));

        if (msgs.length > 0) {
          fetch(`/api/realtime/conversations/${convId}/messages`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ messages: msgs }),
          })
            .then(() => {
              if (convId && onSessionEnd) onSessionEnd(convId);
            })
            .catch((err) =>
              console.error('Failed to persist voice transcript:', err),
            );
        } else if (convId && onSessionEnd) {
          onSessionEnd(convId);
        }
      }
    }

    setVoiceState('idle');
    setTranscript([]);
    setCurrentToolName(null);
    setIsMuted(false);
    conversationIdRef.current = null;
  }, [onSessionEnd]);

  const toggleMute = useCallback(() => {
    const session = sessionRef.current;
    if (!session) return;

    const newMuted = !isMuted;
    session.mute(newMuted);
    setIsMuted(newMuted);
  }, [isMuted]);

  return (
    <VoiceContext.Provider
      value={{
        voiceState,
        isMuted,
        transcript,
        currentToolName,
        startVoice,
        stopVoice,
        toggleMute,
      }}
    >
      {children}
    </VoiceContext.Provider>
  );
}

export function useVoice() {
  const ctx = useContext(VoiceContext);
  if (!ctx) throw new Error('useVoice must be used within VoiceProvider');
  return ctx;
}
