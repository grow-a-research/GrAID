import { useEffect, useState } from 'react'
import { api } from '../api'
import { tw, Empty } from '../ui'

// ── Mini score bar ─────────────────────────────────────────────────────────────
function Bar({ value, max, color = 'emerald' }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
  const cls = color === 'violet' ? 'bg-violet-500' : color === 'amber' ? 'bg-amber-500' : 'bg-emerald-500'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-zinc-800">
        <div className={`h-1.5 rounded-full ${cls} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-zinc-400 tabular-nums w-12 text-right">
        {value != null ? value.toFixed(1) : '—'}
      </span>
    </div>
  )
}

// ── Stat chip ─────────────────────────────────────────────────────────────────
function Chip({ label, value, sub }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 px-4 py-3 flex flex-col gap-0.5">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className="text-xl font-bold text-zinc-100 tabular-nums">{value ?? '—'}</div>
      {sub && <div className="text-xs text-zinc-500">{sub}</div>}
    </div>
  )
}

// ── Class overview section ────────────────────────────────────────────────────
function ClassOverview() {
  const [classes, setClasses] = useState([])
  const [selected, setSelected] = useState(null)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => { api.classes.list().then(setClasses).catch(() => {}) }, [])

  async function load(cls) {
    setSelected(cls); setData(null); setLoading(true)
    try { setData(await api.classes.analytics(cls.id)) } catch {}
    setLoading(false)
  }

  return (
    <div className="flex flex-col gap-4">
      <div className={tw.label}>Class overview</div>

      <div className="flex gap-2 flex-wrap">
        {classes.map(c => (
          <button key={c.id} type="button"
            className={selected?.id === c.id ? tw.btnSmPrimary : tw.btnSm}
            onClick={() => load(c)}>
            {c.code}
          </button>
        ))}
        {classes.length === 0 && <span className={tw.muted}>No classes yet.</span>}
      </div>

      {loading && <div className={tw.muted}>Loading…</div>}

      {data && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Chip label="Class" value={data.class_code} sub={data.class_name} />
            <Chip label="Students" value={data.student_count} />
            <Chip label="Exams" value={data.exams.length} />
            <Chip label="Graded exams"
              value={data.exams.filter(e => e.graded_count > 0).length}
              sub={`of ${data.exams.length}`} />
          </div>

          {data.exams.length === 0
            ? <Empty text="No exams for this class yet." />
            : data.exams.map(ex => (
              <div key={ex.exam_id} className={tw.card}>
                <div className="flex items-start justify-between gap-4 mb-3">
                  <div>
                    <div className="text-sm font-semibold text-zinc-100">{ex.title}</div>
                    <div className={tw.muted}>{ex.exam_code} · {ex.graded_count}/{ex.submission_count} graded</div>
                  </div>
                  {ex.avg_pct != null && (
                    <div className="text-right shrink-0">
                      <div className="text-lg font-bold text-zinc-100">{ex.avg_pct}%</div>
                      <div className="text-xs text-zinc-500">avg · {ex.pass_count}P {ex.fail_count}F</div>
                    </div>
                  )}
                </div>

                {ex.avg_total != null && (
                  <Bar value={ex.avg_total} max={ex.max_possible}
                    color={ex.avg_pct >= 75 ? 'emerald' : ex.avg_pct >= 60 ? 'amber' : 'violet'} />
                )}

                {/* Per-question breakdown */}
                {ex.questions.length > 0 && (
                  <div className="mt-3 border-t border-zinc-800 pt-3 flex flex-col gap-2">
                    {ex.questions.map(q => (
                      <div key={q.question_id}>
                        <div className="flex justify-between text-xs text-zinc-400 mb-0.5">
                          <span className="truncate max-w-[70%]">Q{q.order_index}. {q.prompt}</span>
                          <span className="tabular-nums shrink-0 ml-2">
                            {q.avg_score != null ? `${q.avg_score} / ${q.max_points}` : 'no data'}
                            {q.answer_count > 0 && <span className="text-zinc-600 ml-1">({q.answer_count})</span>}
                          </span>
                        </div>
                        {q.avg_score != null && (
                          <Bar value={q.avg_score} max={q.max_points} />
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))
          }
        </>
      )}
    </div>
  )
}

// ── Student tracker section ───────────────────────────────────────────────────
function StudentTracker() {
  const [students, setStudents] = useState([])
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState(null)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => { api.students.list().then(setStudents).catch(() => {}) }, [])

  async function load(s) {
    setSelected(s); setData(null); setLoading(true)
    try { setData(await api.students.analytics(s.student_id)) } catch {}
    setLoading(false)
  }

  const filtered = search.trim()
    ? students.filter(s =>
        s.student_id.toLowerCase().includes(search.toLowerCase()) ||
        s.full_name.toLowerCase().includes(search.toLowerCase()))
    : students

  return (
    <div className="flex flex-col gap-4">
      <div className={tw.label}>Student tracker</div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Student list */}
        <div className="flex flex-col gap-2">
          <input className={tw.input} placeholder="Search students…"
            value={search} onChange={e => setSearch(e.target.value)} />
          <div className="flex flex-col gap-1 max-h-80 overflow-y-auto">
            {filtered.map(s => (
              <button key={s.id} type="button"
                className={selected?.id === s.id ? tw.rowActive : tw.row}
                onClick={() => load(s)}>
                <div className="text-sm text-zinc-100">{s.full_name}</div>
                <span className="text-xs text-zinc-500">{s.student_id}</span>
              </button>
            ))}
            {filtered.length === 0 && <Empty text="No students." />}
          </div>
        </div>

        {/* Student results */}
        <div className="lg:col-span-2 flex flex-col gap-3">
          {loading && <div className={tw.muted}>Loading…</div>}
          {!loading && !data && (
            <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-zinc-700">
              <span className={tw.muted}>Select a student</span>
            </div>
          )}
          {data && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <Chip label="Student" value={data.student_id} sub={data.full_name} />
                <Chip label="Submissions" value={data.submissions.length}
                  sub={`${data.submissions.filter(s => s.status === 'graded').length} graded`} />
              </div>

              {data.submissions.length === 0
                ? <Empty text="No submissions yet." />
                : data.submissions.map(sub => (
                  <div key={sub.submission_id} className={tw.card}>
                    <div className="flex items-start justify-between gap-3 mb-2">
                      <div>
                        <div className="text-sm font-medium text-zinc-100">{sub.exam_title}</div>
                        <div className={tw.muted}>{sub.class_code} · {sub.exam_code}</div>
                      </div>
                      <div className="text-right shrink-0">
                        {sub.total_score != null
                          ? <>
                              <div className="text-lg font-bold text-zinc-100 tabular-nums">
                                {sub.total_score}
                                <span className="text-sm font-normal text-zinc-500">/{sub.max_possible}</span>
                              </div>
                              <div className="text-xs text-zinc-500">{sub.pct}%</div>
                            </>
                          : <span className={tw.badge(sub.status)}>{sub.status}</span>
                        }
                      </div>
                    </div>
                    {sub.total_score != null && sub.max_possible > 0 && (
                      <Bar value={sub.total_score} max={sub.max_possible}
                        color={sub.pct >= 75 ? 'emerald' : sub.pct >= 60 ? 'amber' : 'violet'} />
                    )}
                  </div>
                ))
              }

              <AiInsightPanel
                key={data.student_id}
                onAnalyze={() => api.students.analyze(data.student_id).then(r => r.analysis)}
              />
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ── AI insight panel (shared) ─────────────────────────────────────────────────
function AiInsightPanel({ onAnalyze }) {
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  async function run() {
    setLoading(true); setErr(''); setText('')
    try { setText(await onAnalyze()) }
    catch (e) { setErr(e.message) }
    setLoading(false)
  }

  return (
    <div className="rounded-xl border border-violet-800/40 bg-violet-950/20 p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-violet-300">AI Analysis</div>
          <div className="text-xs text-zinc-500">Powered by Groq — requires GROQ_API_KEY</div>
        </div>
        <button type="button"
          className="rounded-md px-3 py-1.5 text-sm bg-violet-700 hover:bg-violet-600 text-white transition disabled:opacity-50"
          onClick={run} disabled={loading}>
          {loading ? 'Analyzing…' : text ? 'Re-analyze' : 'Analyze with AI'}
        </button>
      </div>
      {err && <div className="text-xs text-red-400">{err}</div>}
      {text && (
        <div className="text-sm text-zinc-300 leading-relaxed whitespace-pre-wrap border-t border-violet-800/30 pt-3">
          {text}
        </div>
      )}
    </div>
  )
}

// ── Exam breakdown section ────────────────────────────────────────────────────
function ExamBreakdown() {
  const [exams, setExams] = useState([])
  const [selected, setSelected] = useState(null)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => { api.exams.list().then(setExams).catch(() => {}) }, [])

  async function load(ex) {
    setSelected(ex); setData(null); setLoading(true)
    try { setData(await api.exams.analytics(ex.id)) } catch {}
    setLoading(false)
  }

  return (
    <div className="flex flex-col gap-4">
      <div className={tw.label}>Exam breakdown</div>

      <div className="flex gap-2 flex-wrap">
        {exams.map(ex => (
          <button key={ex.id} type="button"
            className={selected?.id === ex.id ? tw.btnSmPrimary : tw.btnSm}
            onClick={() => load(ex)}>
            {ex.exam_code}
          </button>
        ))}
        {exams.length === 0 && <span className={tw.muted}>No exams yet.</span>}
      </div>

      {loading && <div className={tw.muted}>Loading…</div>}

      {data && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Chip label="Exam" value={data.exam_code} sub={data.title} />
            <Chip label="Submissions" value={data.submission_count} sub={`${data.graded_count} graded`} />
            <Chip label="Avg score"
              value={data.avg_total != null ? `${data.avg_total} / ${data.max_possible}` : '—'} />
            <Chip label="Pass / Fail"
              value={data.graded_count > 0 ? `${data.pass_count} / ${data.fail_count}` : '—'}
              sub="≥ 60% to pass" />
          </div>

          {data.avg_total != null && (
            <Bar value={data.avg_total} max={data.max_possible}
              color={data.avg_pct >= 75 ? 'emerald' : data.avg_pct >= 60 ? 'amber' : 'violet'} />
          )}

          <div className={tw.label}>Per-question averages</div>
          {data.questions.length === 0
            ? <Empty text="No questions or no graded answers yet." />
            : data.questions.map(q => (
              <div key={q.question_id} className={tw.card}>
                <div className="flex justify-between items-start gap-3 mb-2">
                  <div className="flex-1">
                    <div className="text-xs font-semibold text-zinc-400">Q{q.order_index}</div>
                    <div className="text-sm text-zinc-200">{q.prompt}</div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-base font-bold text-zinc-100 tabular-nums">
                      {q.avg_score ?? '—'}
                      <span className="text-xs font-normal text-zinc-500"> / {q.max_points}</span>
                    </div>
                    {q.answer_count > 0 && (
                      <div className="text-xs text-zinc-500">
                        min {q.min_score} · max {q.max_score} · n={q.answer_count}
                      </div>
                    )}
                  </div>
                </div>
                {q.avg_score != null && (
                  <Bar value={q.avg_score} max={q.max_points} />
                )}
              </div>
            ))
          }

          <AiInsightPanel
            key={data.exam_id}
            onAnalyze={() => api.exams.analyze(data.exam_id).then(r => r.analysis)}
          />
        </>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function AnalyticsPage() {
  const [section, setSection] = useState('class')

  const sections = [
    { id: 'class',   label: 'Class overview' },
    { id: 'exam',    label: 'Exam breakdown' },
    { id: 'student', label: 'Student tracker' },
  ]

  return (
    <div className="flex flex-col gap-6">
      {/* Section tabs */}
      <div className="flex gap-2 border-b border-zinc-800 pb-3">
        {sections.map(s => (
          <button key={s.id} type="button"
            onClick={() => setSection(s.id)}
            className={[
              'rounded-md px-3 py-1.5 text-sm transition',
              section === s.id
                ? 'bg-zinc-700 text-zinc-100'
                : 'text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800',
            ].join(' ')}>
            {s.label}
          </button>
        ))}
      </div>

      {section === 'class'   && <ClassOverview />}
      {section === 'exam'    && <ExamBreakdown />}
      {section === 'student' && <StudentTracker />}
    </div>
  )
}
