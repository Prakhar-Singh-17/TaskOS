import TaskNode from './TaskNode'

const COL_W = 320   // node width (240) + horizontal gutter
const ROW_H = 110   // node height (~92) + vertical gutter
const NODE_W = 240
const NODE_H = 92

// Left -> right node graph. Column = dependency layer (computed by the backend
// in core/graph.py, not re-derived here); row = position within that layer.
// Dependency edges are real SVG beziers between the parent's right edge and the
// child's left edge, so "3 boxes in a column" is a true statement about
// parallelism and every arrow is a real dependency.
export default function TaskGraph({ layers, tasks }) {
  if (!layers || layers.length === 0) {
    return (
      <p className="px-6 py-10 text-center text-[13px] text-ink-3">
        Waiting for the Supervisor to produce a plan…
      </p>
    )
  }

  const taskById = Object.fromEntries(tasks.map((t) => [t.taskId, t]))
  const tallest = Math.max(...layers.map((l) => l.length))
  const height = tallest * ROW_H - (ROW_H - NODE_H)
  const width = layers.length * COL_W - (COL_W - NODE_W)

  // Node centre positions, keyed by taskId, with each column vertically centred.
  const pos = {}
  layers.forEach((layer, col) => {
    const offset = ((tallest - layer.length) * ROW_H) / 2
    layer.forEach((taskId, row) => {
      pos[taskId] = { x: col * COL_W, y: offset + row * ROW_H }
    })
  })

  const edges = []
  layers.flat().forEach((taskId) => {
    const task = taskById[taskId]
    if (!task) return
    task.dependsOn.forEach((parentId) => {
      const from = pos[parentId]
      const to = pos[taskId]
      if (!from || !to) return
      const x1 = from.x + NODE_W
      const y1 = from.y + NODE_H / 2
      const x2 = to.x
      const y2 = to.y + NODE_H / 2
      const mid = x1 + (x2 - x1) / 2
      edges.push({
        key: `${parentId}->${taskId}`,
        d: `M${x1} ${y1} C${mid} ${y1} ${mid} ${y2} ${x2} ${y2}`,
        // An edge is "hot" once its source finished: that is when data is
        // actually flowing downstream.
        hot: taskById[parentId]?.status === 'done',
      })
    })
  })

  return (
    <div className="overflow-x-auto p-6 pt-2">
      <div className="relative" style={{ width, height }}>
        <svg
          viewBox={`0 0 ${width} ${height}`}
          width={width}
          height={height}
          className="pointer-events-none absolute inset-0 overflow-visible"
        >
          {edges.map((edge, i) => (
            <g key={edge.key}>
              {/* the edge itself: draws in when the plan arrives */}
              <path
                d={edge.d}
                fill="none"
                strokeLinecap="round"
                strokeWidth="1.6"
                strokeDasharray="420"
                className={`animate-draw-in ${edge.hot ? 'stroke-acc opacity-55' : 'stroke-edge'}`}
                style={{ animationDelay: `${100 + i * 90}ms` }}
              />
              {/* travelling dashes: only on edges carrying finished data */}
              {edge.hot && (
                <path
                  d={edge.d}
                  fill="none"
                  strokeLinecap="round"
                  strokeWidth="2.4"
                  strokeDasharray="5 43"
                  className="animate-dash stroke-acc"
                  style={{ animationDelay: `${i * 400}ms` }}
                />
              )}
            </g>
          ))}
        </svg>

        {layers.flat().map((taskId, i) => {
          const task = taskById[taskId]
          if (!task) return null
          return (
            <TaskNode
              key={taskId}
              task={task}
              taskById={taskById}
              x={pos[taskId].x}
              y={pos[taskId].y}
              delay={50 + i * 70}
            />
          )
        })}
      </div>
    </div>
  )
}
