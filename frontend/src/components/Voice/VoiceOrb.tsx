import type { VoiceState } from '../../types';

interface VoiceOrbProps {
  state: VoiceState;
  isMuted: boolean;
}

export default function VoiceOrb({ state, isMuted }: VoiceOrbProps) {
  if (state === 'connecting') {
    return (
      <div className="relative w-10 h-10 flex items-center justify-center">
        <div className="absolute inset-0 rounded-full border-2 border-cvs-primary/30 border-t-cvs-primary animate-spin" />
        <div className="w-5 h-5 rounded-full bg-cvs-primary/20" />
      </div>
    );
  }

  if (state === 'error') {
    return (
      <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center">
        <svg className="w-5 h-5 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      </div>
    );
  }

  if (isMuted) {
    return (
      <div className="w-10 h-10 rounded-full bg-cvs-surface border border-cvs-border flex items-center justify-center">
        <svg className="w-5 h-5 text-cvs-text-tertiary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M17 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2" />
        </svg>
      </div>
    );
  }

  return (
    <div className="relative w-10 h-10 flex items-center justify-center">
      <div className="absolute inset-0 rounded-full bg-cvs-primary/10 animate-pulse" />
      <div className="absolute inset-1 rounded-full bg-cvs-primary/20 animate-pulse [animation-delay:150ms]" />
      <div className="w-5 h-5 rounded-full bg-cvs-primary animate-pulse [animation-delay:300ms]" />
    </div>
  );
}
