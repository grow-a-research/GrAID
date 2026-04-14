import { useEffect, useState } from 'react'
import { api } from '../api'
import { tw, ErrorBox, Empty } from '../ui'

const PAPER_TABS = [
  { id: 'aligned',  label: 'Aligned scan',   hint: 'perspective-corrected' },
  { id: 'original', label: 'Original scan',  hint: 'as uploaded' },
  { id: 'pdf',      label: 'Student PDF',    hint: 'generated paper' },
]

function ProcessedPaperPanel({ submissionId, answers, hasPaper }) {
  const [activeTab, setActiveTab] = useState('aligned')
  const [page, setPage] = useState(1)

  const pages = [...new Set(answers.map(a => a.page_number).filter(Boolean))].sort()
  if (pages.length === 0) pages.push(1)
  const multiPage = pages.length > 1

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/30 overflow-hidden">
      {/* Tab bar */}
      <div className="flex items-center gap-0 border-b border-zinc-800 bg-zinc-900/60 px-1 pt-1">
        {PAPER_TABS.map(tab => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id)}
            className={[
              'px-3 py-1.5 text-xs rounded-t transition-colors',
              activeTab === tab.id
                ? 'bg-zinc-800 text-zinc-100 border border-b-0 border-zinc-700'
                : 'text-zinc-500 hover:text-zinc-300',
            ].join(' ')}
          >
            {tab.label}
            <span className="ml-1 text-zinc-600">({tab.hint})</span>
          </button>
        ))}
        {multiPage && (
          <div className="ml-auto flex items-center gap-1 pr-2 pb-1">
            <span className="text-xs text-zinc-600">Page</span>
            {pages.map(p => (
              <button key={p} type="button"
                onClick={() => setPage(p)}
                className={[
                  'w-6 h-6 rounded text-xs transition',
                  page === p ? 'bg-zinc-700 text-zinc-100' : 'text-zinc-500 hover:text-zinc-300',
                ].join(' ')}>
                {p}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Tab content */}
      <div className="p-2">
        {activeTab === 'aligned' && (
          <img
            src={api.submissions.alignedImageUrl(submissionId, page)}
            alt={`Aligned scan page ${page}`}
            className="w-full object-contain bg-zinc-950 rounded"
            onError={e => {
              e.currentTarget.replaceWith(
                Object.assign(document.createElement('div'), {
                  className: 'flex h-24 items-center justify-center text-xs text-zinc-600',
                  textContent: 'Aligned scan not available — OCR may have used the fallback path.',
                })
              )
            }}
          />
        )}

        {activeTab === 'original' && (
          <img
            src={api.submissions.originalImageUrl(submissionId, page)}
            alt={`Original scan page ${page}`}
            className="w-full object-contain bg-zinc-950 rounded"
            onError={e => {
              e.currentTarget.replaceWith(
                Object.assign(document.createElement('div'), {
                  className: 'flex h-24 items-center justify-center text-xs text-zinc-600',
                  textContent: 'Original scan not found.',
                })
              )
            }}
          />
        )}

        {activeTab === 'pdf' && (
          hasPaper
            ? (
              <div className="flex flex-col gap-2">
                <iframe
                  src={api.submissions.paperUrl(submissionId)}
                  title="Student exam paper"
                  className="w-full rounded border border-zinc-800 bg-zinc-950"
                  style={{ height: '70vh' }}
                />
                <a
                  href={api.submissions.paperUrl(submissionId)}
                  download
                  className={`${tw.btnSm} self-start text-center`}
                >
                  Download PDF
                </a>
              </div>
            )
            : (
              <div className="flex h-24 items-center justify-center text-xs text-zinc-600">
                Student paper not available — generate the exam template first.
              </div>
            )
        )}
      </div>
    </div>
  )
}

function ScoreBar({ score, max, color = 'emerald' }) {
  const pct = max > 0 ? Math.min(100, (score / max) * 100) : 0
  const colorClass = color === 'violet' ? 'bg-violet-500' : 'bg-emerald-500'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-zinc-800">
        <div className={`h-1.5 rounded-full ${colorClass} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-zinc-400 tabular-nums w-16 text-right">
        {score?.toFixed(1) ?? '—'} / {max}
      </span>
    </div>
  )
}

function FlagBadge({ flag, answerId, submissionId, onFlagChange }) {
  const [busy, setBusy] = useState(false)

  const decisionColor = {
    confirmed_error: 'border-red-700 bg-red-950/40 text-red-300',
    false_positive:  'border-zinc-700 bg-zinc-800/40 text-zinc-400',
    verified:        'border-emerald-800 bg-emerald-950/30 text-emerald-400',
  }

  async function act(decision) {
    setBusy(true)
    try {
      if (decision === 'remove') {
        await api.submissions.deleteFlag(submissionId, answerId)
        onFlagChange(answerId, null)
      } else {
        const updated = await api.submissions.reviewFlag(submissionId, answerId, { review_decision: decision })
        onFlagChange(answerId, updated)
      }
    } catch (err) { alert(err.message) }
    setBusy(false)
  }

  async function addFlag() {
    setBusy(true)
    try {
      const created = await api.submissions.createFlag(submissionId, answerId, { flag_reason: 'manual' })
      onFlagChange(answerId, created)
    } catch (err) { alert(err.message) }
    setBusy(false)
  }

  if (!flag) {
    return (
      <div className="flex items-center gap-2 mt-2 pt-2 border-t border-zinc-800">
        <button type="button" onClick={addFlag} disabled={busy}
          className="text-xs text-zinc-600 hover:text-amber-400 transition">
          {busy ? '…' : '⚑ Flag for review'}
        </button>
        <button type="button" onClick={() => act('verified')} disabled={busy}
          className="text-xs text-zinc-600 hover:text-emerald-400 transition">
          {busy ? '…' : '✓ Mark as verified'}
        </button>
      </div>
    )
  }

  const reasonLabel = {
    essay_score_zero:       'Zero score',
    essay_low_confidence:   'Low AI confidence',
    omr_low_confidence:     'Low OMR confidence',
    omr_no_detection:       'No bubble detected',
    identification_no_match:'No match',
    manual:                 'Manual flag',
    verified:               'Verified',
  }[flag.flag_reason] ?? flag.flag_reason

  return (
    <div className={`mt-2 pt-2 border-t border-zinc-800 flex flex-col gap-1.5`}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className={`text-xs rounded border px-1.5 py-0.5 ${
          flag.review_decision ? decisionColor[flag.review_decision] : 'border-amber-700 bg-amber-950/40 text-amber-300'
        }`}>
          {flag.review_decision ? {
            confirmed_error: '✗ Confirmed error',
            false_positive:  '~ False positive',
            verified:        '✓ Verified',
          }[flag.review_decision] : `⚑ Flagged: ${reasonLabel}`}
        </span>
        {flag.auto_flagged && !flag.review_decision && (
          <span className="text-xs text-zinc-600">auto</span>
        )}
      </div>
      {!flag.review_decision && (
        <div className="flex gap-2 flex-wrap">
          <button type="button" disabled={busy} onClick={() => act('confirmed_error')}
            className="text-xs rounded border border-red-800 bg-red-950/30 text-red-300 hover:bg-red-900/40 px-2 py-0.5 transition">
            {busy ? '…' : 'Confirm error'}
          </button>
          <button type="button" disabled={busy} onClick={() => act('false_positive')}
            className="text-xs rounded border border-zinc-700 text-zinc-400 hover:text-zinc-200 px-2 py-0.5 transition">
            {busy ? '…' : 'Not an error'}
          </button>
          <button type="button" disabled={busy} onClick={() => act('remove')}
            className="text-xs text-zinc-600 hover:text-zinc-400 transition px-1">
            Remove flag
          </button>
        </div>
      )}
      {flag.review_decision && (
        <button type="button" disabled={busy} onClick={() => act('remove')}
          className="text-xs text-zinc-600 hover:text-zinc-400 transition self-start">
          {busy ? '…' : 'Clear review'}
        </button>
      )}
    </div>
  )
}

function AnswerCard({ answer, question, flag, onOverrideSaved, onFlagChange }) {
  const [scoreInput, setScoreInput] = useState(
    answer.teacher_score != null ? String(answer.teacher_score) : ''
  )
  const [noteInput, setNoteInput]         = useState(answer.teacher_note ?? '')
  const [refInput, setRefInput]           = useState('')
  const [saving, setSaving]               = useState(false)
  const [saveErr, setSaveErr]             = useState('')
  const [saved, setSaved]                 = useState(false)

  const maxPts     = question?.max_points ?? 10
  const aiScore    = answer.ai_score
  const finalScore = answer.teacher_score != null ? answer.teacher_score : aiScore
  const qtype      = question?.question_type ?? 'essay'
  const typeMeta   = {
    essay:          { label: 'Essay',          color: 'text-zinc-500' },
    mcq:            { label: 'MCQ',            color: 'text-violet-400' },
    tf:             { label: 'True / False',   color: 'text-amber-400' },
    identification: { label: 'Identification', color: 'text-sky-400' },
  }[qtype] ?? { label: qtype, color: 'text-zinc-500' }

  let mcqChoices = []
  try { mcqChoices = question?.choices_json ? JSON.parse(question.choices_json) : [] } catch {}

  async function saveOverride(e) {
    e.preventDefault()
    const val = parseFloat(scoreInput)
    if (isNaN(val) || val < 0 || val > maxPts) {
      setSaveErr(`Score must be between 0 and ${maxPts}`)
      return
    }
    setSaving(true); setSaveErr(''); setSaved(false)
    try {
      const updated = await api.submissions.override(
        answer.submission_id, answer.id,
        {
          teacher_score: val,
          teacher_note: noteInput.trim() || null,
          reference_text: refInput.trim() || null,
        }
      )
      onOverrideSaved(updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (err) { setSaveErr(err.message) }
    setSaving(false)
  }

  function clearOverride(e) {
    e.preventDefault()
    setScoreInput('')
    setNoteInput('')
  }

  return (
    <div className={answer.teacher_score != null ? tw.cardActive : tw.card}>
      {/* Question header */}
      <div className="flex items-start justify-between gap-2 mb-3">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-semibold text-zinc-400 uppercase tracking-wide">
              {question ? `Q${question.order_index}` : `Page ${answer.page_number}`}
            </span>
            {question && (
              <span className={`text-xs font-mono ${typeMeta.color}`}>[{typeMeta.label}]</span>
            )}
          </div>
          {question && (
            <div className="text-sm text-zinc-100">{question.prompt}</div>
          )}
          {!question && (
            <div className="text-xs text-zinc-500 italic">Full-page OCR (no region alignment)</div>
          )}
        </div>
        <div className="flex flex-col items-end gap-1 shrink-0">
          {finalScore != null && (
            <span className="text-lg font-bold text-zinc-100 tabular-nums">
              {finalScore.toFixed(1)}
              <span className="text-sm font-normal text-zinc-500">/{maxPts}</span>
            </span>
          )}
          {answer.teacher_score != null && (
            <span className="text-xs text-violet-400">teacher override</span>
          )}
        </div>
      </div>

      {/* Score bars */}
      {aiScore != null && (
        <div className="mb-3 flex flex-col gap-1">
          <div className="text-xs text-zinc-500">AI score</div>
          <ScoreBar score={aiScore} max={maxPts} color="emerald" />
          {answer.teacher_score != null && (
            <>
              <div className="text-xs text-zinc-500 mt-1">Override score</div>
              <ScoreBar score={answer.teacher_score} max={maxPts} color="violet" />
            </>
          )}
        </div>
      )}

      {/* CER / WER */}
      {(answer.cer != null || answer.wer != null) && (
        <div className="flex gap-4 mb-3">
          {answer.cer != null && (
            <div className="text-xs text-zinc-400">
              CER <span className="text-zinc-200 font-mono">{(answer.cer * 100).toFixed(1)}%</span>
            </div>
          )}
          {answer.wer != null && (
            <div className="text-xs text-zinc-400">
              WER <span className="text-zinc-200 font-mono">{(answer.wer * 100).toFixed(1)}%</span>
            </div>
          )}
        </div>
      )}

      {/* OMR confidence (MCQ / TF only) */}
      {answer.omr_confidence != null && (
        <div className="flex items-center gap-2 mb-3">
          <span className="text-xs text-zinc-500">OMR confidence</span>
          <div className="flex-1 max-w-[120px] h-1.5 rounded-full bg-zinc-800">
            <div
              className={`h-1.5 rounded-full transition-all ${
                answer.omr_confidence >= 0.6 ? 'bg-emerald-500' :
                answer.omr_confidence >= 0.3 ? 'bg-amber-500' : 'bg-red-500'
              }`}
              style={{ width: `${Math.round(answer.omr_confidence * 100)}%` }}
            />
          </div>
          <span className={`text-xs font-mono tabular-nums ${
            answer.omr_confidence >= 0.6 ? 'text-emerald-400' :
            answer.omr_confidence >= 0.3 ? 'text-amber-400' : 'text-red-400'
          }`}>
            {Math.round(answer.omr_confidence * 100)}%
          </span>
          {answer.omr_confidence < 0.3 && (
            <span className="text-xs rounded bg-amber-900/50 border border-amber-700 text-amber-300 px-1.5 py-0.5">
              review needed
            </span>
          )}
        </div>
      )}
      {/* Groq grading confidence (essay only) */}
      {answer.groq_confidence != null && (
        <div className="flex items-center gap-2 mb-3">
          <span className="text-xs text-zinc-500">Groq confidence</span>
          <div className="flex-1 max-w-[120px] h-1.5 rounded-full bg-zinc-800">
            <div
              className={`h-1.5 rounded-full transition-all ${
                answer.groq_confidence >= 0.7 ? 'bg-emerald-500' :
                answer.groq_confidence >= 0.4 ? 'bg-amber-500' : 'bg-red-500'
              }`}
              style={{ width: `${Math.round(answer.groq_confidence * 100)}%` }}
            />
          </div>
          <span className={`text-xs font-mono tabular-nums ${
            answer.groq_confidence >= 0.7 ? 'text-emerald-400' :
            answer.groq_confidence >= 0.4 ? 'text-amber-400' : 'text-red-400'
          }`}>
            {Math.round(answer.groq_confidence * 100)}%
          </span>
          {answer.groq_confidence < 0.4 && (
            <span className="text-xs rounded bg-amber-900/50 border border-amber-700 text-amber-300 px-1.5 py-0.5">
              low confidence
            </span>
          )}
        </div>
      )}

      {/* No-detection badge: OMR ran but detected nothing */}
      {answer.omr_confidence == null && (qtype === 'mcq' || qtype === 'tf') && answer.status === 'needs_review' && (
        <div className="mb-3">
          <span className="text-xs rounded bg-amber-900/50 border border-amber-700 text-amber-300 px-1.5 py-0.5">
            ⚠ No bubble detected — review scan
          </span>
        </div>
      )}

      {/* MCQ choices display */}
      {qtype === 'mcq' && mcqChoices.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-2">
          {mcqChoices.map((choice, i) => {
            const letter = String.fromCharCode(65 + i)
            const isCorrect = question?.correct_answer === letter
            const isStudentAnswer = answer.ocr_text?.trim().toUpperCase().startsWith(letter)
            return (
              <div key={i} className={[
                'flex items-center gap-1.5 rounded px-2 py-1 text-xs border',
                isCorrect ? 'border-emerald-700 bg-emerald-950/40 text-emerald-300' :
                isStudentAnswer && !isCorrect ? 'border-red-800 bg-red-950/40 text-red-300' :
                'border-zinc-800 text-zinc-400',
              ].join(' ')}>
                <span className="font-bold">{letter}.</span>
                <span>{choice}</span>
                {isCorrect && <span className="ml-1 text-emerald-500">✓</span>}
                {isStudentAnswer && !isCorrect && <span className="ml-1 text-red-400">✗</span>}
              </div>
            )
          })}
        </div>
      )}

      {/* T/F answer display */}
      {qtype === 'tf' && (
        <div className="mb-3 flex gap-3">
          {['True', 'False'].map(opt => {
            const isCorrect = question?.correct_answer === opt
            const isStudent = answer.ocr_text?.trim().toLowerCase() === opt.toLowerCase()
            return (
              <div key={opt} className={[
                'rounded px-3 py-1 text-xs border',
                isCorrect ? 'border-emerald-700 bg-emerald-950/40 text-emerald-300' :
                isStudent && !isCorrect ? 'border-red-800 bg-red-950/40 text-red-300' :
                'border-zinc-800 text-zinc-400',
              ].join(' ')}>
                {opt}
                {isCorrect && ' ✓'}
                {isStudent && !isCorrect && ' ✗'}
              </div>
            )
          })}
        </div>
      )}

      {/* OCR text (essay + identification full text; MCQ/TF as compact label) */}
      {answer.ocr_text && (
        <div className="mb-3">
          <div className={`${tw.label} mb-1`}>
            {qtype === 'essay' ? 'Student answer (OCR)' : 'Detected answer'}
          </div>
          {qtype === 'essay' ? (
            <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 px-3 py-2 text-xs text-zinc-300 leading-relaxed whitespace-pre-wrap max-h-36 overflow-y-auto">
              {answer.ocr_text}
            </div>
          ) : (
            <span className="inline-block rounded bg-zinc-800 px-2 py-1 text-xs text-zinc-200 font-mono">
              {answer.ocr_text.trim()}
            </span>
          )}
        </div>
      )}

      {/* Identification: show expected */}
      {qtype === 'identification' && question?.correct_answer && (
        <div className="mb-3 flex items-center gap-2 text-xs">
          <span className="text-zinc-500">Expected:</span>
          <span className="font-mono text-emerald-400">{question.correct_answer}</span>
        </div>
      )}

      {/* AI feedback */}
      {answer.ai_feedback && (
        <div className="mb-3">
          <div className={`${tw.label} mb-1`}>
            {qtype === 'essay' ? 'AI feedback' : 'Result'}
          </div>
          <div className="rounded-lg border border-zinc-700 bg-zinc-900/60 px-3 py-2 text-xs text-zinc-300 leading-relaxed">
            {answer.ai_feedback}
          </div>
        </div>
      )}

      {/* Rubric (essay only) */}
      {qtype === 'essay' && question?.rubric_text && (
        <details className="mb-3">
          <summary className="text-xs text-zinc-500 cursor-pointer hover:text-zinc-300 select-none">
            View rubric
          </summary>
          <div className="mt-1 rounded-lg border border-zinc-800 bg-zinc-950/40 px-3 py-2 text-xs text-zinc-400 leading-relaxed">
            {question.rubric_text}
          </div>
        </details>
      )}

      {/* Teacher override form */}
      <form onSubmit={saveOverride} className="border-t border-zinc-800 pt-3">
        <div className={`${tw.label} mb-2`}>Teacher override</div>
        <div className="flex gap-2 items-start">
          <div className="flex flex-col gap-1 w-28">
            <input
              className={tw.input}
              type="number" min="0" max={maxPts} step="0.5"
              placeholder={`0–${maxPts}`}
              value={scoreInput}
              onChange={e => setScoreInput(e.target.value)}
            />
          </div>
          <textarea
            className={`${tw.input} flex-1 resize-none`} rows={1}
            placeholder="Override note (optional)"
            value={noteInput}
            onChange={e => setNoteInput(e.target.value)}
          />
          <div className="flex flex-col gap-1">
            <button className={tw.btnSmPrimary} type="submit" disabled={saving || !scoreInput}>
              {saving ? '…' : saved ? '✓' : 'Save'}
            </button>
            {(scoreInput || noteInput) && (
              <button className={tw.btnSm} type="button" onClick={clearOverride}>Clear</button>
            )}
          </div>
        </div>
        {/* Reference transcription — enables CER/WER computation */}
        {qtype === 'essay' && (
          <textarea
            className={`${tw.input} mt-2 resize-none text-xs`} rows={2}
            placeholder="Reference transcription (optional) — paste what was actually written to compute CER/WER"
            value={refInput}
            onChange={e => setRefInput(e.target.value)}
          />
        )}
        <ErrorBox msg={saveErr} />
        {answer.teacher_note && (
          <div className="mt-1 text-xs text-zinc-500 italic">Note: {answer.teacher_note}</div>
        )}
        {(answer.cer != null || answer.wer != null) && (
          <div className="mt-1 flex gap-3 text-xs text-zinc-500">
            {answer.cer != null && <span>CER: <span className="text-zinc-300 font-mono">{(answer.cer*100).toFixed(1)}%</span></span>}
            {answer.wer != null && <span>WER: <span className="text-zinc-300 font-mono">{(answer.wer*100).toFixed(1)}%</span></span>}
          </div>
        )}
      </form>

      {/* Flag controls */}
      <FlagBadge
        flag={flag}
        answerId={answer.id}
        submissionId={answer.submission_id}
        onFlagChange={onFlagChange}
      />
    </div>
  )
}

export default function ResultsPage() {
  const [exams, setExams]               = useState([])
  const [selectedExam, setSelectedExam] = useState(null)
  const [submissions, setSubmissions]   = useState([])
  const [selectedSub, setSelectedSub]   = useState(null)
  const [answers, setAnswers]           = useState([])
  const [questions, setQuestions]       = useState([])
  const [flags, setFlags]               = useState({})   // answerId → FlagLog | null
  const [flagStats, setFlagStats]       = useState(null)
  const [grading, setGrading]           = useState(false)
  const [gradeErr, setGradeErr]         = useState('')

  useEffect(() => { api.exams.list().then(setExams).catch(() => {}) }, [])

  async function selectExam(exam) {
    setSelectedExam(exam); setSelectedSub(null); setAnswers([]); setQuestions([])
    setFlags({}); setFlagStats(null)
    try { setSubmissions(await api.exams.submissions(exam.id)) } catch { setSubmissions([]) }
    try { setQuestions(await api.exams.questions.list(exam.id)) } catch {}
    try { setFlagStats(await api.exams.flagStats(exam.id)) } catch {}
  }

  async function selectSub(sub) {
    setGradeErr('')
    setSelectedSub(sub)
    try {
      const [ans, flagList] = await Promise.all([
        api.submissions.answers(sub.id),
        api.submissions.flags(sub.id),
      ])
      setAnswers(ans)
      const flagMap = {}
      flagList.forEach(f => { flagMap[f.submission_answer_id] = f })
      setFlags(flagMap)
    } catch { setAnswers([]); setFlags({}) }
    if (!selectedExam) return
    if (questions.length === 0) {
      try {
        const exam = await api.exams.list().then(list => list.find(e => e.id === sub.exam_id))
        if (exam) setQuestions(await api.exams.questions.list(exam.id))
      } catch {}
    }
  }

  function handleFlagChange(answerId, updatedFlag) {
    setFlags(prev => ({ ...prev, [answerId]: updatedFlag }))
    // Refresh flagstats asynchronously
    if (selectedExam) {
      api.exams.flagStats(selectedExam.id).then(setFlagStats).catch(() => {})
    }
  }

  async function runGrading() {
    if (!selectedSub) return
    setGrading(true); setGradeErr('')
    try {
      const updated = await api.submissions.grade(selectedSub.id)
      setAnswers(updated)
      // Refresh flags and flag stats after grading creates auto-flags
      const [flagList, stats] = await Promise.all([
        api.submissions.flags(selectedSub.id),
        selectedExam ? api.exams.flagStats(selectedExam.id) : Promise.resolve(null),
      ])
      const flagMap = {}
      flagList.forEach(f => { flagMap[f.submission_answer_id] = f })
      setFlags(flagMap)
      if (stats) setFlagStats(stats)
      setSubmissions(await api.exams.submissions(selectedExam.id))
      const sub = submissions.find(s => s.id === selectedSub.id)
      if (sub) setSelectedSub({ ...sub, status: 'graded' })
    } catch (err) { setGradeErr(err.message) }
    setGrading(false)
  }

  function handleOverrideSaved(updated) {
    setAnswers(prev => prev.map(a => a.id === updated.id ? updated : a))
  }

  // Map question_id → question object
  const qMap = Object.fromEntries(questions.map(q => [q.id, q]))

  // Score totals
  const totalMax      = questions.reduce((s, q) => s + q.max_points, 0)
  const totalAi       = answers.reduce((s, a) => s + (a.ai_score ?? 0), 0)
  const totalFinal    = answers.reduce((s, a) => s + (a.teacher_score ?? a.ai_score ?? 0), 0)
  const hasAnyGrading = answers.some(a => a.ai_score != null)
  const hasOverrides  = answers.some(a => a.teacher_score != null)

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      {/* Left panel — exam + submission selector */}
      <div className="flex flex-col gap-4">
        <h2 className={tw.heading}>Results</h2>

        <div className="flex flex-col gap-2">
          <div className={tw.label}>Select exam</div>
          {exams.length === 0
            ? <Empty text="No exams yet." />
            : exams.map(ex => (
              <button key={ex.id} type="button"
                className={selectedExam?.id === ex.id ? tw.rowActive : tw.row}
                onClick={() => selectExam(ex)}>
                <div className="text-sm text-zinc-100">{ex.title}</div>
                <span className="text-xs text-zinc-500">{ex.exam_code}</span>
              </button>
            ))
          }
        </div>

        {selectedExam && (
          <button className={tw.btnSm}
            onClick={() => {
              const a = document.createElement('a')
              a.href = api.exams.gradesCsvUrl(selectedExam.id)
              a.download = `grades_${selectedExam.exam_code}.csv`
              document.body.appendChild(a); a.click(); a.remove()
            }}>
            Download grade sheet (CSV)
          </button>
        )}

        {selectedExam && (
          <div className="flex flex-col gap-2">
            <div className={tw.label}>Submissions ({submissions.length})</div>
            {submissions.length === 0
              ? <Empty text="No submissions yet." />
              : submissions.map(s => (
                <button key={s.id} type="button"
                  className={selectedSub?.id === s.id ? tw.rowActive : tw.row}
                  onClick={() => selectSub(s)}>
                  <div>
                    <div className="text-sm text-zinc-100">{s.student_name}</div>
                    <div className={tw.muted}>{s.student_id}</div>
                  </div>
                  <span className={tw.badge(s.status)}>{s.status}</span>
                </button>
              ))
            }
          </div>
        )}
      </div>

      {/* Right panel — results detail */}
      <div className="lg:col-span-2 flex flex-col gap-4">
        {!selectedSub
          ? <div className="flex h-40 items-center justify-center rounded-xl border border-dashed border-zinc-700">
              <span className={tw.muted}>Select a submission to view results</span>
            </div>
          : <>
            {/* Summary header */}
            <div className={tw.card}>
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className={tw.heading}>{selectedSub.student_name}</div>
                  <div className={tw.muted}>{selectedSub.student_id} · {selectedExam?.title}</div>
                  <div className="mt-1">
                    <span className={tw.badge(selectedSub.status)}>{selectedSub.status}</span>
                  </div>
                </div>

                {hasAnyGrading && (
                  <div className="text-right">
                    <div className="text-2xl font-bold text-zinc-100 tabular-nums">
                      {totalFinal.toFixed(1)}
                      <span className="text-sm font-normal text-zinc-500"> / {totalMax}</span>
                    </div>
                    {hasOverrides && (
                      <div className="text-xs text-zinc-500">
                        AI: {totalAi.toFixed(1)} · Adjusted: {totalFinal.toFixed(1)}
                      </div>
                    )}
                    <div className="text-xs text-zinc-500 mt-0.5">
                      {((totalFinal / totalMax) * 100).toFixed(0)}%
                    </div>
                  </div>
                )}
              </div>

              {/* Overall score bar */}
              {hasAnyGrading && totalMax > 0 && (
                <div className="mt-3">
                  <ScoreBar score={totalFinal} max={totalMax} color={hasOverrides ? 'violet' : 'emerald'} />
                </div>
              )}

              {/* Grade button if not yet graded */}
              {selectedSub.status !== 'graded' && (
                <div className="mt-3 flex items-center gap-3">
                  <button className={tw.btnSmPrimary} onClick={runGrading}
                    disabled={grading || selectedSub.status === 'draft'}>
                    {grading ? 'Grading…' : 'Run AI grading'}
                  </button>
                  {selectedSub.status === 'draft' && (
                    <span className={tw.muted}>Upload + process the paper first</span>
                  )}
                  {selectedSub.status === 'submitted' && (
                    <span className={tw.muted}>OCR not run yet — process in Submissions tab</span>
                  )}
                </div>
              )}
              <ErrorBox msg={gradeErr} />
            </div>

            {/* Processed paper viewer */}
            {selectedSub.status !== 'draft' && (
              <ProcessedPaperPanel
                submissionId={selectedSub.id}
                answers={answers}
                hasPaper={!!selectedExam?.template_spec_json}
              />
            )}

            {/* Per-question answer cards */}
            {answers.length === 0
              ? <Empty text="No OCR results yet. Process the paper in the Submissions tab first." />
              : answers.map(ans => (
                <AnswerCard
                  key={ans.id}
                  answer={ans}
                  question={ans.question_id ? qMap[ans.question_id] : null}
                  flag={flags[ans.id] ?? null}
                  onOverrideSaved={handleOverrideSaved}
                  onFlagChange={handleFlagChange}
                />
              ))
            }
          </>
        }
      </div>

      {/* Flag stats panel — shown when an exam is selected */}
      {flagStats && (
        <div className="lg:col-span-3">
          <div className={tw.card}>
            <div className="flex items-center justify-between mb-3">
              <div className={tw.label}>RQ4 Flag Statistics — {flagStats.exam_code}</div>
              <button className={tw.btnSm}
                onClick={() => selectedExam && api.exams.flagStats(selectedExam.id).then(setFlagStats).catch(() => {})}>
                Refresh
              </button>
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8 text-center">
              {[
                ['Total graded', flagStats.total_answers, 'text-zinc-300'],
                ['Flagged', flagStats.total_flagged, 'text-amber-300'],
                ['Reviewed', flagStats.reviewed_count, 'text-zinc-300'],
                ['TP', flagStats.true_positives, 'text-emerald-400'],
                ['FP', flagStats.false_positives, 'text-red-400'],
                ['FN', flagStats.false_negatives, 'text-orange-400'],
                ['TN', flagStats.true_negatives, 'text-sky-400'],
              ].map(([label, val, color]) => (
                <div key={label} className="rounded-lg bg-zinc-800/50 px-2 py-2">
                  <div className={`text-lg font-bold tabular-nums ${color}`}>{val}</div>
                  <div className="text-xs text-zinc-500 mt-0.5">{label}</div>
                </div>
              ))}
              <div className="rounded-lg bg-zinc-800/50 px-2 py-2 col-span-2 sm:col-span-1">
                <div className="text-xs text-zinc-500 mb-1">Precision</div>
                <div className="text-base font-bold text-violet-400 tabular-nums">
                  {flagStats.precision != null ? `${(flagStats.precision * 100).toFixed(1)}%` : '—'}
                </div>
                <div className="text-xs text-zinc-500 mt-1">Recall</div>
                <div className="text-base font-bold text-violet-400 tabular-nums">
                  {flagStats.recall != null ? `${(flagStats.recall * 100).toFixed(1)}%` : '—'}
                </div>
              </div>
            </div>
            <div className="mt-2 text-xs text-zinc-600">
              Precision = TP/(TP+FP) · Recall = TP/(TP+FN) · FN estimated from unchecked overrides
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
