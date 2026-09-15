import { useEffect, useState } from 'react'
import { createRun, getRun, getRunEvents, listRuns } from './api'
import { socket } from './socket'
import GoalForm from './components/GoalForm'
import RunHistory from './components/RunHistory'
import TaskGraph from './components/TaskGraph'
import EventLog from './components/EventLog'
import FinalResult from './components/FinalResult'

const TERMINAL_STATUSES = new Set(['completed', 'partial', 'failed'])

export default function App() {
  const [runs, setRuns] = useState([])
  const [selectedRunId, setSelectedRunId] = useState(null)
  const [currentRun, setCurrentRun] = useState(null)
  const [events, setEvents] = useState([])
  const [submitting, setSubmitting] = useState(false)
  const [connected, setConnected] = useState(socket.connected)

  // Load run history once on mount.
  useEffect(() => {
    listRuns().then(setRuns).catch(console.error)
  }, [])

  // Backfill detail + event log whenever the selected run changes -- this is
  // what makes clicking an old run in history work, not just live ones.
  useEffect(() => {
    if (!selectedRunId) return
    getRun(selectedRunId).then(setCurrentRun).catch(console.error)
    getRunEvents(selectedRunId).then(setEvents).catch(console.error)
  }, [selectedRunId])

  // The live feed. Every event for the selected run gets appended, and
  // triggers a fresh GET of the run so task statuses stay in sync -- simpler
  // and far less error-prone than hand-patching nested task state field by
  // field from a generic event payload.
  useEffect(() => {
    function onConnect() { setConnected(true) }
    function onDisconnect() { setConnected(false) }
    function onEvent(event) {
      if (event.runId === selectedRunId) {
        setEvents((prev) => [...prev, event])
        getRun(selectedRunId).then(setCurrentRun).catch(console.error)
      }
      if (event.eventType === 'run_created' || event.eventType === 'run_completed') {
        listRuns().then(setRuns).catch(console.error)
      }
    }

    socket.on('connect', onConnect)
    socket.on('disconnect', onDisconnect)
    socket.on('task_event', onEvent)
    return () => {
      socket.off('connect', onConnect)
      socket.off('disconnect', onDisconnect)
      socket.off('task_event', onEvent)
    }
  }, [selectedRunId])

  async function handleSubmitGoal(goal) {
    setSubmitting(true)
    try {
      const { runId } = await createRun(goal)
      setSelectedRunId(runId)
      setCurrentRun(null)
      setEvents([])
    } catch (err) {
      alert(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const isTerminal = currentRun && TERMINAL_STATUSES.has(currentRun.status)

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark">T</span>
          <div>
            <h1>TaskOS</h1>
            <p className="brand-subtitle">Agentic task orchestration</p>
          </div>
        </div>
        <span className={`conn-indicator ${connected ? 'conn-up' : 'conn-down'}`}>
          <span className="conn-dot" />
          {connected ? 'Live' : 'Disconnected'}
        </span>
      </header>

      <GoalForm onSubmit={handleSubmitGoal} disabled={submitting} />

      <div className="app-body">
        <RunHistory runs={runs} selectedRunId={selectedRunId} onSelect={setSelectedRunId} />

        <main className="run-detail">
          {currentRun ? (
            <>
              <div className="run-summary">
                <div className="run-summary-title">
                  <h2>{currentRun.goal}</h2>
                  <span className={`status-badge status-${currentRun.status}`}>
                    {currentRun.status === 'running' && <span className="badge-pulse" />}
                    {currentRun.status}
                  </span>
                </div>
                {currentRun.error && <p className="task-error">{currentRun.error}</p>}
              </div>

              {isTerminal && <FinalResult run={currentRun} />}

              <section className="pipeline-section">
                <h3 className="section-label">Pipeline</h3>
                <TaskGraph layers={currentRun.layers} tasks={currentRun.tasks} />
              </section>
            </>
          ) : (
            <div className="empty-state">
              <p className="empty-hint">Select a run, or start a new one above.</p>
            </div>
          )}
        </main>

        <EventLog events={events} />
      </div>
    </div>
  )
}
