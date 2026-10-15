import { useState } from 'react'
import { api } from '../api'
import { tw, ErrorBox } from '../ui'
import { fmtDue } from '../lib/dates'

const GRADED = ['graded', 'reviewed', 'published']

// Teacher control: students see nothing about their grades until results are
// released for the exam. `onChanged(updatedExam)` gets the server's exam row.
export default function ReleaseResultsCard({ exam, submissions, onChanged }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const released = !!exam.results_released_at
  const graded = submissions.filter(s => GRADED.includes(s.status)).length
  const total = submissions.length

  async function toggle() {
    const next = !released
    if (next) {
      const pending = total - graded
      const msg =
        `Release results for "${exam.title}" to its students?\n\n` +
        `${graded} of ${total} submission${total === 1 ? '' : 's'} graded` +
        (pending > 0 ? ` — the other ${pending} will show "not graded yet" to those students.` : '.') +
        `\n\nStudents will see their score per question, the per-criterion scores for essays, ` +
        `and the correct answers for the other question types. You can withdraw this later.`
      if (!window.confirm(msg)) return
    }
    setBusy(true); setErr('')
    try { onChanged(await api.exams.setResultsRelease(exam.id, next)) } catch (e) { setErr(e.message) }
    setBusy(false)
  }

  return (
    <div className={`${tw.card} flex flex-col gap-2`}>
      <div className="flex items-center justify-between gap-2">
        <div className={tw.label}>Student results</div>
        <span className={[
          'rounded-full px-2 py-0.5 text-xs font-medium',
          released ? 'bg-emerald-500/15 text-emerald-300' : 'bg-zinc-800 text-zinc-400',
        ].join(' ')}>
          {released ? 'Released' : 'Not released'}
        </span>
      </div>
      <div className="text-xs text-zinc-500">
        {released
          ? `Students can see their results (released ${fmtDue(exam.results_released_at)}).`
          : 'Students can see that their paper is graded, but not their scores.'}
        {' '}{graded} of {total} graded.
      </div>
      <button type="button" className={released ? tw.btnGhost : tw.btnPrimary} disabled={busy} onClick={toggle}>
        {busy ? 'Working…' : released ? 'Withdraw results' : 'Release results to students'}
      </button>
      <ErrorBox msg={err} />
    </div>
  )
}
