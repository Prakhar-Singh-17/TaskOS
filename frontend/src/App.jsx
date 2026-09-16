import { useEffect, useState } from 'react'
import { createRun, getRun, getRunEvents, listRuns } from './api'
import { socket } from './socket'
import GoalForm from './components/GoalForm'
import RunHistory from './components/RunHistory'
import RunSummary from './components/RunSummary'
import TaskGraph from './components/TaskGraph'
import EventLog from './components/EventLog'
import FinalResult from './components/FinalResult'
import EmptyState from './components/EmptyState'
import ThemeToggle from './components/ThemeToggle'

const TERMINAL_STATUSES = new Set(['completed', 'partial', 'failed'])

export default function App() {
  const [runs, setRuns] = useState([])
  const [selectedRunId, setSelectedRunId] = useState(null)
  const [currentRun, setCurrentRun] = useState(null)
  const [events, setEvents] = useState([])
  const [submitting, setSubmitting] = useState(false)
  const [connected, setConnected] = useState(socket.connected)

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

  // The live feed. Every event for the selected run gets appended and triggers
  // a fresh GET of the run so task statuses stay in sync -- simpler and far
  // less error-prone than hand-patching nested task state field by field.
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
    <div className="min-h-screen bg-bg">
      <div className="mx-auto max-w-[1440px] p-5 lg:p-10">
        <div className="overflow-hidden rounded-[18px] border border-line bg-bg shadow-[0_24px_70px_-30px_rgb(0_0_0/0.35)]">

          {/* ---------- header ---------- */}
          <header className="relative flex items-center justify-between gap-3 overflow-hidden border-b border-line px-6 py-4.5">
            <div
              aria-hidden="true"
              className="animate-drift pointer-events-none absolute -top-[60%] right-[-20%] left-[30%] h-56 bg-[radial-gradient(closest-side,var(--halo),transparent)] blur-lg"
            />
            <div className="relative flex items-center gap-3.5">
              <span className="grid size-7.5 place-items-center rounded-[9px] bg-acc shadow-[0_0_22px_-4px_var(--acc)]">
                <span className="block size-2.25 rotate-45 rounded-[2px] bg-bg" />
              </span>
              <div className="flex flex-col gap-0.5">
                <span className="text-sm font-semibold tracking-[0.08em] uppercase text-ink">TaskOS</span>
                <span className="text-[11px] text-ink-3">Agentic task orchestration</span>
              </div>
            </div>

            <div className="relative flex items-center gap-2.5">
              <span className="inline-flex items-center gap-2 rounded-full border border-line bg-panel py-1.5 pr-3 pl-2.5 text-[11px] font-medium text-ink-2">
                <span
                  className={`size-1.5 rounded-full ${
                    connected
                      ? 'animate-dot-pulse bg-green-500 shadow-[0_0_9px_1px_rgb(34_197_94/0.7)]'
                      : 'bg-red-500'
                  }`}
                />
                {connected ? 'Live' : 'Disconnected'}
              </span>
              <ThemeToggle />
            </div>
          </header>

          {/* ---------- goal form ---------- */}
          <div className="border-b border-line px-6 py-5">
            <GoalForm onSubmit={handleSubmitGoal} disabled={submitting} />
          </div>

          {/* ---------- rail + main ---------- */}
          <div className="grid lg:grid-cols-[236px_minmax(0,1fr)]">
            <RunHistory runs={runs} selectedRunId={selectedRunId} onSelect={setSelectedRunId} />

            <main className="flex min-w-0 flex-col gap-5.5 p-6">
              {currentRun ? (
                <>
                  <RunSummary run={currentRun} />

                  {isTerminal && <FinalResult run={currentRun} />}

                  <section className="relative overflow-hidden rounded-2xl border border-line bg-canvas">
                    <div
                      aria-hidden="true"
                      className="pointer-events-none absolute inset-0 bg-[radial-gradient(var(--dot)_1px,transparent_1px)] bg-[length:22px_22px]"
                    />
                    <div className="relative flex items-center justify-between px-4 py-3.5">
                      <span className="font-mono text-[10px] tracking-[0.16em] uppercase text-ink-3">
                        Pipeline · {currentRun.layers?.length || 0} layer
                        {currentRun.layers?.length === 1 ? '' : 's'}
                      </span>
                    </div>
                    <div className="relative">
                      <TaskGraph layers={currentRun.layers || []} tasks={currentRun.tasks || []} />
                    </div>
                  </section>

                  <EventLog events={events} />
                </>
              ) : (
                <EmptyState onPick={handleSubmitGoal} />
              )}
            </main>
          </div>
        </div>
      </div>
    </div>
  )
}
