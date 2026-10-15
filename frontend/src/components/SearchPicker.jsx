import { useRef, useState } from 'react'
import { tw } from '../ui'

// Generic searchable single-select. Type to filter, click a result to choose it.
// A chosen item shows as a chip; ✕ clears it back to the search box.
//   items:     list of objects with a stable `id`
//   primary:   item → main line (e.g. name / title)
//   secondary: item → small second line (e.g. code)
export default function SearchPicker({
  items, value, onChange, label, placeholder, primary, secondary, emptyText = 'No matches.',
}) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const inputRef = useRef(null)

  const q = query.trim().toLowerCase()
  const matches = q
    ? items.filter(i => primary(i).toLowerCase().includes(q) || secondary(i).toLowerCase().includes(q))
    : items

  function pick(item) {
    onChange(item)
    setQuery('')
    setOpen(false)
  }

  if (value) {
    return (
      <div className="flex flex-col gap-1">
        <div className={tw.label}>{label}</div>
        <div className="flex items-center justify-between rounded-lg border border-emerald-500/50 bg-emerald-500/10 px-3 py-2">
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-zinc-100">{primary(value)}</div>
            <div className={tw.muted}>{secondary(value)}</div>
          </div>
          <button type="button" onClick={() => onChange(null)} title={`Clear ${label.toLowerCase()}`}
            className="shrink-0 px-1 text-xs text-zinc-400 hover:text-zinc-100 transition">
            ✕
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="relative flex flex-col gap-1">
      <div className={tw.label}>{label}</div>
      <div className="flex gap-2">
        <input ref={inputRef} className={tw.input} placeholder={placeholder}
          value={query}
          onChange={e => { setQuery(e.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)} />
        <button type="button" className={tw.btnSm} title={`Search ${label.toLowerCase()}`}
          onMouseDown={e => e.preventDefault()}
          onClick={() => { inputRef.current?.focus(); setOpen(true) }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.5" y2="16.5" />
          </svg>
        </button>
      </div>
      {open && (
        <div className="absolute left-0 right-0 top-full z-20 mt-1 max-h-60 overflow-y-auto rounded-lg border border-zinc-700 bg-zinc-900 py-1 shadow-lg">
          {matches.length === 0
            ? <div className="px-3 py-2 text-xs text-zinc-500">{emptyText}</div>
            : matches.map(i => (
              <button key={i.id} type="button"
                // mousedown fires before the input's blur, so the pick isn't lost.
                onMouseDown={e => { e.preventDefault(); pick(i) }}
                className="block w-full px-3 py-2 text-left hover:bg-zinc-800 transition">
                <div className="text-sm text-zinc-100">{primary(i)}</div>
                <div className="text-xs text-zinc-500">{secondary(i)}</div>
              </button>
            ))}
        </div>
      )}
    </div>
  )
}
