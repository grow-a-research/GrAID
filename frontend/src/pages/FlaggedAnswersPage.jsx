import { useEffect, useState } from 'react'
import { api } from '../api'
import { tw, ErrorBox, Empty } from '../ui'
import { useWorkflow } from '../context/WorkflowContext'
import ClassPicker, { ExamPicker } from '../components/ClassPicker'
import { REASON_LABELS, DECISION_COLOR } from '../flagLabels'

// One row in the flagged-answers list. Reuses the same review endpoints as
// the per-answer flag badge on the Results page (reviewFlag / deleteFlag) —
// this page only adds a new place to see and act on them, not a new mechanism.
function FlaggedAnswerRow({ row, onRowChange, onOpen }) {
  const [busy, setBusy] = useState(false)

  async function act(decision) {
    setBusy(true)
    try {
      if (decision === 'remove') {
        await api.submissions.deleteFlag(row.submission_id, row.submission_answer_id)
        onRowChange(row.submission_answer_id, null)
      } else {
        const updated = await api.submissions.reviewFlag(
          row.submission_id, row.submission_answer_id, { review_decision: decision }
        )
        onRowChange(row.submission_answer_id, updated)
      }
    } catch (err) { alert(err.message) }
    setBusy(false)
  }

  const reasonLabel = REASON_LABELS[row.flag_reason] ?? row.flag_reason
  const score = row.teacher_score ?? row.ai_score

  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-zinc-800 bg-zinc-900/40 px-3 py-2 sm:flex-row sm:items-center sm:gap-3">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm text-zinc-100">{row.student_name}</span>
          <span className={tw.muted}>{row.student_id}</span>
          <span className={tw.muted}>·</span>
          <span className={tw.muted}>
            {row.question_order_index != null ? `Q${row.question_order_index}` : 'Q?'}
          </span>
          {score != null && <span className={tw.muted}>· {score}</span>}
        </div>
        {row.question_prompt && (
          <div className="text-xs text-zinc-600 truncate mt-0.5">{row.question_prompt}</div>
        )}
      </div>
      <div className="flex items-center gap-2 flex-wrap shrink-0">
        <span className={`text-xs rounded border px-1.5 py-0.5 ${
          row.review_decision ? DECISION_COLOR[row.review_decision] : 'border-amber-700 bg-amber-950/40 text-amber-300'
        }`}>
          {row.review_decision ? {
            confirmed_error: '✗ Confirmed error',
            false_positive:  '~ False positive',
          }[row.review_decision] : `⚑ ${reasonLabel}`}
        </span>
        {!row.review_decision && (
          <>
            <button type="button" disabled={busy} onClick={() => act('confirmed_error')}
              className="text-xs rounded border border-red-800 bg-red-950/30 text-red-300 hover:bg-red-900/40 px-2 py-0.5 transition">
              {busy ? '…' : 'Confirm error'}
            </button>
            <button type="button" disabled={busy} onClick={() => act('false_positive')}
              className="text-xs rounded border border-zinc-700 text-zinc-400 hover:text-zinc-200 px-2 py-0.5 transition">
              {busy ? '…' : 'Not an error'}
            </button>
          </>
        )}
        <button type="button" disabled={busy} onClick={() => act('remove')}
          className="text-xs text-zinc-600 hover:text-zinc-400 transition px-1">
          Remove
        </button>
        <button type="button" onClick={() => onOpen(row.submission_id)} className={tw.btnSm}>
          Open
        </button>
      </div>
    </div>
  )
}

// Exam-wide view of every flagged answer, for reviewing without opening each
// submission one at a time. Purely a UI convenience — it reads from and
// writes to the existing flag_log rows via the existing endpoints, and never
// touches grading, OCR, OMR, or the auto-flagging logic that creates them.
export default function FlaggedAnswersPage() {
  const {
    selectedClass, selectClass,
    selectedExam, selectExam: pickExam,
    selectSubmission, setActiveTab,
  } = useWorkflow()
  const [classes, setClasses]         = useState([])
  const [exams, setExams]             = useState([])
  const [submissions, setSubmissions] = useState([])
  const [rows, setRows]               = useState(null)
  const [loading, setLoading]         = useState(false)
  const [err, setErr]                 = useState('')

  useEffect(() => { api.classes.list().then(setClasses).catch(() => {}) }, [])

  useEffect(() => {
    if (!selectedClass) { setExams([]); return }
    api.exams.list(selectedClass.id).then(setExams).catch(() => setExams([]))
  }, [selectedClass?.id])

  // Arriving with an exam already picked on another tab: show its class too.
  useEffect(() => {
    if (selectedExam && !selectedClass && classes.length > 0) {
      const cls = classes.find(c => c.id === selectedExam.class_id)
      if (cls) selectClass(cls)
    }
  }, [classes, selectedExam?.id])

  function changeClass(cls) {
    if (!cls) pickExam(null)   // clearing the class also closes the exam
    selectClass(cls)
  }

  useEffect(() => {
    setErr('')
    if (!selectedExam) { setSubmissions([]); setRows(null); return }
    setLoading(true)
    Promise.all([
      api.exams.submissions(selectedExam.id),
      api.exams.flags(selectedExam.id),
    ]).then(([subs, flagRows]) => {
      setSubmissions(subs)
      setRows(flagRows)
    }).catch(err => { setSubmissions([]); setRows([]); setErr(err.message) })
      .finally(() => setLoading(false))
  }, [selectedExam?.id])

  function refresh() {
    if (!selectedExam) return
    api.exams.flags(selectedExam.id).then(setRows).catch(() => {})
  }

  function handleRowChange(answerId, updatedFlag) {
    setRows(prev => (prev ?? [])
      .map(r => r.submission_answer_id === answerId ? { ...r, ...updatedFlag } : r)
      .filter(r => updatedFlag !== null || r.submission_answer_id !== answerId)
    )
  }

  // Jumps to the Results tab with that student's submission already selected.
  function handleOpen(submissionId) {
    const sub = submissions.find(s => s.id === submissionId)
    if (!sub) return
    selectSubmission(sub)
    setActiveTab('results')
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1 min-w-[220px]">
          <ClassPicker classes={classes} value={selectedClass} onChange={changeClass} />
        </div>
        {selectedClass && (
          <div className="flex flex-col gap-1 min-w-[260px] flex-1">
            <ExamPicker exams={exams} value={selectedExam} onChange={pickExam} />
          </div>
        )}
        {selectedExam && (
          <button className={tw.btnSm} onClick={refresh}>Refresh</button>
        )}
      </div>

      <ErrorBox msg={err} />

      {!selectedExam
        ? <div className="flex h-40 items-center justify-center rounded-xl border border-dashed border-zinc-700">
            <span className={tw.muted}>
              {selectedClass ? 'Select an exam to see its flagged answers' : 'Select a class, then an exam, to see its flagged answers'}
            </span>
          </div>
        : loading
          ? <div className={tw.muted}>Loading…</div>
          : (rows == null || rows.length === 0)
            ? <Empty text="No flagged answers for this exam." />
            : (
              <div className="flex flex-col gap-2">
                {rows.map(r => (
                  <FlaggedAnswerRow key={r.id} row={r} onRowChange={handleRowChange} onOpen={handleOpen} />
                ))}
              </div>
            )
      }
    </div>
  )
}
