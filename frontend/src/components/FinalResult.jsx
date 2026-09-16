import { useState } from 'react'
import ReactMarkdown from 'react-markdown'

// The thing a user actually came here for, sitting inline above the pipeline.
// Rendered as real markdown -- the Writer/Synthesis agents emit headings, bold
// and lists -- with sources as chips rather than a bare link list.
export default function FinalResult({ run }) {
  const [copied, setCopied] = useState(false)
  const output = run.finalOutput

  if (!output || !output.text) {
    if (run.status === 'failed' || run.status === 'partial') {
      return (
        <div className="animate-fade-up rounded-2xl border border-red-500/30 bg-panel px-6 py-5">
          <p className="m-0 text-[13px] text-ink-2">
            No final result
            {run.error ? ` — ${run.error}` : ' — the run did not reach a terminal task.'}
          </p>
        </div>
      )
    }
    return null
  }

  function handleCopy() {
    navigator.clipboard?.writeText(output.text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <div className="animate-fade-up relative overflow-hidden rounded-2xl border border-line bg-panel px-7 py-6">
      <div
        aria-hidden="true"
        className="absolute inset-x-0 top-0 h-px bg-linear-to-r from-transparent via-acc to-transparent"
      />

      <div className="mb-3.5 flex items-center justify-between">
        <span className="font-mono text-[10px] tracking-[0.16em] uppercase text-acc">
          Final result
        </span>
        <button
          type="button"
          onClick={handleCopy}
          className="rounded-lg border border-line px-3 py-1.5 font-mono text-[10.5px] tracking-[0.08em] uppercase text-ink-2 transition-colors hover:border-acc hover:text-ink"
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>

      {output.image?.base64 && (
        <img
          src={`data:${output.image.mimeType};base64,${output.image.base64}`}
          alt=""
          className="mb-4 max-w-full rounded-xl border border-line"
        />
      )}

      <div
        className="max-w-[72ch] text-[14.5px] leading-[1.7] text-ink-2
          [&_code]:rounded [&_code]:bg-bg [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[0.88em]
          [&_h1]:mt-0 [&_h1]:mb-3 [&_h1]:font-serif [&_h1]:text-[27px] [&_h1]:leading-tight [&_h1]:font-normal [&_h1]:text-ink
          [&_h2]:mt-6 [&_h2]:mb-2.5 [&_h2]:font-serif [&_h2]:text-[22px] [&_h2]:font-normal [&_h2]:text-ink
          [&_h3]:mt-5 [&_h3]:mb-2 [&_h3]:text-[15px] [&_h3]:font-semibold [&_h3]:text-ink
          [&_li]:my-1 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5
          [&_p]:my-3 [&_strong]:font-semibold [&_strong]:text-ink
          [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5"
      >
        <ReactMarkdown>{output.text}</ReactMarkdown>
      </div>

      {output.sources?.length > 0 && (
        <div className="mt-4 flex flex-col gap-2 border-t border-line pt-3.5">
          <span className="font-mono text-[10px] tracking-[0.14em] uppercase text-ink-3">
            Sources · {output.sources.length}
          </span>
          <div className="flex flex-wrap gap-2">
            {output.sources.map((s, i) => (
              <a
                key={i}
                href={s.url || undefined}
                target="_blank"
                rel="noreferrer"
                className="rounded-full border border-line px-3 py-1.5 text-[11.5px] text-ink-2 no-underline transition-colors hover:border-acc hover:text-ink hover:no-underline"
              >
                {s.title || s.url}
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
