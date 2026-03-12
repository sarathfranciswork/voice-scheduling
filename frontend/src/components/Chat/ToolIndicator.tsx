interface ToolIndicatorProps {
  name: string;
  display: string;
  summary?: string;
  done: boolean;
}

export default function ToolIndicator({ display, summary, done }: ToolIndicatorProps) {
  return (
    <div className="flex items-center gap-2 px-4 py-1">
      <div className="flex items-center gap-2 bg-cvs-primary-50 border border-cvs-primary-200 rounded-full px-3 py-1.5 text-xs">
        {!done ? (
          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-cvs-primary opacity-40" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-cvs-primary" />
          </span>
        ) : (
          <svg className="w-3.5 h-3.5 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        )}
        <span className={done ? 'text-green-700' : 'text-cvs-primary'}>
          {done && summary ? summary : display}
        </span>
      </div>
    </div>
  );
}
