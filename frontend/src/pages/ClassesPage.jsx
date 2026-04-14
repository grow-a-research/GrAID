import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { tw, ErrorBox, Empty } from '../ui'

export default function ClassesPage() {
  const [classes, setClasses] = useState([])
  const [students, setStudents] = useState([])
  const [selected, setSelected] = useState(null)
  const [enrolled, setEnrolled] = useState([])
  const [loadingEnrolled, setLoadingEnrolled] = useState(false)

  // new-class form
  const [newCode, setNewCode] = useState('')
  const [newName, setNewName] = useState('')
  const [creating, setCreating] = useState(false)
  const [createErr, setCreateErr] = useState('')

  // single enroll
  const [enrollId, setEnrollId] = useState('')
  const [enrolling, setEnrolling] = useState(false)
  const [enrollErr, setEnrollErr] = useState('')

  // bulk enroll (multi-select)
  const [bulkSelected, setBulkSelected] = useState(new Set())
  const [bulking, setBulking] = useState(false)
  const [bulkResult, setBulkResult] = useState(null)

  // bulk enroll via CSV
  const csvRef = useRef(null)
  const [csvBulking, setCsvBulking] = useState(false)
  const [csvBulkResult, setCsvBulkResult] = useState(null)

  useEffect(() => { loadClasses(); loadStudents() }, [])

  async function loadClasses() {
    try { setClasses(await api.classes.list()) } catch {}
  }
  async function loadStudents() {
    try { setStudents(await api.students.list()) } catch {}
  }
  async function selectClass(cls) {
    setSelected(cls); setEnrollErr(''); setEnrollId('')
    setBulkSelected(new Set()); setBulkResult(null); setCsvBulkResult(null)
    setLoadingEnrolled(true)
    try { setEnrolled(await api.classes.enrolled(cls.id)) } catch { setEnrolled([]) }
    setLoadingEnrolled(false)
  }
  async function createClass(e) {
    e.preventDefault()
    if (!newCode.trim() || !newName.trim()) return
    setCreating(true); setCreateErr('')
    try {
      const cls = await api.classes.create({ code: newCode.trim(), name: newName.trim() })
      setClasses(prev => [...prev, cls])
      setNewCode(''); setNewName('')
    } catch (err) { setCreateErr(err.message) }
    setCreating(false)
  }
  async function enrollStudent(e) {
    e.preventDefault()
    if (!selected || !enrollId.trim()) return
    setEnrolling(true); setEnrollErr('')
    try {
      await api.classes.enroll(selected.id, enrollId.trim())
      setEnrolled(await api.classes.enrolled(selected.id))
      setEnrollId('')
    } catch (err) { setEnrollErr(err.message) }
    setEnrolling(false)
  }

  async function deleteClass(cls) {
    if (!window.confirm(`Delete class "${cls.name}" (${cls.code})?\n\nThis will also delete all its exams, submissions, and uploaded scans. This cannot be undone.`)) return
    try {
      await api.classes.delete(cls.id)
      setClasses(prev => prev.filter(c => c.id !== cls.id))
      if (selected?.id === cls.id) { setSelected(null); setEnrolled([]) }
    } catch (err) { alert(`Delete failed: ${err.message}`) }
  }

  // multi-select bulk enroll
  const enrolledIds = new Set(enrolled.map(s => s.student_id))
  const notEnrolled = students.filter(s => !enrolledIds.has(s.student_id))

  function toggleBulk(studentId) {
    setBulkSelected(prev => {
      const next = new Set(prev)
      next.has(studentId) ? next.delete(studentId) : next.add(studentId)
      return next
    })
  }
  function toggleAllBulk() {
    if (bulkSelected.size === notEnrolled.length) {
      setBulkSelected(new Set())
    } else {
      setBulkSelected(new Set(notEnrolled.map(s => s.student_id)))
    }
  }

  async function enrollBulkSelected() {
    if (!selected || bulkSelected.size === 0) return
    setBulking(true); setBulkResult(null)
    try {
      const result = await api.classes.enrollBulk(selected.id, [...bulkSelected])
      setBulkResult(result)
      if (result.enrolled > 0) {
        setEnrolled(await api.classes.enrolled(selected.id))
        setBulkSelected(new Set())
      }
    } catch (err) { setBulkResult({ error: err.message }) }
    setBulking(false)
  }

  // CSV bulk enroll
  function downloadEnrollTemplate() {
    const nonEnrolledRows = notEnrolled.map(s => s.student_id).join('\n')
    const csv = `student_id\n${nonEnrolledRows}\n`
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `enroll_template_${selected?.code ?? 'class'}.csv`
    document.body.appendChild(a); a.click(); a.remove()
    URL.revokeObjectURL(url)
  }

  async function importEnrollCsv(e) {
    const file = e.target.files?.[0]
    if (!file || !selected) return
    setCsvBulking(true); setCsvBulkResult(null)
    try {
      const text = await file.text()
      const lines = text.split(/\r?\n/).map(l => l.trim()).filter(Boolean)
      // skip header row if it says "student_id"
      const ids = lines[0]?.toLowerCase() === 'student_id' ? lines.slice(1) : lines
      const result = await api.classes.enrollBulk(selected.id, ids)
      setCsvBulkResult(result)
      if (result.enrolled > 0) setEnrolled(await api.classes.enrolled(selected.id))
    } catch (err) { setCsvBulkResult({ error: err.message }) }
    setCsvBulking(false)
    e.target.value = ''
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      {/* Left: class list + create */}
      <div className="flex flex-col gap-4">
        <h2 className={tw.heading}>Classes</h2>

        <form onSubmit={createClass} className={`${tw.card} flex flex-col gap-3`}>
          <div className={tw.label}>New class</div>
          <input className={tw.input} placeholder="Code (e.g. CS101)" value={newCode}
            onChange={e => setNewCode(e.target.value)} />
          <input className={tw.input} placeholder="Name (e.g. Intro to CS)" value={newName}
            onChange={e => setNewName(e.target.value)} />
          <ErrorBox msg={createErr} />
          <button className={tw.btnPrimary} type="submit" disabled={creating}>
            {creating ? 'Creating…' : 'Create class'}
          </button>
        </form>

        <div className="flex flex-col gap-2">
          {classes.length === 0
            ? <Empty text="No classes yet." />
            : classes.map(cls => (
              <div key={cls.id} className={`${selected?.id === cls.id ? tw.rowActive : tw.row} flex items-center gap-2`}>
                <button type="button" className="flex-1 text-left flex items-center justify-between"
                  onClick={() => selectClass(cls)}>
                  <div>
                    <div className="text-sm font-medium text-zinc-100">{cls.name}</div>
                    <div className={tw.muted}>{cls.code}</div>
                  </div>
                </button>
                <button type="button" onClick={() => deleteClass(cls)}
                  className="text-xs text-zinc-600 hover:text-red-400 transition shrink-0 px-1">
                  ✕
                </button>
              </div>
            ))
          }
        </div>
      </div>

      {/* Right: enrollment panel */}
      <div className="lg:col-span-2 flex flex-col gap-4">
        {!selected
          ? <div className="flex h-40 items-center justify-center rounded-xl border border-dashed border-zinc-700">
              <span className={tw.muted}>Select a class to manage enrollment</span>
            </div>
          : <>
            <h2 className={tw.heading}>
              {selected.name}
              <span className="ml-2 text-sm font-normal text-zinc-400">({selected.code})</span>
            </h2>

            {/* Single enroll */}
            <form onSubmit={enrollStudent} className={`${tw.card} flex flex-col gap-3`}>
              <div className={tw.label}>Enroll by student ID</div>
              <div className="flex gap-2">
                <input className={tw.input} placeholder="Student ID (school-issued)"
                  value={enrollId} onChange={e => setEnrollId(e.target.value)} />
                <button className={tw.btnSmPrimary} type="submit" disabled={enrolling}
                  style={{whiteSpace:'nowrap'}}>
                  {enrolling ? 'Enrolling…' : 'Enroll'}
                </button>
              </div>
              <ErrorBox msg={enrollErr} />
            </form>

            {/* Bulk enroll: multi-select */}
            {notEnrolled.length > 0 && (
              <div className={`${tw.card} flex flex-col gap-3`}>
                <div className="flex items-center justify-between">
                  <div className={tw.label}>Bulk enroll ({notEnrolled.length} not yet enrolled)</div>
                  <div className="flex gap-2">
                    <button type="button" className={tw.btnSm} onClick={downloadEnrollTemplate}>
                      Download CSV template
                    </button>
                    <label className={`${tw.btnSm} cursor-pointer`}>
                      {csvBulking ? 'Importing…' : 'Upload CSV'}
                      <input ref={csvRef} type="file" accept=".csv,text/csv" className="hidden"
                        onChange={importEnrollCsv} disabled={csvBulking} />
                    </label>
                  </div>
                </div>

                {/* CSV result */}
                {csvBulkResult && !csvBulkResult.error && (
                  <div className="text-xs text-emerald-400">
                    {csvBulkResult.enrolled} enrolled · {csvBulkResult.skipped} skipped
                    {csvBulkResult.errors?.length > 0 && (
                      <div className="text-red-400 mt-0.5">{csvBulkResult.errors.join(' · ')}</div>
                    )}
                  </div>
                )}
                {csvBulkResult?.error && <div className="text-xs text-red-400">{csvBulkResult.error}</div>}

                {/* Checkbox list */}
                <div className="max-h-48 overflow-y-auto flex flex-col gap-1 pr-1">
                  <label className="flex items-center gap-2 text-xs text-zinc-400 cursor-pointer select-none pb-1 border-b border-zinc-800">
                    <input type="checkbox" className="accent-emerald-500"
                      checked={bulkSelected.size === notEnrolled.length && notEnrolled.length > 0}
                      onChange={toggleAllBulk} />
                    Select all
                  </label>
                  {notEnrolled.map(s => (
                    <label key={s.id} className="flex items-center gap-2 text-xs text-zinc-300 cursor-pointer select-none hover:text-zinc-100">
                      <input type="checkbox" className="accent-emerald-500"
                        checked={bulkSelected.has(s.student_id)}
                        onChange={() => toggleBulk(s.student_id)} />
                      <span className="font-medium">{s.student_id}</span>
                      <span className="text-zinc-500">{s.full_name}</span>
                    </label>
                  ))}
                </div>

                <div className="flex items-center gap-3">
                  <button type="button" className={tw.btnSmPrimary}
                    onClick={enrollBulkSelected}
                    disabled={bulking || bulkSelected.size === 0}>
                    {bulking ? 'Enrolling…' : `Enroll selected (${bulkSelected.size})`}
                  </button>
                  {bulkResult && !bulkResult.error && (
                    <span className="text-xs text-emerald-400">
                      {bulkResult.enrolled} enrolled · {bulkResult.skipped} skipped
                      {bulkResult.errors?.length > 0 && ` · ${bulkResult.errors.length} error(s)`}
                    </span>
                  )}
                  {bulkResult?.error && <span className="text-xs text-red-400">{bulkResult.error}</span>}
                </div>
              </div>
            )}

            {/* Enrolled list */}
            <div className={tw.label}>Enrolled ({enrolled.length})</div>
            {loadingEnrolled
              ? <div className={tw.muted}>Loading…</div>
              : enrolled.length === 0
                ? <Empty text="No students enrolled." />
                : <div className="flex flex-col gap-2">
                    {enrolled.map(s => (
                      <div key={s.id} className={tw.card}>
                        <div className="text-sm text-zinc-100">{s.full_name}</div>
                        <div className={tw.muted}>{s.student_id}</div>
                      </div>
                    ))}
                  </div>
            }
          </>
        }
      </div>
    </div>
  )
}
