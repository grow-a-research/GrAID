import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { tw, ErrorBox, Empty } from '../ui'

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
  const [exams, setExams] = useState([])
  const [selectedExam, setSelectedExam] = useState(null)
  const [submissions, setSubmissions] = useState([])
  const [selectedSub, setSelectedSub] = useState(null)

  // create
  const [newExamId, setNewExamId] = useState('')
  const [newStudentId, setNewStudentId] = useState('')
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
  const [qualityWarnings, setQualityWarnings] = useState([])

  // batch upload
  const batchRef = useRef(null)
  const [batching, setBatching] = useState(false)
  const [batchResult, setBatchResult] = useState(null)

  // bulk process all pending
  const [bulkProcessing, setBulkProcessing] = useState(false)
  const [bulkResult, setBulkResult] = useState(null)

  useEffect(() => { api.exams.list().then(setExams).catch(() => {}) }, [])

  async function selectExam(exam) {
    setSelectedExam(exam)
    setSelectedSub(null)
    try { setSubmissions(await api.exams.submissions(exam.id)) } catch { setSubmissions([]) }
  }

  async function selectSub(sub) {
    setUploadErr(''); setProcessErr('')
    const full = await api.submissions.get(sub.id)
    setSelectedSub(full)
  }

  async function batchUpload(e) {
    const files = [...(e.target.files ?? [])]
    if (!files.length || !selectedExam) return
    setBatching(true); setBatchResult(null)
    try {
      const result = await api.exams.batchUpload(selectedExam.id, files)
      setBatchResult(result)
      setSubmissions(await api.exams.submissions(selectedExam.id))
    } catch (err) { setBatchResult({ error: err.message }) }
    setBatching(false)
    e.target.value = ''
  }

  async function bulkProcessAll() {
    if (!selectedExam) return
    setBulkProcessing(true); setBulkResult(null)
    try {
      const result = await api.exams.processAll(selectedExam.id)
      setBulkResult(result)
      setSubmissions(await api.exams.submissions(selectedExam.id))
    } catch (err) { setBulkResult({ error: err.message }) }
    setBulkProcessing(false)
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
      if (ex && selectedExam?.id === ex.id) {
        setSubmissions(await api.exams.submissions(ex.id))
      }
      setNewStudentId('')
      const full = await api.submissions.get(sub.id)
      setSelectedSub(full)
      if (ex) setSelectedExam(ex)
    } catch (err) { setCreateErr(err.message) }
    setCreating(false)
  }

  async function uploadPaper(e) {
    e.preventDefault()
    if (!selectedSub || !uploadFile) return
    setUploading(true); setUploadErr('')
    try {
      await api.submissions.uploadFile(selectedSub.id, uploadFile)
      const full = await api.submissions.get(selectedSub.id)
      setSelectedSub(full)
      setUploadFile(null)
      if (selectedExam) setSubmissions(await api.exams.submissions(selectedExam.id))
    } catch (err) { setUploadErr(err.message) }
    setUploading(false)
  }

  async function processPaper() {
    if (!selectedSub) return
    setProcessing(true); setProcessErr(''); setQualityWarnings([])
    try {
      setProcessStep('ocr')
      const ocrResult = await api.submissions.runOcr(selectedSub.id)
      if (ocrResult?.quality_warnings?.length) {
        setQualityWarnings(ocrResult.quality_warnings)
      }
      setProcessStep('grade')
      await api.submissions.grade(selectedSub.id)
      const full = await api.submissions.get(selectedSub.id)
      setSelectedSub(full)
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

        {/* Create */}
        <form onSubmit={createSubmission} className={`${tw.card} flex flex-col gap-3`}>
          <div className={tw.label}>New submission</div>
          <select className={tw.select} value={newExamId} onChange={e => setNewExamId(e.target.value)}>
            <option value="">Select exam…</option>
            {exams.map(ex => (
              <option key={ex.id} value={ex.id}>{ex.title} ({ex.exam_code})</option>
            ))}
          </select>
          <input className={tw.input} placeholder="Student ID (school-issued)"
            value={newStudentId} onChange={e => setNewStudentId(e.target.value)} />
          <ErrorBox msg={createErr} />
          <button className={tw.btnPrimary} type="submit" disabled={creating}>
            {creating ? 'Creating…' : 'Create submission'}
          </button>
        </form>

        {/* Browse by exam */}
        <div className="flex flex-col gap-2">
          <div className={tw.label}>Browse by exam</div>
          {exams.map(ex => (
            <button key={ex.id} type="button"
              className={selectedExam?.id === ex.id ? tw.rowActive : tw.row}
              onClick={() => selectExam(ex)}>
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
                    onClick={() => selectSub(s)}>
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

        {/* Batch upload */}
        {selectedExam && (
          <div className={`${tw.card} flex flex-col gap-2`}>
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
                      Page {f.page_number}: {f.original_filename}
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
              {qualityWarnings.length > 0 && (
                <div className="mt-2 rounded border border-amber-500/40 bg-amber-950/40 p-2 text-xs text-amber-300">
                  <p className="font-semibold mb-1">Scan quality warning</p>
                  {qualityWarnings.map((w, i) => <p key={i}>{w}</p>)}
                  <p className="mt-1 text-amber-400/70">OCR was still attempted — consider retaking the scan for better accuracy.</p>
                </div>
              )}
            </div>
          </>
        }
      </div>
    </div>
  )
}
