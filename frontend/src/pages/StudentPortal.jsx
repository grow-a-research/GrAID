import { useEffect, useState } from 'react'
import { api } from '../api'
import { tw, ErrorBox, Empty } from '../ui'
import CameraCapture, { hasCameraApi } from '../components/CameraCapture'
import { dueStanding, fmtDue } from '../lib/dates'

// ── Helpers ──────────────────────────────────────────────────────────────────

const TYPE_LABEL = {
  essay: 'Essay',
  mcq: 'Multiple choice',
  tf: 'True / False',
  identification: 'Identification',
}

// What the student sees on the list and on the activity page.
const WORK_STATUS = {
  not_submitted: { label: 'Not submitted', pill: 'bg-amber-500/15 text-amber-300', dot: 'bg-amber-400' },
  draft:         { label: 'Not submitted', pill: 'bg-amber-500/15 text-amber-300', dot: 'bg-amber-400' },
  submitted:     { label: 'Submitted',     pill: 'bg-emerald-500/15 text-emerald-300', dot: 'bg-emerald-400' },
  ocr_done:      { label: 'Being checked', pill: 'bg-sky-500/15 text-sky-300', dot: 'bg-sky-400' },
  reviewed:      { label: 'Being checked', pill: 'bg-sky-500/15 text-sky-300', dot: 'bg-sky-400' },
  graded:        { label: 'Graded',        pill: 'bg-violet-500/15 text-violet-300', dot: 'bg-violet-400' },
  published:     { label: 'Graded',        pill: 'bg-violet-500/15 text-violet-300', dot: 'bg-violet-400' },
}
const statusOf = (s, pages = 0) => {
  if ((s === 'not_submitted' || s === 'draft') && pages > 0) {
    return { label: 'Draft — not submitted', pill: 'bg-amber-500/15 text-amber-300', dot: 'bg-amber-400' }
  }
  return WORK_STATUS[s] ?? { label: s, pill: 'bg-zinc-800 text-zinc-400', dot: 'bg-zinc-500' }
}
// Lateness and overdue override the plain status on the list and the page.
function workStatus(base, { late = false, overdue = false, closed = false } = {}) {
  if (closed) return { label: 'Closed', pill: 'bg-red-500/15 text-red-300', dot: 'bg-red-400' }
  if (late) return { label: 'Submitted late', pill: 'bg-orange-500/15 text-orange-300', dot: 'bg-orange-400' }
  if (overdue) return { label: 'Overdue', pill: 'bg-red-500/15 text-red-300', dot: 'bg-red-400' }
  return base
}

function fmtScore(n) {
  const v = Number(n) || 0
  return Number.isInteger(v) ? String(v) : v.toFixed(1).replace(/\.0$/, '')
}

function scoreTone(score, max) {
  if (score == null || !max) return 'text-zinc-400'
  const r = score / max
  return r >= 0.75 ? 'text-emerald-300' : r >= 0.5 ? 'text-amber-300' : 'text-red-300'
}

const isPending = (ex) => ex.submission_status === 'not_submitted' || ex.submission_status === 'draft'

function fmtPoints(n) {
  const v = Number(n) || 0
  return `${Number.isInteger(v) ? v : v.toFixed(1)} point${v === 1 ? '' : 's'}`
}

// ── Join a class ─────────────────────────────────────────────────────────────

function EnrollCard({ onJoined, first }) {
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')

  async function submit(e) {
    e.preventDefault()
    setBusy(true); setErr(''); setOk('')
    try {
      const cls = await api.student.enroll(code.trim())
      setOk(`Joined ${cls.name}`)
      setCode('')
      onJoined(cls)
    } catch (e2) { setErr(e2.message) }
    setBusy(false)
  }

  return (
    <form onSubmit={submit} className={`${tw.card} flex flex-col gap-3`}>
      <div className={tw.label}>{first ? 'Join your class' : 'Join another class'}</div>
      <p className={tw.muted}>Enter the enrollment code your teacher gave you.</p>
      <div className="flex gap-2">
        <input className={`${tw.input} uppercase tracking-widest`} placeholder="ABCD2345" maxLength={16}
          value={code} onChange={e => setCode(e.target.value)} />
        <button className={tw.btnSmPrimary} type="submit" disabled={busy || !code.trim()}
          style={{ whiteSpace: 'nowrap' }}>
          {busy ? 'Joining…' : 'Join'}
        </button>
      </div>
      <ErrorBox msg={err} />
      {ok && <div className="text-xs text-emerald-400">{ok}</div>}
    </form>
  )
}

