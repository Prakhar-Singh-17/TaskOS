import { useState } from 'react'

const TONE = {
  run_created: { dot: 'bg-ink-3', type: 'text-ink-2' },
  plan_created: { dot: 'bg-ink-3', type: 'text-ink-2' },
  task_started: { dot: 'bg-blue-500', type: 'text-blue-600 dark:text-blue-300' },
  tool_call: { dot: 'bg-acc', type: 'text-acc' },
  task_completed: { dot: 'bg-green-500', type: 'text-green-600 dark:text-green-400' },
  task_retrying: { dot: 'bg-amber-500', type: 'text-amber-600 dark:text-amber-400' },
  task_failed: { dot: 'bg-red-500', type: 'text-red-600 dark:text-red-400' },
  task_blocked: { dot: 'bg-red-500', type: 'text-red-600 dark:text-red-400' },
  run_completed: { dot: 'bg-ink-3', type: 'text-ink-2' },
}

function summarize(event) {
  const p = event.payload || {}
  switch (event.eventType) {
    case 'tool_call':
      return `${p.tool} → ${p.ok ? 'ok' : 'failed'} (${p.durationMs}ms)`
    case 'task_started':
      return p.description
    case 'task_completed':
      return `attempt ${p.attempt} succeeded`
    case 'task_retrying':
      return `attempt ${p.attempt} failed (${p.failureKind}) — retrying`
    case 'task_failed':
      return `attempt ${p.attempt} failed permanently (${p.failureKind})`
    case 'task_blocked':
      return p.reason
    case 'plan_created':
      return `${p.tasks?.length ?? 0} task(s) planned`
    case 'run_created':
      return p.goal
    case 'run_completed':
      return `status: ${p.status}`
    default:
      return ''
  }
}

// Still fully generic over event shape -- it never special-cases an agent or a
// tool name, so a new MCP tool's events show up with zero changes here.
export default function EventLog({ events }) {
  const [expandedId, setExpandedId] = useState(null)

  return (
    <section className="flex flex-col gap-2.5">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] tracking-[0.16em] uppercase text-ink-3">
          Event stream
        </span>
        <span className="font-mono text-[10px] text-ink-3">
          {events.length} event{events.length === 1 ? '' : 's'}
        </span>
      </div>

      {events.length === 0 && <p className="text-[13px] text-ink-3">No events yet.</p>}

      <div className="grid gap-2 md:grid-cols-2">
        {[...events].reverse().map((event, i) => {
          const tone = TONE[event.eventType] || TONE.run_created
          const open = expandedId === event.eventId
          return (
            <div
              key={event.eventId}
              onClick={() => setExpandedId((id) => (id === event.eventId ? null : event.eventId))}
              style={{ animationDelay: `${Math.min(i, 8) * 40}ms` }}
              className={`animate-fade-up cursor-pointer rounded-xl border bg-panel px-3.5 py-2.5 transition-colors ${
                open ? 'border-acc md:col-span-2' : 'border-line hover:border-acc'
              }`}
            >
              <div className="flex items-center gap-3">
                <span className={`size-1.25 shrink-0 rounded-full ${tone.dot}`} />
                <span className={`shrink-0 font-mono text-[11px] ${tone.type}`}>
                  {event.eventType}
                </span>
                <span className="flex-1 truncate text-xs text-ink-2">{summarize(event)}</span>
                <span className="shrink-0 font-mono text-[10px] text-ink-3">
                  {new Date(event.timestamp).toLocaleTimeString()}
                </span>
              </div>

              {open && (
                <pre className="mt-2.5 max-h-60 overflow-y-auto rounded-lg border border-line bg-bg p-2.5 font-mono text-[10.5px] break-words whitespace-pre-wrap text-ink-2">
                  {JSON.stringify(event.payload, null, 2)}
                </pre>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}
