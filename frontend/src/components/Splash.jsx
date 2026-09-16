// A branded boot screen shown once per fresh page load, while the initial
// run-history fetch is in flight. Purely cosmetic -- it masks real network
// latency instead of adding fake delay, and fades out the instant data is
// ready (see App.jsx's boot-phase logic). Never shown when the browser
// prefers reduced motion.
export default function Splash({ leaving }) {
  return (
    <div
      aria-hidden="true"
      className={`fixed inset-0 z-50 grid place-items-center bg-bg transition-all duration-500 ease-in ${
        leaving ? 'pointer-events-none opacity-0 blur-sm' : 'opacity-100'
      }`}
    >
      <div className="flex flex-col items-center gap-5">
        <div className="relative grid size-20 place-items-center">
          <span className="animate-drift absolute inset-0 rounded-full bg-[radial-gradient(closest-side,var(--halo),transparent)]" />
          <img
            src="/logo.png"
            alt="TaskOS"
            className="animate-splash-pop relative size-14 object-contain drop-shadow-[0_0_26px_-3px_var(--acc)]"
          />
        </div>

        <div className="animate-fade-up flex flex-col items-center gap-2.5" style={{ animationDelay: '220ms' }}>
          <span className="text-sm font-semibold tracking-[0.1em] uppercase text-ink">TaskOS</span>
          <span className="flex gap-1.5">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="animate-dot-pulse size-1 rounded-full bg-acc"
                style={{ animationDelay: `${i * 160}ms` }}
              />
            ))}
          </span>
        </div>
      </div>
    </div>
  )
}
