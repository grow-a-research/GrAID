import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { useWorkflow } from '../context/WorkflowContext'
import { timeAgo } from '../lib/dates'

const KIND_ICON = {
  submitted: '📥',
  autograde_started: '⏱',
  autograde_finished: '✅',
}

// Teacher notifications: a bell with an unread count and a dropdown list.
// Clicking one opens the relevant exam on the relevant tab.
export default function NotificationBell() {
  const { setActiveTab, selectExam } = useWorkflow()
  const [open, setOpen] = useState(false)
  const [data, setData] = useState({ unread: 0, items: [] })
  const box = useRef(null)

  async function load() {
    try { setData(await api.notifications.list()) } catch { /* keep what we have */ }
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 30000)
    window.addEventListener('focus', load)
    return () => { clearInterval(t); window.removeEventListener('focus', load) }
  }, [])

  useEffect(() => {
    if (!open) return
    const onDown = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  async function openItem(n) {
    setOpen(false)
    if (!n.read) {
      api.notifications.read(n.id).catch(() => {})
      setData(prev => ({
        unread: Math.max(0, prev.unread - 1),
        items: prev.items.map(i => (i.id === n.id ? { ...i, read: true } : i)),
      }))
    }
    if (n.exam_id) {
      try { selectExam(await api.exams.get(n.exam_id)) } catch { /* exam may be gone */ }
    }
    if (n.link_tab) setActiveTab(n.link_tab)
  }

  async function readAll() {
    try { await api.notifications.readAll() } catch { return }
    setData(prev => ({ unread: 0, items: prev.items.map(i => ({ ...i, read: true })) }))
  }

  return (
    <div className="relative" ref={box}>
      <button type="button" onClick={() => { setOpen(o => !o); if (!open) load() }}
        className="relative rounded-md border border-zinc-800 px-2.5 py-1.5 text-zinc-400 transition hover:border-zinc-700 hover:text-zinc-100"
        title="Notifications" aria-label={`Notifications${data.unread ? `, ${data.unread} unread` : ''}`}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.7 21a2 2 0 0 1-3.4 0" />
        </svg>
        {data.unread > 0 && (
          <span className="absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-amber-500 px-1 text-[10px] font-bold text-amber-950">
            {data.unread > 99 ? '99+' : data.unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-30 mt-2 w-[22rem] max-w-[92vw] rounded-xl border border-zinc-700 bg-zinc-900 shadow-xl">
          <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-2.5">
            <span className="text-sm font-semibold text-zinc-100">Notifications</span>
            <button type="button" onClick={readAll} disabled={data.unread === 0}
              className="text-xs text-zinc-400 underline underline-offset-2 hover:text-zinc-200 disabled:opacity-40 disabled:no-underline">
              Mark all read
            </button>
          </div>
          {data.items.length === 0
            ? <div className="px-4 py-8 text-center text-sm text-zinc-500">Nothing yet. Submissions and grading updates will appear here.</div>
            : (
              <div className="max-h-96 overflow-y-auto">
                {data.items.map(n => (
                  <button key={n.id} type="button" onClick={() => openItem(n)}
                    className={[
                      'flex w-full items-start gap-3 border-b border-zinc-800/60 px-4 py-3 text-left transition last:border-0 hover:bg-zinc-800/60',
                      n.read ? 'opacity-70' : '',
                    ].join(' ')}>
                    <span className="mt-0.5 text-base">{KIND_ICON[n.kind] ?? '🔔'}</span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className={`truncate text-sm ${n.read ? 'text-zinc-300' : 'font-medium text-zinc-50'}`}>{n.title}</span>
                        {!n.read && <span className="h-2 w-2 shrink-0 rounded-full bg-amber-400" />}
                      </span>
                      {n.body && <span className="mt-0.5 block text-xs text-zinc-400">{n.body}</span>}
                      <span className="mt-1 block text-[11px] text-zinc-500">{timeAgo(n.created_at)}</span>
                    </span>
                  </button>
                ))}
              </div>
            )}
        </div>
      )}
    </div>
  )
}
