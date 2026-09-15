import { useState } from 'react'

const AGENT_ICON = {
  research: '🔎',
  writer: '✍️',
  synthesis: '🧩',
  supervisor: '🧭',
}

const STATUS_LABEL = {
  pending: 'Pending',
  running: 'Running',
  done: 'Done',
  failed: 'Failed',
  blocked: 'Blocked',
  cancelled: 'Cancelled',
}

function ResultPreview({ result }) {
  const text = typeof result === 'string' ? result : JSON.stringify(result, null, 2)
  return <pre className="result-preview">{text}</pre>
}

export default function TaskNode({ task, taskById }) {
  const [expanded, setExpanded] = useState(false)
  const retried = task.attempts.length > 1

  return (
    <div
      className={`task-node status-${task.status}`}
      onClick={() => setExpanded((v) => !v)}
    >
      <div className="task-node-header">
        <span className="agent-icon" title={task.assignedAgent}>{AGENT_ICON[task.assignedAgent] || '🤖'}</span>
        <span className={`status-badge status-${task.status}`}>{STATUS_LABEL[task.status] || task.status}</span>
        {retried && (
          <span className="retry-badge" title={`${task.attempts.length} attempts`}>
            ↻ {task.attempts.length}
          </span>
        )}
        {task.durationMs != null && <span className="duration">{task.durationMs}ms</span>}
      </div>

      <p className="task-description">{task.description}</p>

      {task.dependsOn.length > 0 && (
        <p className="depends-on">
          depends on: {task.dependsOn.map((id) => taskById[id]?.assignedAgent || id).join(', ')}
        </p>
      )}

      {expanded && (
        <div className="task-node-details" onClick={(e) => e.stopPropagation()}>
          {task.attempts.length > 0 && (
            <div className="attempts">
              <h4>Attempts</h4>
              {task.attempts.map((a) => (
                <div key={a.number} className={`attempt ${a.ok ? 'attempt-ok' : 'attempt-failed'}`}>
                  <span>#{a.number}</span>
                  <span>{a.ok ? 'ok' : a.failureKind}</span>
                  {a.note && <span className="attempt-note">{a.note}</span>}
                </div>
              ))}
            </div>
          )}
          {task.error && <p className="task-error">{task.error}</p>}
          {task.result != null && <ResultPreview result={task.result} />}
        </div>
      )}
    </div>
  )
}
