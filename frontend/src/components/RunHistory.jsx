const DOT = {
  planning: 'bg-blue-500',
  running: 'bg-blue-500',
  completed: 'bg-green-500',
  partial: 'bg-amber-500',
  failed: 'bg-red-500',
}

export default function RunHistory({ runs, selectedRunId, onSelect }) {
  return (
    <aside className="flex min-h-[620px] flex-col gap-1 border-b border-line p-3.5 lg:border-r lg:border-b-0">
      <span className="px-2.5 pb-2.5 font-mono text-[10px] tracking-[0.16em] uppercase text-ink-3">
        Runs
      </span>

      {runs.length === 0 && (
        <p className="px-2.5 text-[12.5px] text-ink-3">No runs yet.</p>
      )}

      {runs.map((run, i) => {
        const selected = run.runId === selectedRunId
        const live = run.status === 'running' || run.status === 'planning'
        return (
          <button
            key={run.runId}
            type="button"
            onClick={() => onSelect(run.runId)}
            style={{ animationDelay: `${i * 50}ms` }}
            className={`animate-fade-up relative flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left transition-colors ${
              selected ? 'bg-sel' : 'hover:bg-panel'
            }`}
          >
            {selected && (
              <span className="absolute top-3 bottom-3 left-0 w-0.5 rounded-sm bg-acc" />
            )}
            <span
              className={`size-1.5 shrink-0 rounded-full ${DOT[run.status] || 'bg-ink-3'} ${
                live ? 'animate-dot-pulse' : ''
              }`}
            />
            <span
              title={run.goal}
              className={`line-clamp-2 flex-1 text-[12.5px] leading-snug ${
                selected ? 'text-ink' : 'text-ink-2'
              }`}
            >
              {run.goal}
            </span>
          </button>
        )
      })}
    </aside>
  )
}