// ── Activity list row ────────────────────────────────────────────────────────

function ActivityRow({ exam, onOpen }) {
  const st = workStatus(statusOf(exam.submission_status, exam.file_count),
    { late: exam.submitted_late, overdue: exam.overdue,
      closed: exam.closed && (exam.submission_status === 'not_submitted' || exam.submission_status === 'draft') })
  const standing = exam.submission_status === 'not_submitted' || exam.submission_status === 'draft'
    ? dueStanding(exam.due_at) : null
  const showStatus = exam.results_available
    ? { label: 'Results ready', pill: 'bg-violet-500/15 text-violet-300', dot: 'bg-violet-400' }
    : st
  return (
    <button type="button" onClick={() => onOpen(exam.id)}
      className="flex w-full items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-900/40 px-4 py-3 text-left transition hover:border-emerald-500/40 hover:bg-zinc-900">
      <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${showStatus.dot}`} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-zinc-100">{exam.title}</div>
        <div className="truncate text-xs text-zinc-500">
          {exam.exam_code} · {fmtPoints(exam.total_points)} · {exam.question_count} question{exam.question_count === 1 ? '' : 's'}
          {exam.due_at ? ` · due ${fmtDue(exam.due_at)}` : ''}
        </div>
      </div>
      {standing && !exam.overdue && (
        <span className="hidden shrink-0 text-xs text-zinc-400 sm:inline">{standing.text}</span>
      )}
      <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${showStatus.pill}`}>{showStatus.label}</span>
    </button>
  )
}

// One numbered step of the submission flow.
function Step({ n, title, done, last, children }) {
  return (
    <div className="flex gap-3">
      <div className="flex flex-col items-center">
        <span className={[
          'flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
          done ? 'bg-emerald-500 text-emerald-950' : 'border border-zinc-600 text-zinc-300',
        ].join(' ')}>
          {done ? '✓' : n}
        </span>
        {!last && <span className="mt-1 w-px flex-1 bg-zinc-800" />}
      </div>
      <div className={`min-w-0 flex-1 ${last ? '' : 'pb-5'}`}>
        <div className="mb-1.5 text-sm font-medium text-zinc-100">{title}</div>
        {children}
      </div>
    </div>
  )
}

// ── Activity detail: instructions + questions, and a 3-step submit flow ─────

