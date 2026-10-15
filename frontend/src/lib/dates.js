// Deadline helpers. The server stores and sends UTC instants (ISO with "Z");
// everything shown to a person is converted to their own timezone here.

const pad = (n) => String(n).padStart(2, '0')

// ISO instant → value for <input type="datetime-local"> in the viewer's timezone.
export function toInputValue(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// <input type="datetime-local"> value (viewer's local time) → ISO instant, or null.
export function fromInputValue(v) {
  if (!v) return null
  const d = new Date(v)
  return Number.isNaN(d.getTime()) ? null : d.toISOString()
}

export function fmtDue(iso) {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString(undefined, {
      weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    })
  } catch { return '' }
}

function span(ms) {
  const m = Math.round(Math.abs(ms) / 60000)
  if (m < 60) return `${Math.max(m, 1)} min`
  const h = Math.round(m / 60)
  if (h < 48) return `${h} h`
  return `${Math.round(h / 24)} days`
}

// How the deadline stands right now, for display only (the server decides lateness).
export function dueStanding(iso, now = Date.now()) {
  if (!iso) return null
  const due = new Date(iso)
  if (Number.isNaN(due.getTime())) return null
  const diff = due.getTime() - now
  if (diff < 0) return { overdue: true, text: `Overdue by ${span(diff)}` }
  const today = new Date(now)
  const sameDay = due.toDateString() === today.toDateString()
  return { overdue: false, text: sameDay ? `Due today (in ${span(diff)})` : `Due in ${span(diff)}` }
}

// "5 min ago", "2 h ago", "3 days ago" — for notifications.
export function timeAgo(iso, now = Date.now()) {
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  const sec = Math.max(0, Math.round((now - t) / 1000))
  if (sec < 45) return 'just now'
  const min = Math.round(sec / 60)
  if (min < 60) return `${min} min ago`
  const h = Math.round(min / 60)
  if (h < 24) return `${h} h ago`
  const d = Math.round(h / 24)
  return d === 1 ? 'yesterday' : `${d} days ago`
}
