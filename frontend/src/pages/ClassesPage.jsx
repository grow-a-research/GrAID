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
  const [bulkFilter, setBulkFilter] = useState('')

  // enrolled list search + unenroll
  const [enrolledFilter, setEnrolledFilter] = useState('')
  const [unenrollingId, setUnenrollingId] = useState(null)

  // bulk enroll via CSV
  const csvRef = useRef(null)
  const [csvBulking, setCsvBulking] = useState(false)
  const [csvBulkResult, setCsvBulkResult] = useState(null)
  const [csvToolsOpen, setCsvToolsOpen] = useState(false)

  useEffect(() => { loadClasses(); loadStudents() }, [])

  async function loadClasses() {
    try { setClasses(await api.classes.list()) } catch {}
  }
  async function loadStudents() {
    try { setStudents(await api.students.list()) } catch {}
  }
  async function selectClass(cls) {
    setSelected(cls); setEnrollErr(''); setEnrollId('')
    setBulkSelected(new Set()); setBulkResult(null); setCsvBulkResult(null); setCsvToolsOpen(false)
    setBulkFilter(''); setEnrolledFilter('')
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

  async function unenrollStudent(studentId) {
    if (!selected) return
    if (!window.confirm(`Unenroll ${studentId} from ${selected.name}?`)) return
    setUnenrollingId(studentId)
    try {
      await api.classes.unenroll(selected.id, studentId)
      setEnrolled(prev => prev.filter(s => s.student_id !== studentId))
    } catch (err) { alert(`Unenroll failed: ${err.message}`) }
    setUnenrollingId(null)
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
  const bulkFilterLower = bulkFilter.trim().toLowerCase()
  const notEnrolledFiltered = bulkFilterLower
    ? notEnrolled.filter(s =>
        s.full_name.toLowerCase().includes(bulkFilterLower) ||
        s.student_id.toLowerCase().includes(bulkFilterLower))
    : notEnrolled
  const enrolledFilterLower = enrolledFilter.trim().toLowerCase()
  const enrolledFiltered = enrolledFilterLower
    ? enrolled.filter(s =>
        s.full_name.toLowerCase().includes(enrolledFilterLower) ||
        s.student_id.toLowerCase().includes(enrolledFilterLower))
    : enrolled

  function toggleBulk(studentId) {
    setBulkSelected(prev => {
      const next = new Set(prev)
      next.has(studentId) ? next.delete(studentId) : next.add(studentId)
      return next
    })
  }
  function toggleAllBulk() {
    if (bulkSelected.size === notEnrolledFiltered.length) {
      setBulkSelected(new Set())
    } else {
      setBulkSelected(new Set(notEnrolledFiltered.map(s => s.student_id)))
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

  // Shared by both CSV and Excel import: given rows of cells, locates the ID
  // column via its header ("student_id" / "id", case-insensitive, any
  // position) — falls back to the first column when no header matches. Works
  // for a bare single-column list of IDs or a multi-column sheet (e.g.
  // student_id, full_name, email — extra columns are simply ignored).
  function extractStudentIds(rows) {
    const clean = (v) => (v === null || v === undefined) ? '' : String(v).trim()
    const cleanRows = rows.map(r => r.map(clean)).filter(r => r.some(c => c !== ''))
    if (cleanRows.length === 0) return []
    const header = cleanRows[0].map(c => c.toLowerCase())
    const idCol = header.findIndex(c => c === 'student_id' || c === 'id' || c === 'studentid')
    const dataRows = idCol !== -1 ? cleanRows.slice(1) : cleanRows
    const col = idCol !== -1 ? idCol : 0
    return dataRows.map(r => r[col]).filter(Boolean)
  }

  function parseCsvStudentIds(text) {
    const splitRow = (line) => line.split(',').map(cell => cell.trim().replace(/^"(.*)"$/, '$1'))
    const lines = text.split(/\r?\n/).map(l => l.trim()).filter(Boolean)
    return extractStudentIds(lines.map(splitRow))
  }

  async function parseExcelStudentIds(file) {
    const XLSX = await import('xlsx')
    const buf = await file.arrayBuffer()
    const workbook = XLSX.read(buf, { type: 'array' })
    const sheet = workbook.Sheets[workbook.SheetNames[0]]
    const rows = XLSX.utils.sheet_to_json(sheet, { header: 1, raw: false, defval: '' })
    return extractStudentIds(rows)
  }

  async function importEnrollCsv(e) {
    const file = e.target.files?.[0]
    if (!file || !selected) return
    setCsvBulking(true); setCsvBulkResult(null)
    try {
      const isExcel = /\.(xlsx|xls)$/i.test(file.name)
      const ids = isExcel ? await parseExcelStudentIds(file) : parseCsvStudentIds(await file.text())
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

            {/* Bulk enroll: multi-select + CSV — always available, independent of whether
                anyone is currently unenrolled, since CSV import shouldn't disappear
                just because the roster you already loaded happens to be fully enrolled. */}
            <div className={`${tw.card} flex flex-col gap-3`}>
              <div className="flex items-center justify-between">
                <div className={tw.label}>Bulk enroll ({notEnrolled.length} not yet enrolled)</div>
                <button type="button"
                  className="text-xs text-zinc-500 hover:text-zinc-300 underline underline-offset-2"
                  onClick={() => setCsvToolsOpen(o => !o)}>
                  {csvToolsOpen ? 'Hide CSV import' : 'Use CSV instead'}
                </button>
              </div>

              {csvToolsOpen && (
                <div className="flex flex-col gap-2 rounded-lg border border-zinc-800 bg-zinc-950/40 p-3">
                  <div className="flex gap-2 flex-wrap">
                    <button type="button" className={tw.btnSm} onClick={downloadEnrollTemplate}>
                      Download CSV template
                    </button>
                    <label className={`${tw.btnSm} cursor-pointer`}>
                      {csvBulking ? 'Importing…' : 'Upload CSV / Excel'}
                      <input ref={csvRef} type="file"
                        accept=".csv,.xlsx,.xls,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
                        className="hidden"
                        onChange={importEnrollCsv} disabled={csvBulking} />
                    </label>
                  </div>
                  <div className="text-xs text-zinc-500">
                    Accepts .csv or .xlsx/.xls — a bare list of IDs, or a sheet with a{' '}
                    <code>student_id</code> column (extra columns like name are fine and ignored).
                  </div>
                  {csvBulkResult && !csvBulkResult.error && (
                    <div className="text-xs text-emerald-400">
                      {csvBulkResult.enrolled} enrolled · {csvBulkResult.skipped} skipped
                      {csvBulkResult.errors?.length > 0 && (
                        <div className="text-red-400 mt-0.5">{csvBulkResult.errors.join(' · ')}</div>
                      )}
                    </div>
                  )}
                  {csvBulkResult?.error && <div className="text-xs text-red-400">{csvBulkResult.error}</div>}
                </div>
              )}

              {notEnrolled.length === 0
                ? <div className="text-xs text-zinc-500">Every known student is already enrolled in this class.</div>
                : <>
                {/* Search + checkbox list */}
                <input className={tw.input} placeholder="Search by name or ID…"
                  value={bulkFilter} onChange={e => setBulkFilter(e.target.value)} />
                <div className="max-h-48 overflow-y-auto flex flex-col gap-1 pr-1">
                  <label className="flex items-center gap-2 text-xs text-zinc-400 cursor-pointer select-none pb-1 border-b border-zinc-800">
                    <input type="checkbox" className="accent-emerald-500"
                      checked={bulkSelected.size === notEnrolledFiltered.length && notEnrolledFiltered.length > 0}
                      onChange={toggleAllBulk} />
                    Select all{bulkFilterLower ? ` (${notEnrolledFiltered.length} match)` : ''}
                  </label>
                  {notEnrolledFiltered.length === 0
                    ? <div className="py-2 text-xs text-zinc-500">No matching students.</div>
                    : notEnrolledFiltered.map(s => (
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
                </>
              }
            </div>

            {/* Enrolled list */}
            <div className={tw.label}>Enrolled ({enrolled.length})</div>
            {enrolled.length > 0 && (
              <input className={tw.input} placeholder="Search by name or ID…"
                value={enrolledFilter} onChange={e => setEnrolledFilter(e.target.value)} />
            )}
            {loadingEnrolled
              ? <div className={tw.muted}>Loading…</div>
              : enrolled.length === 0
                ? <Empty text="No students enrolled." />
                : enrolledFiltered.length === 0
                  ? <div className="py-2 text-xs text-zinc-500">No matching students.</div>
                  : <div className="flex flex-col gap-2">
                      {enrolledFiltered.map(s => (
                        <div key={s.id} className={`${tw.card} flex items-center justify-between gap-2`}>
                          <div>
                            <div className="text-sm text-zinc-100">{s.full_name}</div>
                            <div className={tw.muted}>{s.student_id}</div>
                          </div>
                          <button type="button" onClick={() => unenrollStudent(s.student_id)}
                            disabled={unenrollingId === s.student_id}
                            className="text-xs text-zinc-600 hover:text-red-400 transition shrink-0 px-1">
                            {unenrollingId === s.student_id ? '…' : '✕'}
                          </button>
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
