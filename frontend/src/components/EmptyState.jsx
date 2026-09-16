const SAMPLES = [
  'Compare the AI strategies of Google, Microsoft, and Amazon',
  'Summarize the 2026 EU AI Act timeline',
  'Draft a go-to-market brief for a dev tool',
]

export default function EmptyState({ onPick }) {
  return (
    <div className="flex flex-col items-center gap-4 px-7 py-14 text-center">
      <div className="relative grid size-16 place-items-center">
        <span
          aria-hidden="true"
          className="animate-drift absolute inset-0 rounded-full bg-[radial-gradient(closest-side,var(--halo),transparent)]"
        />
        <img
          src="/logo.png"
          alt=""
          className="animate-dot-pulse relative size-9 object-contain"
        />
      </div>

      <h3 className="m-0 font-serif text-3xl font-normal text-ink">
        Give it a goal. It builds the plan.
      </h3>
      <p className="m-0 max-w-[430px] text-[13.5px] leading-relaxed text-ink-3">
        A supervisor agent breaks your goal into a task graph, then research,
        synthesis and writer agents run it — in parallel wherever the graph allows.
      </p>

      <div className="flex flex-wrap justify-center gap-2 pt-1">
        {SAMPLES.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onPick?.(s)}
            className="rounded-full border border-line px-3.5 py-2 text-xs text-ink-2 transition-colors hover:border-acc hover:text-ink"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  )
}
