import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { tw, ErrorBox, Empty } from '../ui'
import { toCsvFile } from '../lib/excelImport'

function downloadCsvTemplate() {
  const csv = 'student_id,full_name,email\n2024-0001,Juan Dela Cruz,juan@example.com\n'
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = 'students_template.csv'
  document.body.appendChild(a); a.click(); a.remove()
  URL.revokeObjectURL(url)
}

export default function StudentsPage() {
  const [students, setStudents] = useState([])
  const [newId, setNewId] = useState('')
  const [newName, setNewName] = useState('')
  const [newEmail, setNewEmail] = useState('')
  const [creating, setCreating] = useState(false)
  const [createErr, setCreateErr] = useState('')
  const [search, setSearch] = useState('')

  // CSV import
  const csvRef = useRef(null)
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState(null)

  // Inline edit
  const [editingId, setEditingId] = useState(null)   // student_id string
  const [editName, setEditName] = useState('')
  const [editEmail, setEditEmail] = useState('')
  const [saving, setSaving] = useState(false)

  // Bulk delete
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [bulkDeleting, setBulkDeleting] = useState(false)

  useEffect(() => { loadStudents() }, [])

  async function loadStudents() {
    try { setStudents(await api.students.list()) } catch {}
  }

  async function createStudent(e) {
    e.preventDefault()
    if (!newId.trim() || !newName.trim()) return
    setCreating(true); setCreateErr('')
    try {
      const s = await api.students.create({
        student_id: newId.trim(),
        full_name: newName.trim(),
        email: newEmail.trim() || undefined,
      })
      setStudents(prev => [...prev, s])
      setNewId(''); setNewName(''); setNewEmail('')
    } catch (err) { setCreateErr(err.message) }
    setCreating(false)
  }

  async function deleteStudent(s) {
    if (!window.confirm(`Delete student "${s.full_name}" (${s.student_id})?\n\nThis will also delete all their submissions. This cannot be undone.`)) return
    try {
      await api.students.delete(s.student_id)
      setStudents(prev => prev.filter(x => x.id !== s.id))
      setSelectedIds(prev => { const next = new Set(prev); next.delete(s.student_id); return next })
    } catch (err) { alert(`Delete failed: ${err.message}`) }
  }

  function toggleSelect(studentId) {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(studentId)) next.delete(studentId); else next.add(studentId)
      return next
    })
  }

  function toggleSelectAllVisible(visible) {
    setSelectedIds(prev => {
      const allSelected = visible.length > 0 && visible.every(s => prev.has(s.student_id))
      if (allSelected) {
        const next = new Set(prev)
        visible.forEach(s => next.delete(s.student_id))
        return next
      }
      const next = new Set(prev)
      visible.forEach(s => next.add(s.student_id))
      return next
    })
  }

  async function bulkDeleteSelected() {
    const ids = [...selectedIds]
    if (ids.length === 0) return
    if (!window.confirm(`Delete ${ids.length} selected student(s)?\n\nThis will also delete all their submissions. This cannot be undone.`)) return
    setBulkDeleting(true)
    try {
      const result = await api.students.bulkDelete(ids)
      await loadStudents()
      setSelectedIds(new Set())
      if (result.errors?.length > 0) {
        alert(`${result.deleted} deleted. ${result.errors.length} error(s):\n${result.errors.join('\n')}`)
      }
    } catch (err) { alert(`Bulk delete failed: ${err.message}`) }
    setBulkDeleting(false)
  }

  function startEdit(s) {
    setEditingId(s.student_id)
    setEditName(s.full_name)
    setEditEmail(s.email ?? '')
  }

  function cancelEdit() {
    setEditingId(null)
  }

  async function saveEdit(s) {
    setSaving(true)
    try {
      const updated = await api.students.update(s.student_id, {
        full_name: editName.trim() || undefined,
        email: editEmail.trim() || null,
      })
      setStudents(prev => prev.map(x => x.id === updated.id ? updated : x))
      setEditingId(null)
    } catch (err) { alert(`Save failed: ${err.message}`) }
    setSaving(false)
  }

  async function importCsv(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setImporting(true); setImportResult(null)
    try {
      const csvFile = await toCsvFile(file)
      const result = await api.students.import(csvFile)
      setImportResult(result)
      if (result.created > 0) await loadStudents()
    } catch (err) { setImportResult({ error: err.message }) }
    setImporting(false)
    e.target.value = ''
  }

  const filtered = search.trim()
    ? students.filter(s =>
        s.student_id.toLowerCase().includes(search.toLowerCase()) ||
        s.full_name.toLowerCase().includes(search.toLowerCase())
      )
    : students

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      {/* Left: create + import */}
      <div className="flex flex-col gap-4">
        <h2 className={tw.heading}>Students</h2>

        <form onSubmit={createStudent} className={`${tw.card} flex flex-col gap-3`}>
          <div className={tw.label}>Add student</div>
          <input className={tw.input} placeholder="Student ID (school-issued)"
            value={newId} onChange={e => setNewId(e.target.value)} />
          <input className={tw.input} placeholder="Full name"
            value={newName} onChange={e => setNewName(e.target.value)} />
          <input className={tw.input} placeholder="Email (optional)"
            type="email" value={newEmail} onChange={e => setNewEmail(e.target.value)} />
          <ErrorBox msg={createErr} />
          <button className={tw.btnPrimary} type="submit" disabled={creating}>
            {creating ? 'Adding…' : 'Add student'}
          </button>
        </form>

        {/* CSV / XLSX import */}
        <div className={`${tw.card} flex flex-col gap-2`}>
          <div className={tw.label}>Bulk import via CSV or Excel</div>
          <p className={tw.muted}>
            Columns: <span className="font-mono text-zinc-300">student_id</span>,{' '}
            <span className="font-mono text-zinc-300">full_name</span>,{' '}
            <span className="font-mono text-zinc-300">email</span> (optional).
            Duplicate IDs are skipped.
          </p>
          <div className="flex gap-2 flex-wrap">
            <label className={`${tw.btnSm} cursor-pointer`}>
              {importing ? 'Importing…' : 'Choose CSV/XLSX file'}
              <input ref={csvRef} type="file" accept=".csv,.xlsx,text/csv" className="hidden"
                onChange={importCsv} disabled={importing} />
            </label>
            <button type="button" className={tw.btnSm} onClick={downloadCsvTemplate}>
              Download template
            </button>
          </div>
          {importResult && !importResult.error && (
            <div className="text-xs text-emerald-400">
              {importResult.created} created · {importResult.skipped} skipped
              {importResult.errors?.length > 0 && (
                <div className="text-red-400 mt-1">{importResult.errors.join('; ')}</div>
              )}
            </div>
          )}
          {importResult?.error && (
            <div className="text-xs text-red-400">{importResult.error}</div>
          )}
        </div>
      </div>

      {/* Right: student list */}
      <div className="lg:col-span-2 flex flex-col gap-4">
        <div className="flex items-center gap-3">
          <input className={tw.input} placeholder="Search by name or ID…"
            value={search} onChange={e => setSearch(e.target.value)} />
          <span className={tw.muted} style={{whiteSpace:'nowrap'}}>{filtered.length} / {students.length}</span>
        </div>

        {filtered.length > 0 && (
          <div className="flex items-center justify-between gap-3">
            <label className="flex items-center gap-2 text-xs text-zinc-400 cursor-pointer select-none">
              <input type="checkbox" className="accent-emerald-500"
                checked={filtered.length > 0 && filtered.every(s => selectedIds.has(s.student_id))}
                onChange={() => toggleSelectAllVisible(filtered)} />
              Select all{search.trim() ? ` (${filtered.length} match)` : ''}
            </label>
            {selectedIds.size > 0 && (
              <button type="button" className={tw.btnSm} onClick={bulkDeleteSelected} disabled={bulkDeleting}
                style={{ color: '#f87171' }}>
                {bulkDeleting ? 'Deleting…' : `Delete selected (${selectedIds.size})`}
              </button>
            )}
          </div>
        )}

        {filtered.length === 0
          ? <Empty text={students.length === 0 ? 'No students yet.' : 'No matches.'} />
          : <div className="flex flex-col gap-2">
              {filtered.map(s => (
                <div key={s.id} className={tw.card}>
                  {editingId === s.student_id ? (
                    /* ── inline edit form ── */
                    <div className="flex flex-col gap-2">
                      <div className="text-xs text-zinc-500">Editing {s.student_id}</div>
                      <input className={tw.input} placeholder="Full name"
                        value={editName} onChange={e => setEditName(e.target.value)} />
                      <input className={tw.input} placeholder="Email (optional)"
                        type="email" value={editEmail} onChange={e => setEditEmail(e.target.value)} />
                      <div className="flex gap-2">
                        <button type="button" className={tw.btnSmPrimary}
                          onClick={() => saveEdit(s)} disabled={saving || !editName.trim()}>
                          {saving ? 'Saving…' : 'Save'}
                        </button>
                        <button type="button" className={tw.btnSm} onClick={cancelEdit}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    /* ── normal row ── */
                    <div className="flex items-center justify-between gap-3">
                      <input type="checkbox" className="accent-emerald-500 shrink-0"
                        checked={selectedIds.has(s.student_id)}
                        onChange={() => toggleSelect(s.student_id)} />
                      <div className="flex-1">
                        <div className="text-sm font-medium text-zinc-100">{s.full_name}</div>
                        <div className={tw.muted}>ID: {s.student_id}</div>
                      </div>
                      <div className="text-right shrink-0">
                        {s.email
                          ? <div className="text-xs text-zinc-400">{s.email}</div>
                          : <div className="text-xs text-zinc-600">no email</div>
                        }
                      </div>
                      <button type="button" onClick={() => startEdit(s)}
                        className="text-xs text-zinc-500 hover:text-zinc-200 transition px-1 shrink-0">
                        edit
                      </button>
                      <button type="button" onClick={() => deleteStudent(s)}
                        className="text-xs text-zinc-600 hover:text-red-400 transition px-1 shrink-0">
                        ✕
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
        }
      </div>
    </div>
  )
}
