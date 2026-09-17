// Thin wrapper around the TaskOS REST API. One function per endpoint, no
// client-side state -- App.jsx owns state, this file just talks to the
// network. Keeping it this small makes it obvious there's no hidden layer
// of client-side business logic duplicating what the backend already does.

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function request(path, options) {
  const response = await fetch(`${API_URL}${path}`, options)
  if (!response.ok) {
    const body = await response.text()
    throw new Error(`${options?.method || 'GET'} ${path} failed (${response.status}): ${body}`)
  }
  return response.status === 204 ? null : response.json()
}

export function createRun(goal) {
  return request('/api/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ goal }),
  })
}

export function listRuns() {
  return request('/api/runs')
}

export function getRun(runId) {
  return request(`/api/runs/${runId}`)
}

export function getRunEvents(runId) {
  return request(`/api/runs/${runId}/events`)
}

export function listTools() {
  return request('/api/tools')
}

export function runDraftedCode(runId, taskId) {
  return request(`/api/runs/${runId}/tasks/${taskId}/run-code`, { method: 'POST' })
}

export { API_URL }