function ActivityDetail({ exam, onBack, onChanged }) {
  const [sub, setSub] = useState(null)
  const [subErr, setSubErr] = useState('')
  const [questions, setQuestions] = useState(null)
  const [qErr, setQErr] = useState('')
  const [results, setResults] = useState(null)   // only when the teacher has released them
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [camOn, setCamOn] = useState(false)
  const [shot, setShot] = useState(null)   // { file, url } — a captured photo awaiting upload
  const [downloading, setDownloading] = useState(false)
  const [dlErr, setDlErr] = useState('')
  const [downloaded, setDownloaded] = useState(false)
  const [finalizing, setFinalizing] = useState(false)

  useEffect(() => {
    let live = true
    api.student.submission(exam.id).then(s => { if (live) setSub(s) }).catch(e => { if (live) setSubErr(e.message) })
    if (exam.template_ready) {
      api.student.questions(exam.id).then(q => { if (live) setQuestions(q) }).catch(e => { if (live) setQErr(e.message) })
    }
    if (exam.results_available) {
      api.student.results(exam.id).then(r => { if (live && r.released && r.graded) setResults(r) }).catch(() => {})
    }
    return () => { live = false }
  }, [exam.id, exam.template_ready, exam.results_available])

  // Release any preview URL when leaving the page.
  useEffect(() => () => { if (shot) URL.revokeObjectURL(shot.url) }, [shot])

  const baseStatus = sub?.status ?? exam.submission_status
  const isDraft = baseStatus === 'draft' || baseStatus === 'not_submitted'
  const closed = sub ? !!sub.closed : !!exam.closed     // auto-grade exam past its deadline
  const editable = sub ? sub.editable : (isDraft && !closed)   // pages can change (draft only)
  const isFinal = !isDraft                               // submitted, being checked, or graded
  const canSubmit = !!sub?.can_submit
  const canUnsubmit = !!sub?.can_unsubmit
  const isLate = sub ? sub.is_late : exam.submitted_late
  const dueIso = sub?.due_at ?? exam.due_at
  const standing = isDraft ? dueStanding(dueIso) : null
  const overdueNow = !!standing?.overdue
  const st = workStatus(statusOf(baseStatus, sub?.files?.length ?? exam.file_count),
    { late: isLate, overdue: overdueNow && !closed, closed: closed && isDraft })

  function discardShot() { setShot(null) }

  // Each file becomes the next page after the highest one already uploaded.
  async function uploadFiles(files) {
    if (files.length === 0) return false
    setBusy(true); setErr('')
    let ok = false
    try {
      const pages = sub?.files?.map(f => f.page_number) ?? []
      let next = (pages.length ? Math.max(...pages) : 0) + 1
      let latest = sub
      for (const f of files) {
        latest = await api.student.uploadFile(exam.id, f, next++)
      }
      setSub(latest)
      onChanged()
      ok = true
    } catch (e) { setErr(e.message) }
    setBusy(false)
    return ok
  }

  async function onPick(e) {
    const files = [...(e.target.files ?? [])]
    e.target.value = ''
    await uploadFiles(files)
  }

  function onCaptured(file) {
    setShot({ file, url: URL.createObjectURL(file) })
    setCamOn(false)
  }

  async function uploadShot() {
    if (shot && await uploadFiles([shot.file])) discardShot()
  }

  async function remove(fileId) {
    setBusy(true); setErr('')
    try { setSub(await api.student.deleteFile(exam.id, fileId)); onChanged() } catch (e) { setErr(e.message) }
    setBusy(false)
  }

  // Nothing reaches the teacher until the student submits.
  async function submitPaper() {
    setFinalizing(true); setErr('')
    try { setSub(await api.student.submit(exam.id)); onChanged() } catch (e) { setErr(e.message) }
    setFinalizing(false)
  }

  async function unsubmitPaper() {
    setFinalizing(true); setErr('')
    try { setSub(await api.student.unsubmit(exam.id)); onChanged() } catch (e) { setErr(e.message) }
    setFinalizing(false)
  }

  // Saves the PDF to the device rather than opening a browser preview.
  async function downloadTemplate() {
    setDownloading(true); setDlErr('')
    try {
      await api.download(api.student.templateUrl(exam.id), `${exam.exam_code}_template.pdf`)
      setDownloaded(true)
    } catch (e) { setDlErr(e.message) }
    setDownloading(false)
  }

  const pageCount = sub?.files?.length ?? 0
  const hasPages = pageCount > 0

  return (
    <div className="flex flex-col gap-5">
      <button type="button" onClick={onBack}
        className="w-fit text-sm text-zinc-400 transition hover:text-zinc-100">
        ← {exam.class_name}
      </button>

      <div>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold text-zinc-50">{exam.title}</h1>
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${st.pill}`}>{st.label}</span>
        </div>
        <div className="mt-1 text-sm text-zinc-400">
          {exam.exam_code} · {exam.class_name}{exam.teacher_name ? ` · by ${exam.teacher_name}` : ''}
        </div>
        <div className="mt-1 text-sm text-zinc-500">
          {fmtPoints(exam.total_points)} · {exam.question_count} question{exam.question_count === 1 ? '' : 's'}
        </div>
        {dueIso && (
          <div className={`mt-1 text-sm ${overdueNow ? 'text-red-300' : 'text-zinc-300'}`}>
            Deadline: {fmtDue(dueIso)}
            {standing && <span className="ml-2 text-xs opacity-80">({standing.text})</span>}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        {/* ── Left: what the teacher posted ──────────────────────────────── */}
        <div className="flex flex-col gap-6">
          {exam.description && (
            <section className="flex flex-col gap-2">
              <div className={tw.label}>Description</div>
              <div className={tw.card}>
                <p className="whitespace-pre-line text-sm text-zinc-200">{exam.description}</p>
              </div>
            </section>
          )}

          {results && (
            <section className="rounded-xl border border-violet-500/30 bg-violet-500/10 p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-violet-300">Your results</div>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="text-3xl font-semibold text-zinc-50">{fmtScore(results.total_score)}</span>
                <span className="text-lg text-zinc-400">/ {fmtScore(results.total_max)}</span>
                {results.total_max > 0 && (
                  <span className="ml-2 text-sm text-zinc-400">
                    ({Math.round((results.total_score / results.total_max) * 100)}%)
                  </span>
                )}
              </div>
            </section>
          )}

          {exam.template_ready || results
            ? (
              <section className="flex flex-col gap-3">
                <div className={tw.label}>{results ? 'Results by question' : `Questions (${exam.question_count})`}</div>
                <ErrorBox msg={qErr} />
                {!results && questions === null && !qErr && <div className={tw.muted}>Loading questions…</div>}
                {!results && questions && questions.length === 0 && <div className={tw.muted}>No questions posted yet.</div>}
                {(results ? results.questions : questions) && (results ? results.questions : questions).map((q, i) => (
                  <div key={i} className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
                    <div className="flex items-start gap-3">
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-zinc-800 text-xs font-semibold text-zinc-300">
                        {q.order_index}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="whitespace-pre-line text-sm text-zinc-100">{q.prompt}</div>
                        {q.choices && q.choices.length > 0 && (
                          <ol className="mt-2 flex flex-col gap-1 text-sm text-zinc-300">
                            {q.choices.map((c, j) => (
                              <li key={j}><span className="mr-2 text-zinc-500">{String.fromCharCode(65 + j)}.</span>{c}</li>
                            ))}
                          </ol>
                        )}
                      </div>
                      <span className="shrink-0 text-right text-xs text-zinc-500">
                        {TYPE_LABEL[q.question_type] ?? q.question_type}
                        {results
                          ? (
                            <span className={`mt-0.5 block text-sm font-semibold ${scoreTone(q.score, q.max_points)}`}>
                              {q.score == null ? '—' : fmtScore(q.score)} / {fmtScore(q.max_points)}
                            </span>
                          )
                          : <span className="block">{fmtPoints(q.max_points)}</span>}
                      </span>
                    </div>

                    {/* Released results: essays show per-criterion scores, others the correct answer */}
                    {results && q.criteria && q.criteria.length > 0 && (
                      <div className="mt-3 flex flex-col gap-1 border-t border-zinc-800 pt-3">
                        {q.criteria.map((c, j) => (
                          <div key={j} className="flex items-center justify-between gap-3 text-sm">
                            <span className="text-zinc-300">{c.criterion}</span>
                            <span className="shrink-0 tabular-nums text-zinc-200">
                              {fmtScore(c.score)} / {fmtScore(c.max_points)}
                            </span>
                          </div>
                        ))}
                        {q.total_adjusted && (
                          <div className="mt-1 text-xs text-zinc-500">
                            Your teacher adjusted the total for this answer.
                          </div>
                        )}
                      </div>
                    )}
                    {results && q.correct_answer && (
                      <div className="mt-3 border-t border-zinc-800 pt-3 text-sm">
                        <span className="text-zinc-500">Correct answer: </span>
                        <span className="font-medium text-emerald-300">{q.correct_answer}</span>
                      </div>
                    )}
                    {results && q.question_type === 'essay' && !(q.criteria && q.criteria.length > 0) && q.score != null && (
                      <div className="mt-3 border-t border-zinc-800 pt-3 text-xs text-zinc-500">
                        This question was graded as a single score.
                      </div>
                    )}
                  </div>
                ))}
              </section>
            )
            : (
              <div className="rounded-lg border border-dashed border-zinc-700 px-4 py-6 text-center text-sm text-zinc-500">
                The questions will appear here once your teacher publishes this activity.
              </div>
            )}
        </div>

        {/* ── Right: submit in three steps (first on small screens) ──────── */}
        <aside className="order-first lg:order-none">
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 lg:sticky lg:top-20">
            <h2 className="mb-4 text-base font-semibold text-zinc-100">Submit your answers</h2>
            <ErrorBox msg={subErr} />

            <Step n={1} title="Get your answer sheet" done={downloaded || hasPages}>
              {exam.template_ready
                ? (
                  <button type="button" className={`${tw.btnGhost} w-full`} onClick={downloadTemplate}
                    disabled={downloading}>
                    {downloading ? 'Preparing…' : `Download ${exam.exam_code}_template.pdf`}
                  </button>
                )
                : <div className="text-xs text-zinc-500">Not ready yet — your teacher hasn't published it.</div>}
              <ErrorBox msg={dlErr} />
            </Step>

            <Step n={2} title="Complete it" done={hasPages}>
              <div className="text-xs text-zinc-500">
                Print the sheet and write your answers in the boxes next to each question.
              </div>
            </Step>

            <Step n={3} title="Photograph, upload and submit" done={isFinal} last>
              {/* Uploaded pages */}
              {hasPages && (
                <div className="mb-2 flex flex-col gap-1.5">
                  {sub.files.map(f => (
                    <div key={f.id}
                      className="flex items-center gap-2 rounded-md border border-zinc-800 bg-zinc-950/50 px-3 py-1.5 text-sm">
                      <span className="text-emerald-400">✓</span>
                      <span className="min-w-0 flex-1 truncate text-zinc-200">
                        Page {f.page_number}
                        <span className="ml-2 text-xs text-zinc-500">{f.original_filename}</span>
                      </span>
                      {editable && (
                        <button type="button" disabled={busy} onClick={() => remove(f.id)}
                          title="Remove this page"
                          className="px-1 text-zinc-500 transition hover:text-red-400">✕</button>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {editable && camOn && (
                <CameraCapture onCapture={onCaptured} onCancel={() => setCamOn(false)} />
              )}

              {editable && !camOn && shot && (
                <div className="flex flex-col gap-2">
                  <img src={shot.url} alt="Captured page"
                    className="max-h-56 w-full rounded-lg border border-emerald-700/50 object-contain" />
                  <div className="text-xs text-emerald-400">Photo captured — check that it is sharp and readable.</div>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" className={tw.btnSmPrimary} onClick={uploadShot} disabled={busy}>
                      {busy ? 'Uploading…' : 'Upload this page'}
                    </button>
                    <button type="button" className={tw.btnSm} disabled={busy}
                      onClick={() => { discardShot(); setCamOn(true) }}>Retake</button>
                    <button type="button" className={tw.btnSm} disabled={busy} onClick={discardShot}>Discard</button>
                  </div>
                </div>
              )}

              {editable && !camOn && !shot && (
                <div className="flex flex-col gap-2">
                  {hasCameraApi && (
                    <button type="button" className={`${tw.btnPrimary} w-full`} disabled={busy}
                      onClick={() => setCamOn(true)}>
                      {hasPages ? 'Scan another page' : 'Scan with camera'}
                    </button>
                  )}
                  {/* On phones this opens the native camera app, even where the
                      live camera above is unavailable (e.g. plain http on the LAN). */}
                  <label className={`${hasCameraApi ? tw.btnGhost : tw.btnPrimary} w-full cursor-pointer text-center sm:hidden`}>
                    Take a photo
                    <input type="file" accept="image/*" capture="environment" className="hidden"
                      onChange={onPick} disabled={busy} />
                  </label>
                  <label className={`${tw.btnGhost} w-full cursor-pointer text-center`}>
                    {busy ? 'Uploading…' : 'Choose image files'}
                    <input type="file" accept="image/*" multiple className="hidden" onChange={onPick} disabled={busy} />
                  </label>
                  <div className="text-xs text-zinc-500">
                    JPG or PNG, up to 15 MB each. Pages are added in order.
                  </div>
                </div>
              )}

              {/* Final step: the paper is only sent to the teacher when submitted. */}
              {editable && !camOn && !shot && (
                <div className="mt-3 flex flex-col gap-1.5 border-t border-zinc-800 pt-3">
                  {overdueNow && (
                    <div className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
                      The deadline has passed. You can still submit, but it will be marked <b>Late</b>.
                    </div>
                  )}
                  <button type="button" className={`${tw.btnPrimary} w-full`}
                    disabled={!canSubmit || busy || finalizing} onClick={submitPaper}>
                    {finalizing ? 'Submitting…' : 'Submit'}
                  </button>
                  <div className="text-xs text-zinc-500">
                    {canSubmit
                      ? 'Not final yet. Your teacher sees your paper only after you press Submit.'
                      : 'Add at least one page to enable Submit.'}
                  </div>
                </div>
              )}

              {closed && isDraft && (
                <div className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
                  Submissions are closed. The deadline has passed and grading is under way,
                  so this paper can no longer be submitted or changed. Ask your teacher if you
                  need to hand it in late.
                </div>
              )}

              {isFinal && (
                <div className="flex flex-col gap-2">
                  {canUnsubmit
                    ? (
                      <>
                        <div className={`text-sm ${isLate ? 'text-orange-300' : 'text-emerald-300'}`}>
                          {isLate
                            ? 'Submitted late (after the deadline). Your teacher can see your paper.'
                            : 'Submitted. Your teacher can now see your paper.'}
                        </div>
                        <button type="button" className={`${tw.btnGhost} w-full`}
                          disabled={finalizing} onClick={unsubmitPaper}>
                          {finalizing ? 'Working…' : 'Unsubmit to make changes'}
                        </button>
                      </>
                    )
                    : (
                      <div className="text-xs text-zinc-500">
                        Your paper has been handed in and can't be changed here.
                      </div>
                    )}
                </div>
              )}
              <ErrorBox msg={err} />
            </Step>
          </div>
        </aside>
      </div>
    </div>
  )
}

// ── Portal shell ─────────────────────────────────────────────────────────────

export default function StudentPortal({ session, onLogout }) {
  const [profile, setProfile] = useState(null)
  const [exams, setExams] = useState([])
  const [classes, setClasses] = useState([])
  const [classId, setClassId] = useState(null)
  const [openExamId, setOpenExamId] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [showJoin, setShowJoin] = useState(false)

  async function load(preferClassId) {
    try {
      const p = await api.student.profile()
      setProfile(p)
      if (p.linked) {
        const [c, e] = await Promise.all([api.student.classes(), api.student.exams()])
        setClasses(c); setExams(e)
        // Keep the current class if it still exists; otherwise start on the first one.
        setClassId(prev => {
          const wanted = preferClassId ?? prev
          return c.some(x => x.id === wanted) ? wanted : (c[0]?.id ?? null)
        })
      }
    } catch (e) { setErr(e.message) }
    setLoading(false)
  }
  useEffect(() => { load() }, [])

  async function refreshExams() {
    try { setExams(await api.student.exams()) } catch { /* keep the list we have */ }
  }

  const current = classes.find(c => c.id === classId) ?? null
  const classExams = exams.filter(e => e.class_id === classId)
  const openExam = openExamId != null ? exams.find(e => e.id === openExamId) ?? null : null

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <header className="sticky top-0 z-10 border-b border-zinc-800 bg-zinc-900/60 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-3">
          <div className="h-2 w-2 rounded-full bg-emerald-400" />
          <span className="text-sm font-semibold">GrAId</span>
          <span className="text-xs text-zinc-600">Student portal</span>
          <span className="ml-auto hidden text-xs text-zinc-400 sm:inline">{session.user.full_name}</span>
          <button type="button" className={tw.btnSm} onClick={onLogout}>Log out</button>
        </div>
      </header>

      <main className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-8">
        <ErrorBox msg={err} />
        {loading
          ? <div className={tw.muted}>Loading…</div>
          : !profile?.linked
            ? <div className="max-w-xl"><EnrollCard first onJoined={cls => load(cls?.id)} /></div>
            : openExam
              ? <ActivityDetail key={openExam.id} exam={openExam}
                  onBack={() => setOpenExamId(null)} onChanged={refreshExams} />
              : <>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h1 className="text-2xl font-semibold text-zinc-50">My classes</h1>
                      <p className="mt-1 text-sm text-zinc-400">
                        Pick a class, then open an activity to see its questions and submit your work.
                      </p>
                    </div>
                    <button type="button" className={tw.btnSm} onClick={() => setShowJoin(s => !s)}>
                      {showJoin ? 'Close' : 'Join another class'}
                    </button>
                  </div>

                  {showJoin && (
                    <div className="max-w-xl">
                      <EnrollCard onJoined={cls => { setShowJoin(false); load(cls?.id) }} />
                    </div>
                  )}

                  {/* One tab per class, with how many activities still need work */}
                  <div className="flex flex-wrap gap-2">
                    {classes.map(c => {
                      const todo = exams.filter(e => e.class_id === c.id && isPending(e)).length
                      return (
                        <button key={c.id} type="button" onClick={() => setClassId(c.id)}
                          className={[
                            'flex items-center gap-2 rounded-lg border px-3 py-2 text-left text-sm transition',
                            c.id === classId
                              ? 'border-emerald-500/50 bg-emerald-500/10 text-zinc-100'
                              : 'border-zinc-800 bg-zinc-900/40 text-zinc-400 hover:border-zinc-700 hover:text-zinc-100',
                          ].join(' ')}>
                          <span>
                            <span className="block font-medium">{c.name}</span>
                            <span className="block text-xs text-zinc-500">{c.code}</span>
                          </span>
                          {todo > 0 && (
                            <span title={`${todo} assigned`}
                              className="rounded-full bg-amber-500/20 px-2 py-0.5 text-xs text-amber-300">{todo}</span>
                          )}
                        </button>
                      )
                    })}
                  </div>

                  {current && (
                    <section className="flex flex-col gap-2">
                      <div className={tw.label}>Activities and exams in {current.name} ({classExams.length})</div>
                      {classExams.length === 0
                        ? <Empty text="Your teacher hasn't posted any activities or exams in this class yet." />
                        : classExams.map(ex => <ActivityRow key={ex.id} exam={ex} onOpen={setOpenExamId} />)}
                    </section>
                  )}
                </>}
      </main>
    </div>
  )
}
