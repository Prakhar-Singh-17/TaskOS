import { useEffect, useState } from 'react'

// Theme lives on <html class="dark">, seeded by the inline script in index.html
// so there is no flash before React mounts.
export default function ThemeToggle() {
  const [theme, setTheme] = useState(() =>
    document.documentElement.classList.contains('dark') ? 'dark' : 'light',
  )

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    localStorage.setItem('taskos-theme', theme)
  }, [theme])

  return (
    <button
      type="button"
      onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
      className="rounded-full border border-line px-3 py-1.5 font-mono text-[10.5px] tracking-[0.08em] uppercase text-ink-2 transition-colors hover:border-acc hover:text-ink"
    >
      {theme === 'dark' ? 'Light' : 'Dark'}
    </button>
  )
}
