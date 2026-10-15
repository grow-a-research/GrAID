import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { tw, ErrorBox, Empty } from '../ui'
import { useWorkflow } from '../context/WorkflowContext'
import ClassPicker, { ExamPicker } from '../components/ClassPicker'
import { REASON_LABELS } from '../flagLabels'

const reasonLabel = (r) =>
  r === 'needs_review' ? 'Needs review (low confidence)' : (REASON_LABELS[r] ?? r)

const snippet = (s, n = 90) => (s && s.length > n ? `${s.slice(0, n).trimEnd()}…` : (s ?? ''))

// Everything in an exam that is waiting on the teacher, in one place: answers
// with status needs_review and/or an unreviewed flag. Items leave the queue
// when the teacher overrides the score, reviews the flag, or marks them reviewed.
export default function ReviewQueuePage() {
  const {
    selectedClass, selectClass,
    selectedExam, selectExam: pickExam,
    reviewQuestionId, setReviewQuestionId,
    selectSubmission, setActiveTab, setFocusAnswerId,
  } = useWorkflow()

  const [classes, setClasses] = useState([])
  const [exams, setExams] = useState([])
  const [queue, setQueue] = useState([])
  const [submissions, setSubmissions] = useState([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const [search, setSearch] = useState('')
  const [kind, setKind] = useState('all')        // all | flagged | status
  const [sort, setSort] = useState('student')    // student | question
  const [picked, setPicked] = useState(new Set())
  const [busyIds, setBusyIds] = useState(new Set())
  const [bulkBusy, setBulkBusy] = useState(false)

  useEffect(() => { api.classes.list().then(setClasses).catch(() => {}) }, [])

  useEffect(() => {
    if (!selectedClass) { setExams([]); return }
    api.exams.list(selectedClass.id).then(setExams).catch(() => setExams([]))
  }, [selectedClass?.id])

  // Arriving with an exam already picked elsewhere (e.g. from Item Analysis): show its class too.
  useEffect(() => {
    if (selectedExam && !selectedClass && classes.length > 0) {
      const cls = classes.find(c => c.id === selectedExam.class_id)
      if (cls) selectClass(cls)
    }
  }, [classes, selectedExam?.id])

  function changeClass(cls) {
    if (!cls) pickExam(null)
    selectClass(cls)
  }

  async function load() {
    if (!selectedExam) { setQueue([]); setSubmissions([]); return }
    setLoading(true); setErr('')
    try {
      const [q, subs] = await Promise.all([
        api.exams.reviewQueue(selectedExam.id),
        api.exams.submissions(selectedExam.id),
      ])
      setQueue(q); setSubmissions(subs)
    } catch (e) { setErr(e.message); setQueue([]); setSubmissions([]) }
    setLoading(false)
  }
  useEffect(() => {
    setSearch(''); setKind('all'); setPicked(new Set())
    load()
  }, [selectedExam?.id])

  // Per-question counts for the filter chips (always over the whole queue).
  const questionChips = useMemo(() => {
    const byQ = new Map()
    queue.forEach(i => {
      const k = i.question_id
      const cur = byQ.get(k) ?? { id: k, order: i.question_order_index ?? 0, n: 0 }
      cur.n += 1
      byQ.set(k, cur)
    })
    return [...byQ.values()].sort((a, b) => a.order - b.order)
  }, [queue])

  const items = useMemo(() => {
    const q = search.trim().toLowerCase()
    const list = queue.filter(i =>
      (reviewQuestionId == null || i.question_id === reviewQuestionId) &&
      (kind === 'all' || (kind === 'flagged' ? i.flagged : !i.flagged)) &&
      (!q || i.student_name.toLowerCase().includes(q) || i.student_id.toLowerCase().includes(q)))
    if (sort === 'question') {
      list.sort((a, b) => (a.question_order_index ?? 0) - (b.question_order_index ?? 0)
        || a.student_name.localeCompare(b.student_name))
    }
    return list   // already student-sorted by the server
  }, [queue, reviewQuestionId, kind, search, sort])

  const flaggedCount = queue.filter(i => i.flagged).length

  function open(item) {
    const sub = submissions.find(s => s.id === item.submission_id)
    if (!sub) return
    selectSubmission(sub)
    setFocusAnswerId(item.answer_id)
    setActiveTab('results')
  }

  async function markOne(item) {
    setBusyIds(prev => new Set(prev).add(item.answer_id))
    try {
      await api.submissions.markReviewed(item.submission_id, item.answer_id)
      setQueue(prev => prev.filter(i => i.answer_id !== item.answer_id))
      setPicked(prev => { const n = new Set(prev); n.delete(item.answer_id); return n })
    } catch (e) { setErr(`Could not mark reviewed: ${e.message}`) }
    setBusyIds(prev => { const n = new Set(prev); n.delete(item.answer_id); return n })
  }

  async function markPicked() {
    const targets = queue.filter(i => picked.has(i.answer_id))
    if (targets.length === 0) return
    if (!window.confirm(`Mark ${targets.length} answer${targets.length === 1 ? '' : 's'} as reviewed?\n\nThis only removes them from this list; scores and flags are not changed.`)) return
    setBulkBusy(true); setErr('')
    const done = new Set()
    for (const t of targets) {
      try {
        await api.submissions.markReviewed(t.submission_id, t.answer_id)
        done.add(t.answer_id)
      } catch (e) { setErr(`Stopped at ${t.student_name} Q${t.question_order_index}: ${e.message}`); break }
    }
    setQueue(prev => prev.filter(i => !done.has(i.answer_id)))
    setPicked(new Set())
    setBulkBusy(false)
  }

  function togglePick(id) {
    setPicked(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  }
  const allVisiblePicked = items.length > 0 && items.every(i => picked.has(i.answer_id))
  function togglePickAll() {
    setPicked(allVisiblePicked ? new Set() : new Set(items.map(i => i.answer_id)))
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Class → exam */}
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex min-w-[220px] flex-col gap-1">
          <ClassPicker classes={classes} value={selectedClass} onChange={changeClass} />
        </div>
        {selectedClass && (
          <div className="flex min-w-[260px] flex-1 flex-col gap-1">
            <ExamPicker exams={exams} value={selectedExam} onChange={pickExam} />
          </div>
        )}
        {selectedExam && <button className={tw.btnSm} onClick={load} disabled={loading}>Refresh</button>}
      </div>

      <ErrorBox msg={err} />

      {!selectedExam
        ? (
          <div className="flex h-40 items-center justify-center rounded-xl border border-dashed border-zinc-700 px-4 text-center">
            <span className={tw.muted}>
              {selectedClass ? 'Select an exam to see what needs your review' : 'Select a class, then an exam'}
            </span>
          </div>
        )
        : loading
          ? <div className={tw.muted}>Loading…</div>
          : queue.length === 0
            ? (
              <div className="rounded-xl border border-emerald-900/40 bg-emerald-950/20 px-4 py-6 text-center text-sm text-emerald-300">
                ✓ Nothing is waiting for review in {selectedExam.title}.
              </div>
            )
            : (
              <>
                {/* Summary + question chips */}
                <div className={`${tw.card} flex flex-col gap-3`}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-sm text-zinc-300">
                      <span className="text-lg font-semibold text-amber-300">{queue.length}</span>{' '}
                      answer{queue.length === 1 ? '' : 's'} waiting ·{' '}
                      <span className="text-amber-400">{flaggedCount} flagged</span> ·{' '}
                      <span className="text-sky-300">{queue.length - flaggedCount} low confidence</span>
                    </div>
                    <button type="button" className={tw.btnSmPrimary} disabled={items.length === 0}
                      onClick={() => open(items[0])}>
                      Review next →
                    </button>
                  </div>

                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="mr-1 text-xs text-zinc-500">Question:</span>
                    <button type="button" onClick={() => setReviewQuestionId(null)}
                      className={chipClass(reviewQuestionId == null)}>All ({queue.length})</button>
                    {questionChips.map(c => (
                      <button key={c.id} type="button"
                        onClick={() => setReviewQuestionId(reviewQuestionId === c.id ? null : c.id)}
                        className={chipClass(reviewQuestionId === c.id)}>
                        Q{c.order} ({c.n})
                      </button>
                    ))}
                  </div>
                </div>

                {/* Filters */}
                <div className="flex flex-wrap items-center gap-2">
                  <input className={`${tw.input} max-w-xs`} placeholder="Search student name or ID…"
                    value={search} onChange={e => setSearch(e.target.value)} />
                  <select className={`${tw.select} w-auto`} value={kind} onChange={e => setKind(e.target.value)}>
                    <option value="all">All reasons</option>
                    <option value="flagged">Flagged only</option>
                    <option value="status">Low confidence only</option>
                  </select>
                  <select className={`${tw.select} w-auto`} value={sort} onChange={e => setSort(e.target.value)}>
                    <option value="student">Sort by student</option>
                    <option value="question">Sort by question</option>
                  </select>
                  <span className={`${tw.muted} ml-auto`}>{items.length} shown</span>
                </div>

                {/* Bulk bar */}
                {items.length > 0 && (
                  <div className="flex items-center justify-between gap-3">
                    <label className="flex cursor-pointer select-none items-center gap-2 text-xs text-zinc-400">
                      <input type="checkbox" className="accent-emerald-500" checked={allVisiblePicked}
                        onChange={togglePickAll} />
                      Select all shown
                    </label>
                    {picked.size > 0 && (
                      <button type="button" className={tw.btnSm} disabled={bulkBusy} onClick={markPicked}>
                        {bulkBusy ? 'Marking…' : `Mark ${picked.size} reviewed`}
                      </button>
                    )}
                  </div>
                )}

                {/* The queue */}
                {items.length === 0
                  ? <Empty text="No items match these filters." />
                  : (
                    <div className="flex flex-col gap-2">
                      {items.map(it => (
                        <div key={it.answer_id}
                          className={`${tw.card} flex flex-wrap items-center gap-3 ${picked.has(it.answer_id) ? 'border-emerald-500/40' : ''}`}>
                          <input type="checkbox" className="shrink-0 accent-emerald-500"
                            checked={picked.has(it.answer_id)} onChange={() => togglePick(it.answer_id)} />
                          <div className="min-w-[180px] flex-1">
                            <div className="text-sm font-medium text-zinc-100">{it.student_name}</div>
                            <div className="text-xs text-zinc-500">{it.student_id}</div>
                          </div>
                          <div className="min-w-[220px] flex-[2]">
                            <div className="text-xs text-zinc-400">
                              <span className="font-semibold text-zinc-200">Q{it.question_order_index ?? '?'}</span>
                              {it.question_type && <span className="ml-2 text-zinc-500">{typeLabel(it.question_type)}</span>}
                            </div>
                            <div className="text-xs text-zinc-500" title={it.question_prompt ?? ''}>
                              {snippet(it.question_prompt)}
                            </div>
                          </div>
                          <div className="flex shrink-0 flex-col items-end gap-1">
                            <span className={[
                              'rounded-full px-2 py-0.5 text-[11px] font-medium',
                              it.flagged ? 'bg-amber-500/15 text-amber-300' : 'bg-sky-500/15 text-sky-300',
                            ].join(' ')}>
                              {it.flagged ? '⚑ ' : ''}{reasonLabel(it.reason)}
                            </span>
                            <span className="text-xs text-zinc-500">
                              AI score {it.ai_score != null ? it.ai_score : '—'}{it.max_points != null ? ` / ${it.max_points}` : ''}
                            </span>
                          </div>
                          <div className="flex shrink-0 gap-2">
                            <button type="button" className={tw.btnSmPrimary} onClick={() => open(it)}>Open</button>
                            <button type="button" className={tw.btnSm} disabled={busyIds.has(it.answer_id)}
                              onClick={() => markOne(it)} title="Mark this answer as reviewed">
                              {busyIds.has(it.answer_id) ? '…' : 'Mark reviewed'}
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
              </>
            )}
    </div>
  )
}

function chipClass(active) {
  return [
    'rounded-full border px-2.5 py-1 text-xs transition',
    active
      ? 'border-amber-500/60 bg-amber-500/15 text-amber-200'
      : 'border-zinc-700 bg-zinc-900 text-zinc-300 hover:bg-zinc-800',
  ].join(' ')
}

function typeLabel(t) {
  return { essay: 'Essay', mcq: 'MCQ', tf: 'True / False', identification: 'Identification' }[t] ?? t
}
