import { useEffect, useRef, useState, useCallback } from 'react'
import { api } from '../api'
import { tw, ErrorBox, Empty } from '../ui'
import { useWorkflow } from '../context/WorkflowContext'

const STATUS_STEPS = ['draft', 'submitted', 'ocr_done', 'graded']

function StatusBar({ status }) {
  const idx = STATUS_STEPS.indexOf(status)
  return (
    <div className="flex items-center gap-1">
      {STATUS_STEPS.map((s, i) => (
        <div key={s} className="flex items-center gap-1">
          <div className={[
            'h-2 w-2 rounded-full',
            i <= idx ? 'bg-emerald-400' : 'bg-zinc-700',
          ].join(' ')} />
          <span className={`text-xs ${i <= idx ? 'text-zinc-300' : 'text-zinc-600'}`}>{s}</span>
          {i < STATUS_STEPS.length - 1 && (
            <div className={`h-px w-4 ${i < idx ? 'bg-emerald-400' : 'bg-zinc-700'}`} />
          )}
        </div>
      ))}
    </div>
  )
}

export default function SubmissionsPage() {
  const {
    selectedClass, selectClass,
    selectedExam, selectExam: pickExam,
    selectedSubmission: selectedSub, selectSubmission: pickSub, updateSelectedSubmission: setSelectedSub,
  } = useWorkflow()
  const [classes, setClasses] = useState([])
  const [exams, setExams] = useState([])
  const [submissions, setSubmissions] = useState([])

  // create
  const [newExamId, setNewExamId] = useState('')
  const [newStudentId, setNewStudentId] = useState('')
  const [studentSearch, setStudentSearch] = useState('')
  const [enrolledStudents, setEnrolledStudents] = useState([])
  const [studentPickerOpen, setStudentPickerOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [createErr, setCreateErr] = useState('')

  // upload
  const [uploadFile, setUploadFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadErr, setUploadErr] = useState('')

  // camera
  const videoRef      = useRef(null)
  const canvasRef     = useRef(null)
  const streamRef     = useRef(null)
  const [camVisible,  setCamVisible]  = useState(false) // toggle camera section
  const [camOpen,     setCamOpen]     = useState(false) // viewfinder active
  const [camErr,      setCamErr]      = useState('')
  const [captured,    setCaptured]    = useState(null)  // blob URL preview
  const hasCamera = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia

  // process (OCR + grade)
  const [processing, setProcessing] = useState(false)
  const [processStep, setProcessStep] = useState('')   // 'ocr' | 'grade' | ''
  const [processErr, setProcessErr] = useState('')

  // batch upload
  const batchRef = useRef(null)
  const [batching, setBatching] = useState(false)
  const [batchResult, setBatchResult] = useState(null)
  const [batchToolsOpen, setBatchToolsOpen] = useState(false)

  // bulk process all pending
  const [bulkProcessing, setBulkProcessing] = useState(false)
  const [bulkResult, setBulkResult] = useState(null)

  // background queue
  const [queueStatus, setQueueStatus] = useState(null)
  const queuePollRef = useRef(null)
  const bulkPollRef = useRef(null)

  useEffect(() => { api.classes.list().then(setClasses).catch(() => {}) }, [])

  // Re-loads the exam list whenever the shared selected class changes (including
  // arriving here with a class already picked from Exams/Results).
  useEffect(() => {
    api.exams.list(selectedClass?.id).then(setExams).catch(() => setExams([]))
  }, [selectedClass?.id])

  // Loads the roster for whichever exam is picked in "New submission" — the
  // student picker only offers students enrolled in that exam's class.
  useEffect(() => {
    setNewStudentId(''); setStudentSearch('')
    const ex = exams.find(x => x.id === parseInt(newExamId))
    if (!ex) { setEnrolledStudents([]); return }
    api.classes.enrolled(ex.class_id).then(setEnrolledStudents).catch(() => setEnrolledStudents([]))
  }, [newExamId])

  // Loads the submission list whenever the shared selected exam changes — covers both
  // an explicit pick here and arriving with an exam already selected from Exams/Results.
  useEffect(() => {
    if (!selectedExam) { setSubmissions([]); return }
    api.exams.submissions(selectedExam.id).then(setSubmissions).catch(() => setSubmissions([]))
  }, [selectedExam?.id])

  // Bulk "process all" runs server-side and can outlive this component (e.g. you
  // navigate away mid-batch and come back, or a groupmate started it on another
  // machine) — check real server state on arrival instead of assuming idle.
  useEffect(() => {
    if (!selectedExam) return
    api.exams.processAllStatus(selectedExam.id)
      .then(s => { if (s.processing) { setBulkProcessing(true); startBulkPolling() } })
      .catch(() => {})
  }, [selectedExam?.id])

  // Loads full submission detail (files, etc.) whenever the shared selected submission
  // changes — the row objects in the list above are lighter-weight than the full record.
  useEffect(() => {
    setUploadErr(''); setProcessErr('')
    if (!selectedSub) return
    api.submissions.get(selectedSub.id).then(mergeFullSubmission).catch(() => {})
  }, [selectedSub?.id])

  // GET /submissions/{id} returns the raw record (numeric student_id, no student_name) —
  // preserve the denormalized display fields from the list row instead of clobbering them.
  function mergeFullSubmission(full) {
    setSelectedSub(prev => ({
      ...full,
      student_id: prev?.student_id ?? full.student_id,
      student_name: prev?.student_name ?? full.student_name,
    }))
  }

  async function batchUpload(e) {
    const files = [...(e.target.files ?? [])]
    if (!files.length || !selectedExam) return
    setBatching(true); setBatchResult(null)
    try {
      const result = await api.exams.batchUpload(selectedExam.id, files)
      setBatchResult(result)
      setSubmissions(await api.exams.submissions(selectedExam.id))
      // Auto-enqueue newly uploaded scans for background processing
      if (result.ok_count > 0) {
        try {
          await api.queue.enqueue(selectedExam.id)
          setQueueStatus(await api.queue.status())
          startQueuePolling()
        } catch {}
      }
    } catch (err) { setBatchResult({ error: err.message }) }
    setBatching(false)
    e.target.value = ''
  }

  const startBulkPolling = useCallback(() => {
    if (bulkPollRef.current) return   // already polling
    bulkPollRef.current = setInterval(async () => {
      try {
        const s = await api.exams.processAllStatus(selectedExam.id)
        if (!s.processing) {
          clearInterval(bulkPollRef.current)
          bulkPollRef.current = null
          setBulkProcessing(false)
          // Refresh submission list now that the batch has drained
          try { setSubmissions(await api.exams.submissions(selectedExam.id)) } catch {}
        }
      } catch {}
    }, 2000)
  }, [selectedExam])

  async function bulkProcessAll() {
    if (!selectedExam) return
    setBulkProcessing(true); setBulkResult(null)
    startBulkPolling()   // catches completion even if this tab navigates away and back
    try {
      const result = await api.exams.processAll(selectedExam.id)
      setBulkResult(result)
      setSubmissions(await api.exams.submissions(selectedExam.id))
    } catch (err) { setBulkResult({ error: err.message }) }
    setBulkProcessing(false)
  }

  const startQueuePolling = useCallback(() => {
    if (queuePollRef.current) return   // already polling
    queuePollRef.current = setInterval(async () => {
      try {
        const s = await api.queue.status()
        setQueueStatus(s)
        const active = s.pending > 0 || s.current !== null
        if (!active) {
          clearInterval(queuePollRef.current)
          queuePollRef.current = null
          // Refresh submission list after queue drains
          if (selectedExam) {
            try { setSubmissions(await api.exams.submissions(selectedExam.id)) } catch {}
          }
        }
      } catch {}
    }, 2000)
  }, [selectedExam])

  async function enqueueAll() {
    if (!selectedExam) return
    try {
      const result = await api.queue.enqueue(selectedExam.id)
      setQueueStatus(await api.queue.status())
      if (result.enqueued > 0) startQueuePolling()
    } catch (err) { alert(`Enqueue failed: ${err.message}`) }
  }

  async function deleteSub(sub) {
    if (!window.confirm(`Delete submission #${sub.id} for ${sub.student_name}?\n\nThis removes all uploaded scans, OCR results, and grades. This cannot be undone.`)) return
    try {
      await api.submissions.delete(sub.id)
      if (selectedExam) setSubmissions(await api.exams.submissions(selectedExam.id))
      if (selectedSub?.id === sub.id) setSelectedSub(null)
    } catch (err) { alert(`Delete failed: ${err.message}`) }
  }

  async function createSubmission(e) {
    e.preventDefault()
    if (!newExamId || !newStudentId.trim()) return
    setCreating(true); setCreateErr('')
    try {
      const sub = await api.submissions.create({
        exam_id: parseInt(newExamId),
        student_id: newStudentId.trim(),
      })
      const ex = exams.find(x => x.id === parseInt(newExamId))
      // Refetch via the list endpoint (not GET /submissions/{id}) so the row carries the
      // denormalized student_name/student_id the UI displays, not just the raw FK id.
      const subList = ex ? await api.exams.submissions(ex.id) : []
      if (ex) setSubmissions(subList)
      setNewStudentId(''); setStudentSearch('')
      const row = subList.find(s => s.id === sub.id)
      if (ex) pickExam(ex) // picking a (possibly different) exam clears submission first
      setSelectedSub(row ?? sub)
    } catch (err) { setCreateErr(err.message) }
    setCreating(false)
  }

  async function uploadPaper(e) {
    e.preventDefault()
    if (!selectedSub || !uploadFile) return
    setUploading(true); setUploadErr('')
    try {
      const existingPages = selectedSub.files?.map(f => f.page_number) ?? []
      const nextPage = existingPages.length ? Math.max(...existingPages) + 1 : 1
      await api.submissions.uploadFile(selectedSub.id, uploadFile, nextPage)
      mergeFullSubmission(await api.submissions.get(selectedSub.id))
      setUploadFile(null)
      if (selectedExam) setSubmissions(await api.exams.submissions(selectedExam.id))
    } catch (err) { setUploadErr(err.message) }
    setUploading(false)
  }

  async function deleteFile(f) {
    if (!selectedSub) return
    setUploadErr('')
    try {
      await api.submissions.deleteFile(selectedSub.id, f.id)
      mergeFullSubmission(await api.submissions.get(selectedSub.id))
      if (selectedExam) setSubmissions(await api.exams.submissions(selectedExam.id))
    } catch (err) { setUploadErr(err.message) }
  }

  async function processPaper() {
    if (!selectedSub) return
    setProcessing(true); setProcessErr('')
    try {
      setProcessStep('ocr')
      await api.submissions.runOcr(selectedSub.id)
      setProcessStep('grade')
      await api.submissions.grade(selectedSub.id)
      mergeFullSubmission(await api.submissions.get(selectedSub.id))
      if (selectedExam) setSubmissions(await api.exams.submissions(selectedExam.id))
    } catch (err) { setProcessErr(err.message) }
    setProcessing(false); setProcessStep('')
  }

  function downloadPaper() {
    if (!selectedSub) return
    const a = document.createElement('a')
    a.href = api.submissions.paperUrl(selectedSub.id)
    a.download = `submission_${selectedSub.id}_paper.pdf`
    document.body.appendChild(a); a.click(); a.remove()
  }

  // ── Camera helpers ────────────────────────────────────────────────────────
  function toggleCamera() {
    if (camVisible) {
      closeCamera()
      setCamVisible(false)
    } else {
      setCamVisible(true)
    }
  }

  async function openCamera() {
    setCamErr(''); setCaptured(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 3840 }, height: { ideal: 2160 } }
      })
      streamRef.current = stream
      setCamOpen(true)
      setTimeout(() => {
        if (videoRef.current) videoRef.current.srcObject = stream
      }, 50)
    } catch (e) {
      setCamErr(`Camera error: ${e.message}. Try uploading a file instead.`)
    }
  }

  function closeCamera() {
    streamRef.current?.getTracks().forEach(t => t.stop())
    streamRef.current = null
    setCamOpen(false); setCaptured(null); setCamErr('')
  }

  function capturePhoto() {
    const video  = videoRef.current
    const canvas = canvasRef.current
    if (!video || !canvas) return
    canvas.width  = video.videoWidth
    canvas.height = video.videoHeight
    canvas.getContext('2d').drawImage(video, 0, 0)
    canvas.toBlob(blob => {
      const file = new File([blob], `scan_${Date.now()}.jpg`, { type: 'image/jpeg' })
      setUploadFile(file)
      setCaptured(URL.createObjectURL(blob))
      // stop camera after capture
      streamRef.current?.getTracks().forEach(t => t.stop())
      streamRef.current = null
      setCamOpen(false)
    }, 'image/jpeg', 0.95)
  }

  const canProcess = selectedSub?.files?.length > 0 && !processing

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      {/* Left panel */}
      <div className="flex flex-col gap-4">
        <h2 className={tw.heading}>Submissions</h2>

        {/* Class filter — scopes both the create-form exam picker and the browse list below */}
        <select className={tw.select} value={selectedClass?.id ?? ''}
          onChange={e => {
            const cls = classes.find(c => c.id === parseInt(e.target.value)) ?? null
            selectClass(cls)
          }}>
          <option value="">All classes</option>
          {classes.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>

        {/* Create */}
        <form onSubmit={createSubmission} className={`${tw.card} flex flex-col gap-3`}>
          <div className={tw.label}>New submission</div>
          <select className={tw.select} value={newExamId} onChange={e => setNewExamId(e.target.value)}>
            <option value="">Select exam…</option>
            {exams.map(ex => (
              <option key={ex.id} value={ex.id}>{ex.title} ({ex.exam_code})</option>
            ))}
          </select>
          <div className="relative">
            <input className={tw.input}
              placeholder={newExamId ? 'Search enrolled student…' : 'Select an exam first'}
              value={studentSearch}
              disabled={!newExamId}
              onChange={e => { setStudentSearch(e.target.value); setNewStudentId(''); setStudentPickerOpen(true) }}
              onFocus={() => setStudentPickerOpen(true)}
              onBlur={() => setTimeout(() => setStudentPickerOpen(false), 150)} />
            {studentPickerOpen && newExamId && (
              <div className="absolute z-10 mt-1 max-h-48 w-full overflow-y-auto rounded-lg border border-zinc-700 bg-zinc-900 shadow-lg">
                {(() => {
                  const q = studentSearch.trim().toLowerCase()
                  const matches = q
                    ? enrolledStudents.filter(s =>
                        s.student_id.toLowerCase().includes(q) || s.full_name.toLowerCase().includes(q))
                    : enrolledStudents
                  if (matches.length === 0) {
                    return (
                      <div className="px-3 py-2 text-xs text-zinc-500">
                        {enrolledStudents.length === 0 ? 'No students enrolled in this class.' : 'No match.'}
                      </div>
                    )
                  }
                  return matches.map(s => (
                    <button key={s.id} type="button"
                      className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs hover:bg-zinc-800"
                      onMouseDown={e => e.preventDefault()}
                      onClick={() => {
                        setNewStudentId(s.student_id)
                        setStudentSearch(`${s.full_name} (${s.student_id})`)
                        setStudentPickerOpen(false)
                      }}>
                      <span className="text-zinc-100">{s.full_name}</span>
                      <span className="text-zinc-500">{s.student_id}</span>
                    </button>
                  ))
                })()}
              </div>
            )}
          </div>
          <ErrorBox msg={createErr} />
          <button className={tw.btnPrimary} type="submit" disabled={creating || !newExamId || !newStudentId}>
            {creating ? 'Creating…' : 'Create submission'}
          </button>
        </form>

        {/* Browse by exam */}
        <div className="flex flex-col gap-2">
          <div className={tw.label}>Browse by exam{selectedClass ? ` — ${selectedClass.name}` : ''}</div>
          {exams.length === 0
            ? <Empty text="No exams in this class yet." />
            : exams.map(ex => (
              <button key={ex.id} type="button"
                className={selectedExam?.id === ex.id ? tw.rowActive : tw.row}
                onClick={() => pickExam(ex)}>
                <div className="text-sm text-zinc-100">{ex.title}</div>
                <span className="text-xs text-zinc-500">{ex.exam_code}</span>
              </button>
            ))}
        </div>

        {/* Submission list */}
        {selectedExam && (
          <div className="flex flex-col gap-2">
            <div className={tw.label}>{selectedExam.exam_code} — {submissions.length} submission(s)</div>
            {submissions.length === 0
              ? <Empty text="No submissions yet." />
              : submissions.map(s => (
                <div key={s.id} className={`${selectedSub?.id === s.id ? tw.rowActive : tw.row} flex items-center gap-2`}>
                  <button type="button" className="flex-1 text-left flex items-center justify-between gap-2"
                    onClick={() => pickSub(s)}>
                    <div>
                      <div className="text-sm text-zinc-100">{s.student_name}</div>
                      <div className={tw.muted}>{s.student_id}</div>
                    </div>
                    <span className={tw.badge(s.status)}>{s.status}</span>
                  </button>
                  <button type="button" onClick={() => deleteSub(s)}
                    className="text-xs text-zinc-600 hover:text-red-400 transition shrink-0 px-1">
                    ✕
                  </button>
                </div>
              ))
            }
          </div>
        )}

        {/* Bulk process all pending */}
        {selectedExam && (() => {
          const pendingCount = submissions.filter(s => s.status === 'submitted').length
          return pendingCount > 0 ? (
            <div className={`${tw.card} flex flex-col gap-2`}>
              <div className={tw.label}>Bulk process</div>
              <p className={tw.muted}>
                {pendingCount} submission{pendingCount !== 1 ? 's' : ''} with uploaded scans waiting to be processed.
              </p>
              <button
                className={tw.btnPrimary}
                onClick={bulkProcessAll}
                disabled={bulkProcessing}>
                {bulkProcessing ? 'Processing…' : `Process all pending (${pendingCount})`}
              </button>
              {bulkResult?.error && (
                <div className="text-xs text-red-400">{bulkResult.error}</div>
              )}
              {bulkResult && !bulkResult.error && (
                <div className="flex flex-col gap-1 mt-1">
                  <div className="text-xs text-zinc-400">
                    <span className="text-emerald-400">{bulkResult.processed} processed</span>
                    {bulkResult.failed > 0 && (
                      <span className="text-red-400 ml-2">{bulkResult.failed} failed</span>
                    )}
                  </div>
                  {bulkResult.errors?.map((e, i) => (
                    <div key={i} className="text-xs text-red-400">{e}</div>
                  ))}
                </div>
              )}
            </div>
          ) : null
        })()}

        {/* Batch tools: batch upload + processing queue — collapsed by default */}
        {selectedExam && (
          <div className={`${tw.card} flex flex-col gap-2`}>
            <button type="button" className="flex items-center justify-between w-full text-left"
              onClick={() => setBatchToolsOpen(o => !o)}>
              <span className={tw.label}>Batch tools</span>
              <span className="text-xs text-zinc-500 flex items-center gap-1.5">
                {queueStatus && (queueStatus.pending > 0 || queueStatus.current) && (
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                )}
                {batchToolsOpen ? 'Hide ▴' : 'Show ▾'}
              </span>
            </button>

            {batchToolsOpen && (
              <div className="flex flex-col gap-4 pt-1">
                {/* Batch upload */}
                <div className="flex flex-col gap-2">
                  <div className={tw.label}>Batch upload scans</div>
                  <p className={tw.muted}>
                    Select multiple scan images at once. Each must contain the printed QR code
                    so the system can identify the student automatically.
                  </p>
                  <label className={`${tw.btnSm} cursor-pointer w-fit`}>
                    {batching ? 'Uploading…' : 'Select files…'}
                    <input ref={batchRef} type="file" accept="image/*" multiple className="hidden"
                      onChange={batchUpload} disabled={batching} />
                  </label>

                  {batchResult?.error && (
                    <div className="text-xs text-red-400">{batchResult.error}</div>
                  )}
                  {batchResult && !batchResult.error && (
                    <div className="flex flex-col gap-1 mt-1">
                      <div className="text-xs text-zinc-400">
                        {batchResult.ok_count} uploaded · {batchResult.error_count} failed
                      </div>
                      {batchResult.results.map((r, i) => (
                        <div key={i} className={`text-xs flex items-start gap-1.5 ${r.status === 'ok' ? 'text-emerald-400' : 'text-red-400'}`}>
                          <span>{r.status === 'ok' ? '✓' : '✕'}</span>
                          <span className="truncate">{r.filename}</span>
                          {r.student_name && <span className="text-zinc-400 shrink-0">→ {r.student_name}</span>}
                          {r.detail && <span className="text-zinc-500 shrink-0">({r.detail})</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Queue status */}
                <div className="flex flex-col gap-2 border-t border-zinc-800 pt-3">
                  <div className="flex items-center justify-between">
                    <div className={tw.label}>Processing queue</div>
                    <button className={tw.btnSm} onClick={enqueueAll} title="Add all pending scans to queue">
                      Enqueue all
                    </button>
                  </div>
                  {!queueStatus ? (
                    <p className={tw.muted}>No queue activity yet.</p>
                  ) : (
                    <>
                      {queueStatus.current && (
                        <div className="flex items-center gap-2 text-xs text-zinc-300">
                          <span className="inline-block w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                          Processing: {queueStatus.current.label}
                        </div>
                      )}
                      <div className="text-xs text-zinc-400 flex gap-3">
                        <span>Pending: <span className="text-zinc-200">{queueStatus.pending}</span></span>
                        <span>Done: <span className="text-emerald-400">{queueStatus.completed}</span></span>
                        {queueStatus.failed > 0 && (
                          <span>Failed: <span className="text-red-400">{queueStatus.failed}</span></span>
                        )}
                      </div>
                      {/* Progress bar */}
                      {queueStatus.total_enqueued > 0 && (
                        <div className="h-1.5 rounded-full bg-zinc-800 overflow-hidden">
                          <div
                            className="h-full rounded-full bg-emerald-500 transition-all"
                            style={{
                              width: `${Math.round(
                                (queueStatus.completed / queueStatus.total_enqueued) * 100
                              )}%`
                            }}
                          />
                        </div>
                      )}
                      {queueStatus.recent_errors?.slice(-3).map((e, i) => (
                        <div key={i} className="text-xs text-red-400 truncate">{e}</div>
                      ))}
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Right panel */}
      <div className="lg:col-span-2 flex flex-col gap-4">
        {!selectedSub
          ? <div className="flex h-40 items-center justify-center rounded-xl border border-dashed border-zinc-700">
              <span className={tw.muted}>Select or create a submission</span>
            </div>
          : <>
            {/* Header */}
            <div className="flex items-start justify-between gap-3">
              <div className="flex flex-col gap-1">
                <h2 className={tw.heading}>Submission #{selectedSub.id}</h2>
                <StatusBar status={selectedSub.status} />
              </div>
              <button className={tw.btnSm} onClick={downloadPaper}>
                Download student PDF
              </button>
            </div>

            {/* Upload / Camera */}
            <div className={tw.card}>
              <div className={tw.label}>Scan / upload paper</div>

              {/* Camera section — only shown when user opts in */}
              {camVisible && (
                <>
                  {/* Camera viewfinder */}
                  {camOpen && (
                    <div className="mt-2 flex flex-col gap-2">
                      {/* Video with A4 alignment overlay */}
                      <div className="relative w-full rounded-lg overflow-hidden border border-zinc-700 bg-zinc-950">
                        <video ref={videoRef} autoPlay playsInline className="w-full block" />
                        {/* A4 alignment guide (210:297 aspect ratio) */}
                        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                          <div className="relative border border-white/50"
                            style={{ aspectRatio: '210/297', height: '82%' }}>
                            {/* Corner brackets */}
                            <span className="absolute top-0 left-0 w-5 h-5 border-t-2 border-l-2 border-white" />
                            <span className="absolute top-0 right-0 w-5 h-5 border-t-2 border-r-2 border-white" />
                            <span className="absolute bottom-0 left-0 w-5 h-5 border-b-2 border-l-2 border-white" />
                            <span className="absolute bottom-0 right-0 w-5 h-5 border-b-2 border-r-2 border-white" />
                            <span className="absolute inset-x-0 top-2 text-center text-xs text-white/60 select-none">
                              Align paper within frame
                            </span>
                          </div>
                        </div>
                      </div>
                      <div className="flex gap-2">
                        <button className={tw.btnPrimary} type="button" onClick={capturePhoto}>
                          Capture
                        </button>
                        <button className={tw.btnGhost} type="button" onClick={closeCamera}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Captured preview */}
                  {!camOpen && captured && (
                    <div className="mt-2 flex flex-col gap-2">
                      <img src={captured} alt="Captured scan"
                        className="w-full max-h-48 object-contain rounded-lg border border-emerald-700/50" />
                      <div className="text-xs text-emerald-400">Photo captured — ready to upload</div>
                    </div>
                  )}

                  {/* Open camera / close camera toggle */}
                  {!camOpen && (
                    <div className="mt-2 flex gap-2 items-center">
                      <button type="button" className={tw.btnGhost} onClick={openCamera}>
                        Open Camera
                      </button>
                      <button type="button" className="text-xs text-zinc-500 hover:text-zinc-300"
                        onClick={toggleCamera}>
                        Hide camera
                      </button>
                    </div>
                  )}

                  <ErrorBox msg={camErr} />
                </>
              )}

              {/* Upload form */}
              {!camOpen && (
                <form onSubmit={uploadPaper} className="mt-2 flex flex-col gap-2">
                  <div className="flex gap-2 items-center flex-wrap">
                    <label className={`${tw.btnSm} cursor-pointer`}>
                      Choose File
                      <input type="file" accept="image/*" className="hidden"
                        onChange={e => {
                          setCaptured(null)
                          setUploadFile(e.target.files?.[0] ?? null)
                        }} />
                    </label>
                    {uploadFile && !captured && (
                      <span className="text-xs text-zinc-400 truncate max-w-40">{uploadFile.name}</span>
                    )}
                    {hasCamera && !camVisible && (
                      <button type="button"
                        className="text-xs text-zinc-500 hover:text-zinc-300 underline underline-offset-2"
                        onClick={toggleCamera}>
                        use camera instead
                      </button>
                    )}
                  </div>
                  <ErrorBox msg={uploadErr} />
                  <button className={tw.btnSmPrimary} type="submit" disabled={!uploadFile || uploading}>
                    {uploading ? 'Uploading…' : 'Upload'}
                  </button>
                </form>
              )}

              {/* Hidden canvas for camera capture */}
              <canvas ref={canvasRef} className="hidden" />

              {/* Uploaded files list */}
              {selectedSub.files?.length > 0 && (
                <div className="mt-3 flex flex-col gap-1 border-t border-zinc-800 pt-3">
                  {selectedSub.files.map(f => (
                    <div key={f.id} className="flex items-center gap-2 text-xs text-zinc-400">
                      <span className="text-emerald-400">✓</span>
                      <span className="flex-1">Page {f.page_number}: {f.original_filename}</span>
                      <button type="button"
                        className="text-zinc-500 hover:text-red-400"
                        title="Remove this page"
                        onClick={() => deleteFile(f)}>
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Process */}
            <div className={tw.card}>
              <div className={tw.label}>Process paper</div>
              <p className={`mt-1 ${tw.muted}`}>
                Runs OCR on the uploaded scan (with ArUco alignment if available), then sends each
                answer to Groq for AI grading against the rubric.
              </p>
              <div className="mt-3 flex items-center gap-3">
                <button className={tw.btnPrimary} onClick={processPaper} disabled={!canProcess}>
                  {processing
                    ? processStep === 'ocr' ? 'Running OCR…' : 'Grading with AI…'
                    : selectedSub.status === 'graded' ? 'Re-process' : 'Process paper'
                  }
                </button>
                {selectedSub.status === 'graded' && !processing && (
                  <span className="text-xs text-emerald-400">
                    Done — view results in the Results tab
                  </span>
                )}
              </div>
              <ErrorBox msg={processErr} />
            </div>
          </>
        }
      </div>
    </div>
  )
}
