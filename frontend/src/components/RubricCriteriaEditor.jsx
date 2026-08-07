import { tw } from '../ui'

// Structured rubric editor, grid-style — criteria as rows, performance levels
// as shared columns (matches how teachers actually build rubrics in
// Excel/Sheets: e.g. "Needs Improvement / Satisfactory / Excellent" across
// the top, one criterion per row). Editing a column header renames that
// level for every criterion at once. Points and descriptions stay
// independent per cell — the same level name can be worth different points
// depending on the criterion, which is how real rubrics are usually built.
//
// Underneath, each criterion still stores its own `levels` array (unchanged
// from before) — a shared-column grid is just the common case where every
// criterion's level labels line up by position. Column headers are read from
// the first criterion; editing a header writes that label into every row.

function emptyLevel() {
  return { label: '', points: 0, description: '' }
}

function emptyCriterion() {
  return { name: '', levels: [emptyLevel(), emptyLevel(), emptyLevel()] }
}

export { emptyCriterion }

// A criterion's max points is never independently set — it's always the
// highest of its own levels' points, so the two can't silently disagree.
export function criterionMaxPoints(c) {
  const points = (c.levels || []).map(lvl => parseFloat(lvl.points) || 0)
  return points.length ? Math.max(...points) : 0
}

export default function RubricCriteriaEditor({ criteria, onChange }) {
  const list = criteria || []
  const total = list.reduce((sum, c) => sum + criterionMaxPoints(c), 0)
  const numCols = Math.max(0, ...list.map(c => (c.levels || []).length))
  const columnLabels = Array.from({ length: numCols }, (_, i) => list[0]?.levels?.[i]?.label ?? '')

  function updateCriterion(idx, patch) {
    onChange(list.map((c, i) => (i === idx ? { ...c, ...patch } : c)))
  }
  function removeCriterion(idx) {
    onChange(list.filter((_, i) => i !== idx))
  }
  function addCriterion() {
    const labels = list[0]?.levels?.map(l => l.label) || []
    const levels = numCols > 0
      ? Array.from({ length: numCols }, (_, i) => ({ label: labels[i] || '', points: 0, description: '' }))
      : [emptyLevel()]
    onChange([...list, { name: '', levels }])
  }
  function cellAt(c, colIdx) {
    return c.levels?.[colIdx] || { label: '', points: 0, description: '' }
  }
  function updateCell(rowIdx, colIdx, patch) {
    const levels = [...(list[rowIdx].levels || [])]
    while (levels.length <= colIdx) levels.push(emptyLevel())
    levels[colIdx] = { ...levels[colIdx], ...patch }
    updateCriterion(rowIdx, { levels })
  }
  function updateColumnLabel(colIdx, label) {
    onChange(list.map(c => {
      const levels = [...(c.levels || [])]
      while (levels.length <= colIdx) levels.push(emptyLevel())
      levels[colIdx] = { ...levels[colIdx], label }
      return { ...c, levels }
    }))
  }
  function addColumn() {
    onChange(list.map(c => ({ ...c, levels: [...(c.levels || []), emptyLevel()] })))
  }
  function removeColumn(colIdx) {
    onChange(list.map(c => ({ ...c, levels: (c.levels || []).filter((_, i) => i !== colIdx) })))
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="overflow-x-auto rounded-lg border border-zinc-700">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr>
              <th className="min-w-[160px] border-b border-r border-zinc-700 bg-zinc-900 px-2 py-1.5 text-left font-medium text-zinc-400">
                Criteria
              </th>
              {columnLabels.map((label, colIdx) => (
                <th key={colIdx} className="min-w-[190px] border-b border-r border-zinc-700 bg-zinc-900 px-2 py-1.5">
                  <div className="flex items-center gap-1">
                    <input className={`${tw.input} !py-1`} placeholder={`Level ${colIdx + 1}`} maxLength={128}
                      value={label} onChange={e => updateColumnLabel(colIdx, e.target.value)} />
                    <button type="button" onClick={() => removeColumn(colIdx)}
                      className="shrink-0 text-zinc-600 hover:text-red-400 transition" title="Remove level column">
                      ✕
                    </button>
                  </div>
                </th>
              ))}
              <th className="border-b border-zinc-700 bg-zinc-900 px-2 py-1.5">
                <button type="button" className={tw.btnSm} onClick={addColumn}>+ Level</button>
              </th>
            </tr>
          </thead>
          <tbody>
            {list.map((c, rowIdx) => (
              <tr key={rowIdx}>
                <td className="border-b border-r border-zinc-800 px-2 py-1.5 align-top">
                  <div className="flex items-start gap-1">
                    <input className={`${tw.input} !py-1`} placeholder="Criterion name" maxLength={255}
                      value={c.name} onChange={e => updateCriterion(rowIdx, { name: e.target.value })} />
                    <button type="button" onClick={() => removeCriterion(rowIdx)}
                      className="mt-1 shrink-0 text-zinc-600 hover:text-red-400 transition" title="Remove criterion">
                      ✕
                    </button>
                  </div>
                  <div className="mt-1 text-[10px] text-zinc-500">{criterionMaxPoints(c)} pts</div>
                </td>
                {Array.from({ length: numCols }).map((_, colIdx) => {
                  const cell = cellAt(c, colIdx)
                  return (
                    <td key={colIdx} className="border-b border-r border-zinc-800 px-2 py-1.5 align-top">
                      <input className={`${tw.input} !py-1 mb-1 w-16`} type="number" min="0" step="0.5"
                        placeholder="Pts" value={cell.points}
                        onChange={e => updateCell(rowIdx, colIdx, { points: parseFloat(e.target.value) || 0 })} />
                      <textarea className={`${tw.input} !py-1`} rows={2} placeholder="Description" maxLength={2000}
                        value={cell.description}
                        onChange={e => updateCell(rowIdx, colIdx, { description: e.target.value })} />
                    </td>
                  )
                })}
                <td className="border-b border-zinc-800" />
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <button type="button" className={`${tw.btnSm} self-start`} onClick={addCriterion}>
        + Add criterion
      </button>

      {list.length > 0 && (
        <div className="text-xs text-zinc-400">
          Total: <span className="font-medium text-zinc-200">{total}</span> pts
          {' '}(sum of each criterion's highest-scoring level — points aren't locked per column, set them per cell)
        </div>
      )}
    </div>
  )
}
