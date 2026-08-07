import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { tw, ErrorBox, Empty } from '../ui'
import { useWorkflow } from '../context/WorkflowContext'

// Shown as a concrete example of a well-structured rubric — weighted criteria
// grade more consistently through the AI grader than a single vague paragraph.
const EXAMPLE_RUBRIC =
  'Thesis clarity (3 pts): states a clear main argument. ' +
  'Supporting evidence (4 pts): uses at least two specific examples from the text. ' +
  'Grammar and organization (3 pts): logically structured paragraphs with minimal errors.'

function csvCell(value) {
  return `"${String(value).replace(/"/g, '""')}"`
}

function downloadCsv(filename, rows) {
  const csv = rows.map(row => row.join(',')).join('\n') + '\n'
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename
  document.body.appendChild(a); a.click(); a.remove()
  URL.revokeObjectURL(url)
}

function downloadQuestionsCsvTemplate() {
  downloadCsv('questions_template.csv', [
    ['prompt', 'question_type', 'rubric_text', 'max_points', 'choices', 'correct_answer'],
    [
      csvCell('Explain how photosynthesis converts sunlight into chemical energy.'),
      'essay', csvCell(EXAMPLE_RUBRIC), '10', '', '',
    ],
    [csvCell('What is the capital of France?'), 'identification', '', '5', '', 'Paris'],
    [csvCell('The mitochondria is the powerhouse of the cell.'), 'tf', '', '2', '', 'True'],
    [
      csvCell('Which gas do plants absorb during photosynthesis?'),
      'mcq', '', '2', csvCell('Oxygen|Carbon Dioxide|Nitrogen|Hydrogen'), 'B',
    ],
  ])
}

function downloadRubricsCsvTemplate() {
  downloadCsv('rubrics_template.csv', [
    ['order_index', 'rubric_text'],
    ['1', csvCell(EXAMPLE_RUBRIC)],
  ])
}

