import { useState } from 'react'
import ReactMarkdown from 'react-markdown'

// The one thing a user actually came here for: what the run produced. Shown
// as properly rendered markdown (the Writer/Synthesis agents write real
// markdown -- headings, bold, lists) rather than a monospace text dump.
export default function FinalResult({ run }) {
  const [copied, setCopied] = useState(false)
  const output = run.finalOutput

  if (!output || !output.text) {
    if (run.status === 'failed' || run.status === 'partial') {
      return (
        <div className="final-result final-result-empty">
          <p className="empty-hint">
            No final result{run.error ? ` — ${run.error}` : ' — the run did not reach a terminal task.'}
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
    <div className="final-result">
      <div className="final-result-header">
        <h3>Final result</h3>
        <button className="copy-button" onClick={handleCopy} type="button">
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <div className="markdown-body">
        <ReactMarkdown>{output.text}</ReactMarkdown>
      </div>
      {output.sources?.length > 0 && (
        <div className="sources">
          <h4>Sources</h4>
          <ul>
            {output.sources.map((s, i) => (
              <li key={i}>
                {s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.title || s.url}</a> : s.title}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
