import { useState } from 'react'

const TONE = {
  done: {
    border: 'border-green-500/30',
    label: 'text-green-500 dark:text-green-400',
    dot: 'bg-green-500',
  },
  running: {
    border: 'border-blue-500',
    label: 'text-blue-600 dark:text-blue-300',
    dot: 'bg-blue-500',
  },
  failed: {
    border: 'border-red-500/40',
    label: 'text-red-600 dark:text-red-400',
    dot: 'bg-red-500',
  },
  blocked: {
    border: 'border-amber-500/40',
    label: 'text-amber-600 dark:text-amber-400',
    dot: 'bg-amber-500',
  },
  cancelled: { border: 'border-edge', label: 'text-ink-3', dot: 'bg-ink-3' },
  pending: { border: 'border-edge border-dashed', label: 'text-ink-3', dot: 'bg-ink-3' },
}

function fmtDuration(ms) {
  if (ms == null) return null
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`
}

// A single DAG node. Absolutely positioned by TaskGraph; springs in on mount,
// breathes while running, expands in place to show attempts and raw result.
export default function TaskNode({ task, taskById, x, y, delay = 0 }) {
  const [expanded, setExpanded] = useState(false)
  const tone = TONE[task.status] || TONE.pending
  const running = task.status === 'running'
  const idle = task.status === 'pending' || task.status === 'cancelled'
  const retried = task.attempts.length > 1

  return (
    <div
      onClick={() => setExpanded((v) => !v)}
      style={{ left: x, top: y, animationDelay: `${delay}ms` }}
      className={`animate-pop-in absolute w-60 cursor-pointer rounded-xl border px-3.5 py-3 backdrop-blur-sm transition-transform ${tone.border} ${
        idle ? 'bg-node-dim' : 'bg-node'
      } ${running ? 'animate-breathe z-10' : 'hover:-translate-y-0.5'} ${expanded ? 'z-20' : ''}`}
    >
      <div className="mb-2 flex items-center gap-2 font-mono text-[10px] tracking-[0.12em] uppercase">
        <span className={`size-1.5 shrink-0 rounded-full ${tone.dot} ${running ? 'animate-dot-pulse' : ''}`} />
        <span className={tone.label}>{task.assignedAgent}</span>
        {retried && (
          <span className="text-amber-600 dark:text-amber-400" title={`${task.attempts.length} attempts`}>
            ↻{task.attempts.length}
          </span>
        )}
        <span className="ml-auto text-ink-3">
          {fmtDuration(task.durationMs) || (running ? 'running' : 'queued')}
        </span>
      </div>

      <p className={`m-0 line-clamp-2 text-[12.5px] leading-[1.42] ${idle ? 'text-ink-3' : 'text-ink-2'}`}>
        {task.description}
      </p>

      {running && (
        <div className="mt-2 h-0.5 overflow-hidden rounded-sm bg-edge">
          <div className="h-full w-2/5 rounded-sm bg-linear-to-r from-transparent via-blue-500 to-transparent bg-[length:220%_100%] animate-shimmer" />
        </div>
      )}

      {task.dependsOn.length > 0 && !expanded && (
        <p className="mt-2 m-0 font-mono text-[10px] text-ink-3">
          {task.dependsOn.length} dep{task.dependsOn.length > 1 ? 's' : ''}
        </p>
      )}

      {expanded && (
        <div
          onClick={(e) => e.stopPropagation()}
          className="animate-fade-up mt-2.5 cursor-default border-t border-line pt-2.5"
        >
          {task.dependsOn.length > 0 && (
            <p className="m-0 mb-2 font-mono text-[10px] text-ink-3">
              depends on: {task.dependsOn.map((id) => taskById[id]?.assignedAgent || id).join(', ')}
            </p>
          )}

          {task.attempts.length > 0 && (
            <div className="mb-2">
              <h4 className="m-0 mb-1.5 font-mono text-[9.5px] tracking-[0.12em] uppercase text-ink-3">
                Attempts
              </h4>
              {task.attempts.map((a) => (
                <div key={a.number} className="flex gap-2 py-0.5 font-mono text-[11px]">
                  <span className="text-ink-3">#{a.number}</span>
                  <span className={a.ok ? 'text-green-500 dark:text-green-400' : 'text-red-600 dark:text-red-400'}>
                    {a.ok ? 'ok' : a.failureKind}
                  </span>
                  {a.note && <span className="truncate text-ink-3 italic">{a.note}</span>}
                </div>
              ))}
            </div>
          )}

          {task.error && (
            <p className="m-0 mb-2 text-[11.5px] text-red-600 dark:text-red-400">{task.error}</p>
          )}

          {task.result?.image?.base64 ? (
            // An image result (Illustrator) renders as a picture, not a
            // base64 wall of text -- the one place a new result *shape*
            // needs its own branch, same as FinalResult.jsx.
            <img
              src={`data:${task.result.image.mimeType};base64,${task.result.image.base64}`}
              alt=""
              className="max-h-40 w-full rounded-lg border border-line object-cover"
            />
          ) : task.result?.code ? (
            <pre className="m-0 max-h-40 overflow-y-auto rounded-lg border border-line bg-panel p-2.5 font-mono text-[10.5px] break-words whitespace-pre-wrap text-ink-2">
              {task.result.code.source}
            </pre>
          ) : (
            task.result != null && (
              <pre className="m-0 max-h-48 overflow-y-auto rounded-lg border border-line bg-panel p-2.5 font-mono text-[10.5px] break-words whitespace-pre-wrap text-ink-2">
                {typeof task.result === 'string' ? task.result : JSON.stringify(task.result, null, 2)}
              </pre>
            )
          )}
        </div>
      )}
    </div>
  )
}
