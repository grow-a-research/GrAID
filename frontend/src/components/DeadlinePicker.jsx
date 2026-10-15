import { useEffect, useState } from 'react'
import { tw } from '../ui'
import { fmtDue, fromInputValue, toInputValue } from '../lib/dates'

// End of a day, in the teacher's own timezone (the server stores the UTC instant).
function endOfDay(offsetDays) {
  const d = new Date()
  d.setDate(d.getDate() + offsetDays)
  d.setHours(23, 59, 0, 0)
  return d
}

const PRESETS = [
  { key: 'none',     label: 'No deadline' },
  { key: 'today',    label: 'Today, 11:59 PM',       at: () => endOfDay(0) },
  { key: 'tomorrow', label: 'Tomorrow, 11:59 PM',    at: () => endOfDay(1) },
  { key: '3days',    label: 'In 3 days, 11:59 PM',   at: () => endOfDay(3) },
  { key: 'week',     label: 'In 1 week, 11:59 PM',   at: () => endOfDay(7) },
  { key: 'custom',   label: 'Custom date & time…' },
]

const asInput = (d) => toInputValue(d.toISOString())

// Which dropdown option a stored datetime-local value corresponds to.
function detect(value) {
  if (!value) return 'none'
  const hit = PRESETS.find(p => p.at && asInput(p.at()) === value)
  return hit ? hit.key : 'custom'
}

// Deadline chooser: a dropdown of common choices, with a date-time picker for
// "Custom". `value` and `onChange` use the <input type="datetime-local"> format
// ('' = no deadline).
export default function DeadlinePicker({ value, onChange, disabled = false }) {
  const [mode, setMode] = useState(detect(value))

  // Follow the value when it changes from outside (a different exam, a save…),
  // but never snap a freshly chosen "Custom" back while its value is still empty.
  useEffect(() => {
    setMode(prev => (prev === 'custom' && !value ? 'custom' : detect(value)))
  }, [value])

  function choose(key) {
    setMode(key)
    if (key === 'none') return onChange('')
    if (key === 'custom') {
      // Start from the current deadline, or tomorrow at 5 PM.
      if (!value) {
        const d = endOfDay(1); d.setHours(17, 0, 0, 0)
        onChange(asInput(d))
      }
      return
    }
    onChange(asInput(PRESETS.find(p => p.key === key).at()))
  }

  const iso = fromInputValue(value)

  return (
    <div className="flex flex-col gap-2">
      <select className={tw.select} value={mode} disabled={disabled} onChange={e => choose(e.target.value)}>
        {PRESETS.map(p => <option key={p.key} value={p.key}>{p.label}</option>)}
      </select>
      {mode === 'custom' && (
        <input type="datetime-local" className={tw.input} value={value} disabled={disabled}
          onChange={e => onChange(e.target.value)} />
      )}
      {iso && (
        <div className="text-xs text-zinc-500">
          Students will see: <span className="text-zinc-300">{fmtDue(iso)}</span>
        </div>
      )}
    </div>
  )
}
