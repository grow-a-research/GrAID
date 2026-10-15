import { useEffect, useState } from 'react'
import { api } from '../api'
import { tw, ErrorBox } from '../ui'
import { fmtDue, fromInputValue, toInputValue } from '../lib/dates'
import DeadlinePicker from './DeadlinePicker'

// Shows an exam's deadline and lets the teacher set, change or clear it.
// "No deadline" in the dropdown clears it. `onSaved(updatedExam)` receives the
// exam returned by the server.
export default function DeadlineEditor({ exam, onSaved }) {
  const [value, setValue] = useState(toInputValue(exam.due_at))
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [saved, setSaved] = useState(false)

  // Follow the exam when a different one is opened or it changes elsewhere.
  useEffect(() => { setValue(toInputValue(exam.due_at)); setErr(''); setSaved(false) }, [exam.id, exam.due_at])

  const dirty = value !== toInputValue(exam.due_at)
  const started = !!exam.auto_grade_started_at

  async function toggleAutoGrade() {
    const next = !exam.auto_grade
    if (next) {
      const ok = window.confirm(
        `Turn on automatic grading for "${exam.title}"?\n\n` +
        `After the deadline (${fmtDue(exam.due_at)}):\n` +
        `• Students can no longer submit, edit or unsubmit.\n` +
        `• Every submitted paper is graded automatically.\n` +
        `• You get a notification when it finishes.\n\n` +
        `Results stay hidden from students until you release them.`
      )
      if (!ok) return
    }
    setBusy(true); setErr('')
    try { onSaved(await api.exams.setAutoGrade(exam.id, next)) } catch (e) { setErr(e.message) }
    setBusy(false)
  }

  async function save() {
    setBusy(true); setErr(''); setSaved(false)
    try {
      const updated = await api.exams.setDeadline(exam.id, fromInputValue(value))
      onSaved(updated)
      setSaved(true)
    } catch (e) { setErr(e.message) }
    setBusy(false)
  }

  return (
    <div className={`${tw.card} flex flex-col gap-2`}>
      <div className="flex items-center justify-between gap-2">
        <div className={tw.label}>Deadline</div>
        <div className="text-xs text-zinc-500">
          {exam.due_at ? `Currently: ${fmtDue(exam.due_at)}` : 'No deadline set'}
        </div>
      </div>
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-[220px] max-w-xs flex-1">
          <DeadlinePicker value={value} disabled={busy}
            onChange={v => { setValue(v); setSaved(false) }} />
        </div>
        <button type="button" className={tw.btnSmPrimary} disabled={busy || !dirty} onClick={save}>
          {busy ? 'Saving…' : 'Save deadline'}
        </button>
        {saved && <span className="pt-1.5 text-xs text-emerald-400">Saved</span>}
      </div>
      <div className="text-xs text-zinc-500">
        {exam.auto_grade
          ? 'Submissions close at the deadline (no submitting, editing or unsubmitting).'
          : <>Late submissions are still accepted but are marked <span className="text-zinc-300">Late</span> for you and the student.</>}
      </div>

      {/* Automatic grading after the deadline */}
      <label className={`mt-1 flex items-start gap-2 rounded-lg border border-zinc-800 bg-zinc-950/40 p-3 ${
        (!exam.due_at || started || dirty) ? 'opacity-70' : 'cursor-pointer'}`}>
        <input type="checkbox" className="mt-0.5 accent-emerald-500" checked={!!exam.auto_grade}
          disabled={busy || started || !exam.due_at || dirty} onChange={toggleAutoGrade} />
        <span className="min-w-0">
          <span className="block text-sm text-zinc-200">Grade automatically after the deadline</span>
          <span className="block text-xs text-zinc-500">
            {started
              ? (exam.auto_grade_finished_at
                ? `Finished ${fmtDue(exam.auto_grade_finished_at)}. Review the results, then release them.`
                : `Grading started ${fmtDue(exam.auto_grade_started_at)} and is in progress.`)
              : !exam.due_at
                ? 'Set and save a deadline first.'
                : dirty
                  ? 'Save the deadline change first.'
                  : 'Closes submissions at the deadline, grades submitted papers, then notifies you. Results stay hidden until you release them.'}
          </span>
        </span>
      </label>
      <ErrorBox msg={err} />
    </div>
  )
}
