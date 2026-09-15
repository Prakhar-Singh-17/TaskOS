import { useState } from 'react'

const EVENT_COLOR = {
  run_created: 'evt-neutral',
  plan_created: 'evt-neutral',
  task_started: 'evt-info',
  tool_call: 'evt-tool',
  task_completed: 'evt-ok',
  task_retrying: 'evt-warn',
  task_failed: 'evt-error',
  task_blocked: 'evt-error',
  run_completed: 'evt-neutral',
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

// This entire component is generic over event shape -- it never special-cases
// an agent or tool name, only the eventType label and a one-line summary. A
// brand-new tool or agent needs zero changes here: its events just show up.
export default function EventLog({ events }) {
  const [expandedId, setExpandedId] = useState(null)

  return (
    <div className="event-log">
      <h2>Event log</h2>
      {events.length === 0 && <p className="empty-hint">No events yet.</p>}
      <ul>
        {[...events].reverse().map((event) => (
          <li
            key={event.eventId}
            className={EVENT_COLOR[event.eventType] || 'evt-neutral'}
            onClick={() => setExpandedId((id) => (id === event.eventId ? null : event.eventId))}
          >
            <div className="event-row">
              <span className="event-time">{new Date(event.timestamp).toLocaleTimeString()}</span>
              <span className="event-type">{event.eventType}</span>
              <span className="event-summary">{summarize(event)}</span>
            </div>
            {expandedId === event.eventId && (
              <pre className="event-payload">{JSON.stringify(event.payload, null, 2)}</pre>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