export default function ExamsPage() {
  const {
    selectedClass, selectClass,
    selectedExam: selected, selectExam: pickExam, updateSelectedExam: setSelected, clearWorkflow,
  } = useWorkflow()
  const [classes, setClasses] = useState([])
  const [exams, setExams] = useState([])
  const [questions, setQuestions] = useState([])

  // create exam form
  const [newClassId, setNewClassId] = useState('')
  const [newCode, setNewCode] = useState('')
  const [newTitle, setNewTitle] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [creating, setCreating] = useState(false)
  const [createErr, setCreateErr] = useState('')

  // add question form
  const [qPrompt, setQPrompt] = useState('')
  const [qPoints, setQPoints] = useState('10')
  const [qRubric, setQRubric] = useState('')
  const [qType, setQType] = useState('essay')          // essay | mcq | tf | identification
  const [qChoices, setQChoices] = useState(['', '', '', ''])  // MCQ choices A-D
  const [qCorrect, setQCorrect] = useState('')          // correct answer
  const [addingQ, setAddingQ] = useState(false)
  const [addQErr, setAddQErr] = useState('')

  // template
  const [genning, setGenning] = useState(false)
  const [genErr, setGenErr] = useState('')
  const [templateReady, setTemplateReady] = useState(false)

  // question CSV import
  const qCsvRef = useRef(null)
  const [qImporting, setQImporting] = useState(false)
  const [qImportResult, setQImportResult] = useState(null)

  // rubric CSV import
  const rubricCsvRef = useRef(null)
  const [rubricImporting, setRubricImporting] = useState(false)
  const [rubricImportResult, setRubricImportResult] = useState(null)
  const [clearingRubrics, setClearingRubrics] = useState(false)

  // exam duplication
  const [duplicating, setDuplicating] = useState(false)

  // advanced tools disclosure (duplicate exam, CSV import/export)
  const [advancedOpen, setAdvancedOpen] = useState(false)

  // inline question editing
  const [editingQId, setEditingQId] = useState(null)
  const [editQPrompt, setEditQPrompt] = useState('')
  const [editQType, setEditQType] = useState('essay')
  const [editQChoices, setEditQChoices] = useState(['', '', '', ''])
  const [editQCorrect, setEditQCorrect] = useState('')
  const [editQRubric, setEditQRubric] = useState('')
  const [editQPoints, setEditQPoints] = useState('10')
  const [savingQ, setSavingQ] = useState(false)
  const [saveQErr, setSaveQErr] = useState('')

  useEffect(() => { loadClasses(); loadExams(selectedClass?.id) }, [])

  // Loads question/template state for whichever exam is selected — runs on explicit
  // selection here, and also when arriving on this tab with an exam already picked
  // from Submissions/Results (shared WorkflowContext selection).
  useEffect(() => {
    setAddQErr(''); setGenErr(''); setAdvancedOpen(false)
    setQImportResult(null); setRubricImportResult(null)
    if (!selected) { setQuestions([]); setTemplateReady(false); return }
    setTemplateReady(!!selected.template_spec_json)
    api.exams.questions.list(selected.id)
      .then(setQuestions)
      .catch(() => setQuestions([]))
  }, [selected?.id])

  async function loadClasses() {
    try { setClasses(await api.classes.list()) } catch {}
  }
  async function loadExams(classId) {
    try { setExams(await api.exams.list(classId || undefined)) } catch {}
  }
  async function createExam(e) {
    e.preventDefault()
    if (!newClassId || !newCode.trim() || !newTitle.trim()) return
    setCreating(true); setCreateErr('')
    try {
      const exam = await api.exams.create({
        class_id: parseInt(newClassId),
        exam_code: newCode.trim(),
        title: newTitle.trim(),
        description: newDesc.trim() || undefined,
      })
      setExams(prev => [...prev, exam])
      setNewCode(''); setNewTitle(''); setNewDesc('')
    } catch (err) { setCreateErr(err.message) }
    setCreating(false)
  }
  async function addQuestion(e) {
    e.preventDefault()
    if (!selected || !qPrompt.trim()) return
    setAddingQ(true); setAddQErr('')
    try {
      const body = {
        order_index: questions.length + 1,
        prompt: qPrompt.trim(),
        max_points: parseFloat(qPoints) || 10,
        question_type: qType,
        rubric_text: qType === 'essay' ? qRubric.trim() : null,
        correct_answer: qCorrect.trim() || null,
        choices_json: qType === 'mcq'
          ? JSON.stringify(qChoices.map(c => c.trim()).filter(Boolean))
          : null,
      }
      const q = await api.exams.questions.add(selected.id, body)
      setQuestions(prev => [...prev, q])
      setQPrompt(''); setQPoints('10'); setQRubric('')
      setQCorrect(''); setQChoices(['', '', '', ''])
    } catch (err) { setAddQErr(err.message) }
    setAddingQ(false)
  }
  async function generateTemplate() {
    if (!selected) return
    setGenning(true); setGenErr('')
    try {
      const updated = await api.exams.generateTemplate(selected.id)
      setSelected(updated)
      setTemplateReady(true)
      // refresh question region_json
      setQuestions(await api.exams.questions.list(selected.id))
    } catch (err) { setGenErr(err.message) }
    setGenning(false)
  }
  function downloadTemplate() {
    if (!selected) return
    const url = api.exams.templatePdfUrl(selected.id)
    const a = document.createElement('a')
    a.href = url; a.download = `exam_${selected.exam_code}_template.pdf`
    document.body.appendChild(a); a.click(); a.remove()
  }
  function downloadQuestionnaire() {
    if (!selected) return
    const url = api.exams.questionnairePdfUrl(selected.id)
    const a = document.createElement('a')
    a.href = url; a.download = `exam_${selected.exam_code}_questionnaire.pdf`
    document.body.appendChild(a); a.click(); a.remove()
  }

  function downloadAllPapers() {
    if (!selected) return
    const url = api.exams.allPapersZipUrl(selected.id)
    const a = document.createElement('a')
    a.href = url; a.download = `${selected.exam_code}_papers.zip`
    document.body.appendChild(a); a.click(); a.remove()
  }

  async function importQuestionsCsv(e) {
    const file = e.target.files?.[0]
    if (!file || !selected) return
    setQImporting(true); setQImportResult(null)
    try {
      const result = await api.exams.questions.import(selected.id, file)
      setQImportResult(result)
      if (result.created > 0) setQuestions(await api.exams.questions.list(selected.id))
    } catch (err) { setQImportResult({ error: err.message }) }
    setQImporting(false)
    e.target.value = ''
  }

  async function importRubricsCsv(e) {
    const file = e.target.files?.[0]
    if (!file || !selected) return
    setRubricImporting(true); setRubricImportResult(null)
    try {
      const result = await api.exams.rubrics.import(selected.id, file)
      setRubricImportResult(result)
      if (result.updated > 0) setQuestions(await api.exams.questions.list(selected.id))
    } catch (err) { setRubricImportResult({ error: err.message }) }
    setRubricImporting(false)
    e.target.value = ''
  }

  async function clearRubrics() {
    if (!selected) return
    if (!window.confirm('Clear rubric text from ALL questions in this exam?')) return
    setClearingRubrics(true)
    try {
      await api.exams.rubrics.clear(selected.id)
      setQuestions(prev => prev.map(q => ({ ...q, rubric_text: null })))
    } catch (err) { alert(`Failed: ${err.message}`) }
    setClearingRubrics(false)
  }

  async function duplicateExam() {
    if (!selected) return
    setDuplicating(true)
    try {
      const copy = await api.exams.duplicate(selected.id)
      setExams(prev => [...prev, copy])
      alert(`Exam duplicated as "${copy.title}" (${copy.exam_code})`)
    } catch (err) { alert(`Duplicate failed: ${err.message}`) }
    setDuplicating(false)
  }

  function startEditQ(q) {
    let choices = ['', '', '', '']
    try { if (q.choices_json) choices = JSON.parse(q.choices_json).concat(['','','','']).slice(0, 4) } catch {}
    setEditingQId(q.id)
    setEditQPrompt(q.prompt)
    setEditQType(q.question_type || 'essay')
    setEditQChoices(choices)
    setEditQCorrect(q.correct_answer || '')
    setEditQRubric(q.rubric_text || '')
    setEditQPoints(String(q.max_points ?? 10))
    setSaveQErr('')
  }
  function cancelEditQ() {
    setEditingQId(null); setSaveQErr('')
  }
  async function saveEditQ(qId) {
    setSavingQ(true); setSaveQErr('')
    try {
      const body = {
        prompt: editQPrompt.trim() || undefined,
        question_type: editQType,
        rubric_text: editQType === 'essay' ? (editQRubric.trim() || null) : null,
        max_points: parseFloat(editQPoints) || undefined,
        choices_json: editQType === 'mcq'
          ? JSON.stringify(editQChoices.map(c => c.trim()).filter(Boolean))
          : null,
        correct_answer: editQCorrect.trim() || null,
      }
      const updated = await api.exams.questions.update(selected.id, qId, body)
      setQuestions(prev => prev.map(q => q.id === qId ? updated : q))
      // structural changes may invalidate template
      setSelected(prev => ({ ...prev, template_spec_json: updated.region_json === null ? null : prev.template_spec_json }))
      setEditingQId(null)
    } catch (err) { setSaveQErr(err.message) }
    setSavingQ(false)
  }
  async function deleteQuestion(q) {
    if (!window.confirm(`Delete question "${q.prompt.slice(0, 60)}"?\n\nThis will also invalidate the exam template.`)) return
    try {
      await api.exams.questions.delete(selected.id, q.id)
      setQuestions(prev => prev.filter(x => x.id !== q.id))
      setSelected(prev => ({ ...prev, template_spec_json: null }))
      setTemplateReady(false)
    } catch (err) { alert(`Delete failed: ${err.message}`) }
  }

  async function deleteExam(exam) {
    if (!window.confirm(`Delete exam "${exam.title}" (${exam.exam_code})?\n\nThis will also delete all questions, submissions, and uploaded scans. This cannot be undone.`)) return
    try {
      await api.exams.delete(exam.id)
      setExams(prev => prev.filter(e => e.id !== exam.id))
      if (selected?.id === exam.id) clearWorkflow()
    } catch (err) { alert(`Delete failed: ${err.message}`) }
  }

  const filteredExams = selectedClass
    ? exams.filter(ex => ex.class_id === selectedClass.id)
    : exams

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      {/* Left: exam list + create */}
      <div className="flex flex-col gap-4">
        <h2 className={tw.heading}>Exams</h2>

        <form onSubmit={createExam} className={`${tw.card} flex flex-col gap-3`}>
          <div className={tw.label}>New exam</div>
          <select className={tw.select} value={newClassId} onChange={e => setNewClassId(e.target.value)}>
            <option value="">Select class…</option>
            {classes.map(c => <option key={c.id} value={c.id}>{c.name} ({c.code})</option>)}
          </select>
          <input className={tw.input} placeholder="Exam code (e.g. MID1)"
            value={newCode} onChange={e => setNewCode(e.target.value)} />
          <input className={tw.input} placeholder="Title"
            value={newTitle} onChange={e => setNewTitle(e.target.value)} />
          <textarea className={tw.input} placeholder="Description (optional)" rows={2}
            value={newDesc} onChange={e => setNewDesc(e.target.value)} />
          <ErrorBox msg={createErr} />
          <button className={tw.btnPrimary} type="submit" disabled={creating}>
            {creating ? 'Creating…' : 'Create exam'}
          </button>
        </form>

        <div className="flex flex-col gap-2">
          <select className={tw.select} value={selectedClass?.id ?? ''}
            onChange={e => {
              const cls = classes.find(c => c.id === parseInt(e.target.value)) ?? null
              selectClass(cls)
              loadExams(cls?.id)
            }}>
            <option value="">All classes</option>
            {classes.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>

          {filteredExams.length === 0
            ? <Empty text="No exams yet." />
            : filteredExams.map(ex => (
              <div key={ex.id} className={`${selected?.id === ex.id ? tw.rowActive : tw.row} flex items-center gap-2`}>
                <button type="button" className="flex-1 text-left flex items-center justify-between gap-2"
                  onClick={() => pickExam(ex)}>
                  <div>
                    <div className="text-sm font-medium text-zinc-100">{ex.title}</div>
                    <div className={tw.muted}>{ex.exam_code}</div>
                  </div>
                  {ex.template_spec_json
                    ? <span className={tw.badge('ocr_done')}>template</span>
                    : <span className={tw.badge('draft')}>no template</span>
                  }
                </button>
                <button type="button" onClick={() => deleteExam(ex)}
                  className="text-xs text-zinc-600 hover:text-red-400 transition shrink-0 px-1">
                  ✕
                </button>
              </div>
            ))
          }
        </div>
      </div>

      {/* Right: exam detail */}
      <div className="lg:col-span-2 flex flex-col gap-4">
        {!selected
          ? <div className="flex h-40 items-center justify-center rounded-xl border border-dashed border-zinc-700">
              <span className={tw.muted}>Select an exam</span>
            </div>
          : <>
            <div className="flex items-center justify-between">
              <h2 className={tw.heading}>
                {selected.title}
                <span className="ml-2 text-sm font-normal text-zinc-400">({selected.exam_code})</span>
              </h2>
              <div className="flex gap-2 flex-wrap justify-end">
                <button className={tw.btnSmPrimary} onClick={generateTemplate} disabled={genning || questions.length === 0}>
                  {genning ? 'Generating…' : templateReady ? 'Re-generate PDF' : 'Generate PDF template'}
                </button>
                {templateReady && (
                  <button className={tw.btnSm} onClick={downloadTemplate}>
                    Download PDF
                  </button>
                )}
                {questions.length > 0 && (
                  <button className={tw.btnSm} onClick={downloadQuestionnaire}
                    title="Plain document listing question text — separate from the answer sheet, safe to hand out or read from">
                    Download questionnaire
                  </button>
                )}
                {templateReady && (
                  <button className={tw.btnSm} onClick={downloadAllPapers}
                    title="Generates a personalised PDF for every enrolled student and downloads as a ZIP">
                    Download all papers (ZIP)
                  </button>
                )}
                <button type="button" className={tw.btnSm} onClick={() => setAdvancedOpen(o => !o)}>
                  {advancedOpen ? 'Hide advanced tools' : 'Advanced tools ▾'}
                </button>
              </div>
            </div>
            {selected.description && <p className={tw.muted}>{selected.description}</p>}
            <ErrorBox msg={genErr} />
            {templateReady && (
              <div className="rounded-lg border border-emerald-900/40 bg-emerald-950/20 px-3 py-2 text-xs text-emerald-300">
                Template generated — answer regions stored for Phase 5 OCR alignment.
              </div>
            )}
            {!templateReady && questions.length > 0 && (
              <div className="rounded-lg border border-amber-900/40 bg-amber-950/20 px-3 py-2 text-xs text-amber-300">
                Template outdated — questions were added, edited, or deleted. Re-generate the PDF template before printing or scanning.
              </div>
            )}

            {/* Advanced tools: duplicate exam, bulk CSV import/export — collapsed by default */}
            {advancedOpen && (
              <div className={`${tw.card} flex flex-col gap-3`}>
                <div className={tw.label}>Advanced tools</div>

                <button className={tw.btnSm} onClick={duplicateExam} disabled={duplicating}
                  title="Clone this exam (questions + rubrics) as a new draft"
                  style={{ alignSelf: 'flex-start' }}>
                  {duplicating ? 'Duplicating…' : 'Duplicate exam'}
                </button>

                {/* Bulk import questions */}
                <div className="flex flex-col gap-2 border-t border-zinc-800 pt-3">
                  <div className={tw.label}>Bulk import questions (CSV)</div>
                  <p className="text-xs text-zinc-500 leading-relaxed">
                    Columns: <span className="font-mono text-zinc-400">prompt</span> (optional — auto-numbered if left blank),{' '}
                    <span className="font-mono text-zinc-400">question_type</span> (<span className="font-mono">essay</span> / <span className="font-mono">mcq</span> / <span className="font-mono">tf</span> / <span className="font-mono">identification</span>, defaults to essay),{' '}
                    <span className="font-mono text-zinc-400">rubric_text</span> (required for essay),{' '}
                    <span className="font-mono text-zinc-400">max_points</span>,{' '}
                    <span className="font-mono text-zinc-400">choices</span> (MCQ only — pipe-separated, e.g. <span className="font-mono">Oxygen|Carbon Dioxide|Nitrogen|Hydrogen</span>; order maps to A/B/C/D),{' '}
                    <span className="font-mono text-zinc-400">correct_answer</span> (required for mcq/tf/identification — a letter for MCQ, "True"/"False" for T-F, the expected text for Identification).
                    {' '}Download the template below to see a filled example of each type.
                  </p>
                  <div className="flex gap-2 flex-wrap">
                    <button type="button" className={tw.btnSm} onClick={downloadQuestionsCsvTemplate}>
                      Download template
                    </button>
                    <label className={`${tw.btnSm} cursor-pointer`}>
                      {qImporting ? 'Importing…' : 'Upload CSV'}
                      <input ref={qCsvRef} type="file" accept=".csv,text/csv" className="hidden"
                        onChange={importQuestionsCsv} disabled={qImporting} />
                    </label>
                  </div>
                  {qImportResult && !qImportResult.error && (
                    <div className="text-xs text-emerald-400">
                      {qImportResult.created} question(s) imported
                      {qImportResult.errors?.length > 0 && (
                        <div className="text-red-400 mt-0.5">{qImportResult.errors.join(' · ')}</div>
                      )}
                    </div>
                  )}
                  {qImportResult?.error && (
                    <div className="text-xs text-red-400">{qImportResult.error}</div>
                  )}
                </div>

                {/* Bulk update rubrics */}
                <div className="flex flex-col gap-2 border-t border-zinc-800 pt-3">
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <div className={tw.label}>Bulk update rubrics (CSV)</div>
                    {questions.some(q => q.rubric_text) && (
                      <button className={tw.btnSm} onClick={clearRubrics} disabled={clearingRubrics}
                        title="Remove rubric text from all questions">
                        {clearingRubrics ? 'Clearing…' : 'Clear rubrics'}
                      </button>
                    )}
                  </div>
                  <p className="text-xs text-zinc-500 leading-relaxed">
                    Columns: <span className="font-mono text-zinc-400">order_index</span>,{' '}
                    <span className="font-mono text-zinc-400">rubric_text</span>. Matches existing
                    essay questions by their number and replaces the rubric — does not create new
                    questions. Download the template for an example of a well-structured rubric
                    (weighted criteria grade more consistently than a vague paragraph).
                  </p>
                  <div className="flex gap-2 flex-wrap">
                    <button type="button" className={tw.btnSm} onClick={downloadRubricsCsvTemplate}>
                      Download template
                    </button>
                    <label className={`${tw.btnSm} cursor-pointer`}>
                      {rubricImporting ? 'Updating…' : 'Upload CSV'}
                      <input ref={rubricCsvRef} type="file" accept=".csv,text/csv" className="hidden"
                        onChange={importRubricsCsv} disabled={rubricImporting} />
                    </label>
                  </div>
                  {rubricImportResult && !rubricImportResult.error && (
                    <div className="text-xs text-emerald-400">
                      {rubricImportResult.updated} rubric(s) updated
                      {rubricImportResult.errors?.length > 0 && (
                        <div className="text-red-400 mt-0.5">{rubricImportResult.errors.join(' · ')}</div>
                      )}
                    </div>
                  )}
                  {rubricImportResult?.error && (
                    <div className="text-xs text-red-400">{rubricImportResult.error}</div>
                  )}
                </div>
              </div>
            )}

            {/* Questions */}
            <div className={tw.label}>Questions ({questions.length})</div>

            <form onSubmit={addQuestion} className={`${tw.card} flex flex-col gap-3`}>
              <div className={tw.label}>Add question</div>

              {/* Question type selector */}
              <div className="flex gap-2 flex-wrap">
                {[['essay','Essay'],['mcq','MCQ'],['tf','True / False'],['identification','Identification']].map(([val, label]) => (
                  <button key={val} type="button"
                    onClick={() => { setQType(val); setQCorrect(''); setQChoices(['','','','']) }}
                    className={[
                      'rounded px-3 py-1 text-xs transition',
                      qType === val
                        ? 'bg-emerald-700 text-white'
                        : 'bg-zinc-800 text-zinc-400 hover:text-zinc-100',
                    ].join(' ')}>
                    {label}
                  </button>
                ))}
              </div>

              <textarea className={tw.input} placeholder="Question prompt *" rows={2}
                value={qPrompt} onChange={e => setQPrompt(e.target.value)} required />

              {/* Essay: rubric */}
              {qType === 'essay' && (
                <textarea className={tw.input} rows={3}
                  placeholder={`Rubric / marking criteria * — write it as weighted criteria, e.g.:\n${EXAMPLE_RUBRIC}`}
                  value={qRubric} onChange={e => setQRubric(e.target.value)} />
              )}

              {/* MCQ: four choices + correct answer letter */}
              {qType === 'mcq' && (
                <>
                  {['A','B','C','D'].map((lbl, i) => (
                    <div key={lbl} className="flex items-center gap-2">
                      <span className="text-xs text-zinc-400 w-4">{lbl}</span>
                      <input className={tw.input} placeholder={`Choice ${lbl}`}
                        value={qChoices[i]}
                        onChange={e => setQChoices(prev => prev.map((c, idx) => idx === i ? e.target.value : c))} />
                    </div>
                  ))}
                  <select className={tw.select} value={qCorrect}
                    onChange={e => setQCorrect(e.target.value)}>
                    <option value="">Correct answer…</option>
                    {['A','B','C','D'].map(l => <option key={l} value={l}>{l}</option>)}
                  </select>
                </>
              )}

              {/* T/F: correct answer */}
              {qType === 'tf' && (
                <select className={tw.select} value={qCorrect}
                  onChange={e => setQCorrect(e.target.value)}>
                  <option value="">Correct answer…</option>
                  <option value="True">True</option>
                  <option value="False">False</option>
                </select>
              )}

              {/* Identification: expected answer */}
              {qType === 'identification' && (
                <input className={tw.input} placeholder="Expected answer (used for auto-scoring)"
                  value={qCorrect} onChange={e => setQCorrect(e.target.value)} />
              )}

              <input className={tw.input} placeholder="Max points" type="number" min="0" step="0.5"
                value={qPoints} onChange={e => setQPoints(e.target.value)} />
              <ErrorBox msg={addQErr} />
              <button className={tw.btnPrimary} type="submit"
                disabled={addingQ || !qPrompt.trim() || (qType === 'essay' && !qRubric.trim())}>
                {addingQ ? 'Adding…' : 'Add question'}
              </button>
            </form>

            {questions.length === 0
              ? <Empty text="No questions yet. Add one above." />
              : <div className="flex flex-col gap-2">
                  {questions.map(q => {
                    const typeLabel = {essay:'Essay',mcq:'MCQ',tf:'T/F',identification:'ID'}[q.question_type] ?? q.question_type
                    const typeColor = {essay:'text-zinc-500',mcq:'text-violet-400',tf:'text-amber-400',identification:'text-sky-400'}[q.question_type] ?? 'text-zinc-500'
                    let choices = []
                    try { choices = q.choices_json ? JSON.parse(q.choices_json) : [] } catch {}

                    if (editingQId === q.id) {
                      // ── Inline edit form ──────────────────────────────────────
                      return (
                        <div key={q.id} className={`${tw.card} flex flex-col gap-3 border border-emerald-800/50`}>
                          <div className={tw.label}>Edit Q{q.order_index}</div>

                          {/* Type selector */}
                          <div className="flex gap-2 flex-wrap">
                            {[['essay','Essay'],['mcq','MCQ'],['tf','True / False'],['identification','Identification']].map(([val, lbl]) => (
                              <button key={val} type="button"
                                onClick={() => { setEditQType(val); setEditQCorrect(''); setEditQChoices(['','','','']) }}
                                className={[
                                  'rounded px-3 py-1 text-xs transition',
                                  editQType === val
                                    ? 'bg-emerald-700 text-white'
                                    : 'bg-zinc-800 text-zinc-400 hover:text-zinc-100',
                                ].join(' ')}>
                                {lbl}
                              </button>
                            ))}
                          </div>

                          <textarea className={tw.input} placeholder="Question prompt *" rows={2}
                            value={editQPrompt} onChange={e => setEditQPrompt(e.target.value)} />

                          {editQType === 'essay' && (
                            <textarea className={tw.input} rows={3}
                              placeholder={`Rubric / marking criteria — write it as weighted criteria, e.g.:\n${EXAMPLE_RUBRIC}`}
                              value={editQRubric} onChange={e => setEditQRubric(e.target.value)} />
                          )}

                          {editQType === 'mcq' && (
                            <>
                              {['A','B','C','D'].map((lbl, i) => (
                                <div key={lbl} className="flex items-center gap-2">
                                  <span className="text-xs text-zinc-400 w-4">{lbl}</span>
                                  <input className={tw.input} placeholder={`Choice ${lbl}`}
                                    value={editQChoices[i]}
                                    onChange={e => setEditQChoices(prev => prev.map((c, idx) => idx === i ? e.target.value : c))} />
                                </div>
                              ))}
                              <select className={tw.select} value={editQCorrect}
                                onChange={e => setEditQCorrect(e.target.value)}>
                                <option value="">Correct answer…</option>
                                {['A','B','C','D'].map(l => <option key={l} value={l}>{l}</option>)}
                              </select>
                            </>
                          )}

                          {editQType === 'tf' && (
                            <select className={tw.select} value={editQCorrect}
                              onChange={e => setEditQCorrect(e.target.value)}>
                              <option value="">Correct answer…</option>
                              <option value="True">True</option>
                              <option value="False">False</option>
                            </select>
                          )}

                          {editQType === 'identification' && (
                            <input className={tw.input} placeholder="Expected answer (auto-scoring)"
                              value={editQCorrect} onChange={e => setEditQCorrect(e.target.value)} />
                          )}

                          <input className={tw.input} placeholder="Max points" type="number" min="0" step="0.5"
                            value={editQPoints} onChange={e => setEditQPoints(e.target.value)} />

                          <ErrorBox msg={saveQErr} />
                          <div className="flex gap-2">
                            <button className={tw.btnPrimary} type="button"
                              disabled={savingQ || !editQPrompt.trim()}
                              onClick={() => saveEditQ(q.id)}>
                              {savingQ ? 'Saving…' : 'Save'}
                            </button>
                            <button className={tw.btnSm} type="button" onClick={cancelEditQ}>
                              Cancel
                            </button>
                          </div>
                        </div>
                      )
                    }

                    // ── Read-only card ──────────────────────────────────────────
                    return (
                      <div key={q.id} className={tw.card}>
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex-1">
                            <div className="flex items-center gap-2">
                              <span className={`text-xs font-mono ${typeColor}`}>[{typeLabel}]</span>
                              <span className="text-sm font-medium text-zinc-100">Q{q.order_index}. {q.prompt}</span>
                            </div>
                            {q.rubric_text && (
                              <div className="mt-1 text-xs text-zinc-400">Rubric: {q.rubric_text}</div>
                            )}
                            {choices.length > 0 && (
                              <div className="mt-1 flex gap-3 flex-wrap">
                                {choices.map((c, i) => (
                                  <span key={i} className="text-xs text-zinc-400">
                                    <span className={q.correct_answer === String.fromCharCode(65+i) ? 'text-emerald-400 font-bold' : ''}>
                                      {String.fromCharCode(65+i)}.
                                    </span>{' '}{c}
                                  </span>
                                ))}
                              </div>
                            )}
                            {q.correct_answer && q.question_type !== 'mcq' && (
                              <div className="mt-1 text-xs text-emerald-400">Answer: {q.correct_answer}</div>
                            )}
                            {q.region_json && (
                              <div className="mt-1 text-xs text-emerald-400">Region mapped</div>
                            )}
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            <div className="text-xs text-zinc-400 whitespace-nowrap">{q.max_points} pts</div>
                            <button type="button" onClick={() => startEditQ(q)}
                              className="text-xs text-zinc-500 hover:text-emerald-400 transition px-1"
                              title="Edit question">
                              ✎
                            </button>
                            <button type="button" onClick={() => deleteQuestion(q)}
                              className="text-xs text-zinc-600 hover:text-red-400 transition px-1"
                              title="Delete question">
                              ✕
                            </button>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
            }
          </>
        }
      </div>
    </div>
  )
}
