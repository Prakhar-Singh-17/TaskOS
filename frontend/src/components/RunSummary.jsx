import { useEffect, useState } from 'react'

const STATUS_TONE = {
  planning: 'border-ink-3/30 bg-ink-3/10 text-ink-2',
  running: 'border-blue-500/30 bg-blue-500/12 text-blue-600 dark:text-blue-300',
  completed: 'border-green-500/30 bg-green-500/12 text-green-600 dark:text-green-400',
  partial: 'border-amber-500/30 bg-amber-500/12 text-amber-600 dark:text-amber-400',
  failed: 'border-red-500/30 bg-red-500/12 text-red-600 dark:text-red-400',
}

function Stat({ label, value, tone = 'text-ink' }) {
  return (
    <div className="flex flex-col gap-0.75">
      <span className="font-mono text-[10px] tracking-[0.14em] uppercase text-ink-3">{label}</span>
      <span className={`font-mono text-[17px] ${tone}`}>{value}</span>
    </div>
  )
}

function elapsed(run) {
  // The API returns finishedAt (see backend/taskos/api/app.py), not
  // completedAt -- without this a completed run's "Elapsed" stat would
  // keep ticking upward against Date.now() forever instead of freezing.
  const start = run.createdAt ? new Date(run.createdAt).getTime() : null
  if (!start) return '—'
  const end = run.finishedAt ? new Date(run.finishedAt).getTime() : Date.now()
  const s = Math.max(0, Math.round((end - start) / 1000))
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

export default function RunSummary({ run }) {
  const tasks = run.tasks || []
  const done = tasks.filter((t) => t.status === 'done').length
  const retries = tasks.reduce((n, t) => n + Math.max(0, t.attempts.length - 1), 0)
  const running = run.status === 'running' || run.status === 'planning'

  // elapsed() is derived from real timestamps (createdAt/finishedAt), so the
  // value itself is always accurate -- but this component only re-renders on
  // prop changes (a websocket event), which can be many seconds apart. Force
  // a re-render every second while the run is live so the clock visibly
  // ticks; once finished, finishedAt freezes the value and this stops.
  const [, tick] = useState(0)
  useEffect(() => {
    if (!running) return
    const id = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(id)
  }, [running])

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-5">
        <h2 className="m-0 max-w-[620px] font-serif text-[30px] leading-[1.16] font-normal tracking-tight text-ink text-pretty">
          {run.goal}
        </h2>

        <div className="flex shrink-0 items-center gap-5 pt-1">
          <Stat label="Elapsed" value={elapsed(run)} />
          <Stat
            label="Tasks"
            value={
              <>
                {done}
                <span className="text-ink-3">/{tasks.length}</span>
              </>
            }
          />
          {retries > 0 && (
            <Stat label="Retries" value={retries} tone="text-amber-600 dark:text-amber-400" />
          )}
          <span
            className={`inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-[11px] font-semibold tracking-[0.08em] uppercase ${
              STATUS_TONE[run.status] || STATUS_TONE.planning
            }`}
          >
            {running && <span className="animate-dot-pulse size-1.5 rounded-full bg-current" />}
            {run.status}
          </span>
        </div>
      </div>

      {run.error && <p className="m-0 text-[13px] text-red-600 dark:text-red-400">{run.error}</p>}
    </div>
  )
}
