export default function TypingIndicator() {
  return (
    <div className="flex items-center gap-1.5 px-4 py-2">
      <div className="flex items-center gap-1 bg-cvs-surface rounded-2xl px-4 py-3">
        <span className="typing-dot w-2 h-2 bg-cvs-text-tertiary rounded-full" />
        <span className="typing-dot w-2 h-2 bg-cvs-text-tertiary rounded-full" />
        <span className="typing-dot w-2 h-2 bg-cvs-text-tertiary rounded-full" />
      </div>
    </div>
  );
}
