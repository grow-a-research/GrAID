import SearchPicker from './SearchPicker'

// Searchable class selector (name or code). See SearchPicker.
export default function ClassPicker({ classes, value, onChange, label = 'Class' }) {
  return (
    <SearchPicker items={classes} value={value} onChange={onChange} label={label}
      placeholder="Search class by name or code…"
      primary={c => c.name} secondary={c => c.code} emptyText="No matching classes." />
  )
}

// Searchable exam selector (title or exam code).
export function ExamPicker({ exams, value, onChange, label = 'Exam' }) {
  return (
    <SearchPicker items={exams} value={value} onChange={onChange} label={label}
      placeholder="Search exam by title or code…"
      primary={e => e.title} secondary={e => e.exam_code} emptyText="No matching exams." />
  )
}
