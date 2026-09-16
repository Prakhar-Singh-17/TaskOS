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
    <form onSubmit={handleSubmit} className="flex items-stretch gap-2.5">
      <div className="group relative flex flex-1 items-center gap-3 overflow-hidden rounded-2xl border border-line bg-panel px-4 transition-colors focus-within:border-acc">
        <span className="font-mono text-xs text-acc">&gt;</span>
        <input
          type="text"
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          disabled={disabled}
          placeholder="Compare the AI strategies of Google, Microsoft, and Amazon"
          className="min-w-0 flex-1 bg-transparent py-4 text-[14.5px] text-ink outline-none placeholder:text-ink-3"
        />
        {!goal && (
          <span className="h-[17px] w-[1.5px] bg-acc animate-caret" aria-hidden="true" />
        )}
      </div>
      <button
        type="submit"
        disabled={disabled || !goal.trim()}
        className="relative flex shrink-0 items-center gap-2 overflow-hidden rounded-2xl bg-acc px-6 text-sm font-semibold text-white shadow-[0_10px_30px_-12px_var(--acc)] transition-transform hover:-translate-y-px active:scale-[0.98] disabled:cursor-default disabled:opacity-45 disabled:hover:translate-y-0"
      >
        {!disabled && (
          <span
            aria-hidden="true"
            className="absolute inset-y-0 left-0 w-1/3 bg-linear-to-r from-transparent via-white/45 to-transparent animate-sweep"
          />
        )}
        <span className="relative">{disabled ? 'Running…' : 'Run'}</span>
        <span className="relative font-mono text-[11px] opacity-60">⏎</span>
      </button>
    </form>
  )
}
