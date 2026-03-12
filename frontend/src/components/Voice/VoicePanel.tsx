import { useRef, useEffect } from 'react';
import { useVoice } from '../../contexts/VoiceContext';
import VoiceOrb from './VoiceOrb';

const TOOL_LABELS: Record<string, string> = {
  get_eligible_vaccines: 'Checking vaccine eligibility…',
  check_vaccine_eligibility: 'Verifying eligibility…',
  search_stores: 'Searching nearby stores…',
  get_available_time_slots: 'Finding time slots…',
  get_store_details: 'Loading store details…',
  soft_reserve_slot: 'Reserving your slot…',
  submit_patient_details: 'Saving your details…',
  get_questionnaire: 'Loading screening questions…',
  submit_questionnaire: 'Submitting answers…',
  get_user_schedule: 'Checking your schedule…',
  confirm_appointment: 'Confirming appointment…',
  address_typeahead: 'Looking up address…',
  get_patient_profile: 'Loading your profile…',
  get_my_appointments: 'Fetching appointments…',
  cancel_appointment: 'Cancelling appointment…',
};

export default function VoicePanel() {
  const { voiceState, isMuted, transcript, currentToolName, stopVoice, toggleMute } =
    useVoice();
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [transcript, currentToolName]);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && voiceState === 'active') {
        stopVoice();
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [voiceState, stopVoice]);

  if (voiceState === 'idle') return null;

  return (
    <div className="border-t border-cvs-border bg-white flex flex-col shrink-0" style={{ maxHeight: '50vh' }}>
      {/* Live transcript */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-4 py-3 space-y-2 min-h-[120px] max-h-[30vh] scrollbar-thin"
      >
        {transcript.length === 0 && voiceState === 'active' && !currentToolName && (
          <p className="text-sm text-cvs-text-tertiary text-center italic">
            Listening… say something to get started
          </p>
        )}

        {transcript.map((entry, i) => (
          <div
            key={i}
            className={`text-sm ${
              entry.role === 'user'
                ? 'text-cvs-text font-medium'
                : 'text-cvs-text-secondary'
            } ${!entry.isFinal ? 'opacity-60' : ''}`}
          >
            <span className="text-[10px] uppercase tracking-wider text-cvs-text-tertiary mr-1.5">
              {entry.role === 'user' ? 'You' : 'Agent'}:
            </span>
            {entry.text}
          </div>
        ))}

        {currentToolName && (
          <div className="flex items-center gap-2 text-xs text-cvs-primary">
            <div className="w-3 h-3 border-2 border-cvs-primary/30 border-t-cvs-primary rounded-full animate-spin" />
            {TOOL_LABELS[currentToolName] || `Running ${currentToolName}…`}
          </div>
        )}
      </div>

      {/* Orb + controls */}
      <div className="flex items-center justify-between px-4 py-3 border-t border-cvs-border/50 bg-cvs-surface/30">
        <div className="flex items-center gap-3">
          <VoiceOrb state={voiceState} isMuted={isMuted} />
          <span className="text-xs text-cvs-text-secondary">
            {voiceState === 'connecting'
              ? 'Connecting…'
              : isMuted
                ? 'Muted'
                : 'Listening'}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {voiceState === 'active' && (
            <button
              onClick={toggleMute}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                isMuted
                  ? 'bg-cvs-primary text-white hover:bg-cvs-primary-hover'
                  : 'bg-cvs-surface border border-cvs-border text-cvs-text hover:bg-cvs-border/50'
              }`}
              title={isMuted ? 'Unmute' : 'Mute'}
            >
              {isMuted ? (
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M17 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2" />
                </svg>
              ) : (
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4M12 1a3 3 0 00-3 3v4a3 3 0 006 0V4a3 3 0 00-3-3z" />
                </svg>
              )}
              {isMuted ? 'Unmute' : 'Mute'}
            </button>
          )}

          <button
            onClick={stopVoice}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-500 text-white text-xs font-medium
                       hover:bg-red-600 transition-colors"
            title="End voice session (Esc)"
          >
            <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
              <rect x="6" y="6" width="12" height="12" rx="2" />
            </svg>
            End Voice
          </button>
        </div>
      </div>
    </div>
  );
}
