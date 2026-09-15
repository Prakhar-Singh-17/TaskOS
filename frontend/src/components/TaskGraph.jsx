import TaskNode from './TaskNode'

// Renders the DAG as rows, one row per dependency layer -- exactly what
// TaskGraph.layers() computes on the backend (see core/graph.py). Tasks in
// the same row have no dependency relationship to each other, which is what
// makes "3 boxes side by side" a true, not just visual, statement about
// parallelism: the backend computed that grouping, this component doesn't
// re-derive the DAG itself.
export default function TaskGraph({ layers, tasks }) {
  const taskById = Object.fromEntries(tasks.map((t) => [t.taskId, t]))

  if (layers.length === 0) {
    return <p className="empty-hint">Waiting for the Supervisor to produce a plan…</p>
  }

  return (
    <div className="task-graph">
      {layers.map((layer, i) => (
        <div className="task-layer" key={i}>
          {layer.map((taskId) => (
            <TaskNode key={taskId} task={taskById[taskId]} taskById={taskById} />
          ))}
        </div>
      ))}
    </div>
  )
}
