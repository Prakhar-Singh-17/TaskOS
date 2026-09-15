import { useState } from 'react'

export default function GoalForm({ onSubmit, disabled }) {
  const [goal, setGoal] = useState('')

  function handleSubmit(e) {
    e.preventDefault()
    const trimmed = goal.trim()
    if (!trimmed || disabled) return
    onSubmit(trimmed)
    setGoal('')
  }

  return (
    <form className="goal-form" onSubmit={handleSubmit}>
      <input
        type="text"
        placeholder="e.g. Compare the AI strategies of Google, Microsoft, and Amazon"
        value={goal}
        onChange={(e) => setGoal(e.target.value)}
        disabled={disabled}
      />
      <button type="submit" disabled={disabled || !goal.trim()}>
        {disabled ? 'Running…' : 'Run'}
      </button>
    </form>
  )
}
