const STATUS_LABEL = {
  planning: 'Planning',
  running: 'Running',
  completed: 'Completed',
  partial: 'Partial',
  failed: 'Failed',
}

export default function RunHistory({ runs, selectedRunId, onSelect }) {
  return (
    <div className="run-history">
      <h2>Runs</h2>
      {runs.length === 0 && <p className="empty-hint">No runs yet.</p>}
      <ul>
        {runs.map((run) => (
          <li
            key={run.runId}
            className={run.runId === selectedRunId ? 'selected' : ''}
            onClick={() => onSelect(run.runId)}
          >
            <span className={`status-dot status-${run.status}`} />
            <span className="run-goal" title={run.goal}>{run.goal}</span>
            <span className="run-status-label">{STATUS_LABEL[run.status] || run.status}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
