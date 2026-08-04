import { useState } from 'react'
import OcrPage         from './pages/OcrPage'
import ClassesPage     from './pages/ClassesPage'
import StudentsPage    from './pages/StudentsPage'
import ExamsPage       from './pages/ExamsPage'
import SubmissionsPage from './pages/SubmissionsPage'
import ResultsPage     from './pages/ResultsPage'
import AnalyticsPage   from './pages/AnalyticsPage'
import { WorkflowProvider, useWorkflow } from './context/WorkflowContext'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000'

// Setup: done once per term, rarely revisited.
const SETUP_TABS = [
  { id: 'students', label: 'Students', desc: 'Manage the student registry.' },
  { id: 'classes',  label: 'Classes',  desc: 'Create course classes and manage student enrollment.' },
]

// Exam workflow: the per-exam cycle that repeats every time a new exam is given.
const WORKFLOW_TABS = [
  { id: 'exams',       label: 'Exams',       desc: 'Create exams, add questions, and generate printable PDF templates with ArUco markers.' },
  { id: 'submissions', label: 'Submissions', desc: 'Upload scanned papers and process them (OCR + AI grading).' },
  { id: 'results',     label: 'Results',     desc: 'View per-question OCR text, AI scores and feedback, and apply teacher overrides.' },
]

// Secondary: not part of the core setup → exam cycle.
const MORE_TABS = [
  { id: 'analytics', label: 'Analytics', desc: 'Class overview, per-exam question breakdown, and individual student score tracker.' },
  { id: 'ocr',       label: 'OCR Tool',  desc: 'Raw OCR test — upload an image and inspect Surya line detection + Qwen2.5-VL transcription output.' },
]

const WORKFLOW_TAB_IDS = new Set(WORKFLOW_TABS.map(t => t.id))

function NavGroup({ tabs, groupLabel, tab, onSelect }) {
  return (
    <div className="flex items-center gap-1.5 shrink-0">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-600 mr-0.5 hidden sm:inline">
        {groupLabel}
      </span>
      {tabs.map(t => (
        <button key={t.id} type="button"
          onClick={() => onSelect(t.id)}
          className={[
            'rounded-md px-3 py-1.5 text-sm transition',
            tab === t.id
              ? 'bg-zinc-700 text-zinc-100'
              : 'text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800',
          ].join(' ')}>
          {t.label}
        </button>
      ))}
    </div>
  )
}

function Breadcrumb({ tab }) {
  const { selectedExam, selectedSubmission, clearWorkflow } = useWorkflow()
  if (!WORKFLOW_TAB_IDS.has(tab) || !selectedExam) return null

  return (
    <div className="mx-auto max-w-7xl px-4">
      <div className="flex items-center gap-1.5 py-2 text-xs text-zinc-400 border-b border-zinc-900">
        <span className="text-zinc-600">Working on:</span>
        <span className="rounded bg-zinc-800/80 px-2 py-0.5 text-zinc-200">
          {selectedExam.title} <span className="text-zinc-500">({selectedExam.exam_code})</span>
        </span>
        {selectedSubmission && (
          <>
            <span className="text-zinc-700">›</span>
            <span className="rounded bg-zinc-800/80 px-2 py-0.5 text-zinc-200">
              {selectedSubmission.student_name}
            </span>
          </>
        )}
        <button type="button" onClick={clearWorkflow}
          className="ml-1 text-zinc-600 hover:text-zinc-300 transition" title="Clear selection">
          ✕
        </button>
      </div>
    </div>
  )
}

function AppShell() {
  const [tab, setTab]         = useState('classes')
  const [moreOpen, setMoreOpen] = useState(false)

  const allTabs   = [...SETUP_TABS, ...WORKFLOW_TABS, ...MORE_TABS]
  const activeTab = allTabs.find(t => t.id === tab)

  function selectTab(id) {
    setTab(id)
    setMoreOpen(false)
  }

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      {/* Top bar */}
      <header className="border-b border-zinc-800 bg-zinc-900/60 backdrop-blur sticky top-0 z-10">
        <div className="mx-auto max-w-7xl px-4">
          <div className="flex items-center gap-4 py-3 flex-wrap">

            {/* Brand */}
            <div className="flex items-center gap-2 shrink-0">
              <div className="h-2 w-2 rounded-full bg-emerald-400" />
              <span className="text-sm font-semibold text-zinc-100">GrAId</span>
              <span className="text-xs text-zinc-600 hidden md:inline">{API_BASE}</span>
            </div>

            <div className="h-5 w-px bg-zinc-800 hidden sm:block" />
            <NavGroup tabs={SETUP_TABS} groupLabel="Setup" tab={tab} onSelect={selectTab} />
            <div className="h-5 w-px bg-zinc-800 hidden sm:block" />
            <NavGroup tabs={WORKFLOW_TABS} groupLabel="Exam workflow" tab={tab} onSelect={selectTab} />

            {/* More dropdown — Analytics + Tools, deliberately lower priority */}
            <div className="relative ml-auto">
              <button
                type="button"
                onClick={() => setMoreOpen(o => !o)}
                className={[
                  'rounded-md px-3 py-1.5 text-sm transition border',
                  moreOpen
                    ? 'border-zinc-600 bg-zinc-800 text-zinc-100'
                    : 'border-zinc-800 text-zinc-500 hover:text-zinc-300 hover:border-zinc-700',
                ].join(' ')}>
                More ▾
              </button>
              {moreOpen && (
                <div className="absolute right-0 mt-1 w-44 rounded-lg border border-zinc-700 bg-zinc-900 shadow-lg py-1 z-20">
                  {MORE_TABS.map(t => (
                    <button key={t.id} type="button"
                      onClick={() => selectTab(t.id)}
                      className="w-full text-left px-3 py-2 text-sm text-zinc-300 hover:bg-zinc-800 hover:text-zinc-100 transition">
                      {t.label}
                    </button>
                  ))}
                </div>
              )}
            </div>

          </div>
        </div>
      </header>

      <Breadcrumb tab={tab} />

      {/* Page header */}
      <main className="mx-auto max-w-7xl px-4 py-8">
        {activeTab && (
          <div className="mb-6">
            <h1 className="text-2xl font-semibold text-zinc-50">{activeTab.label}</h1>
            <p className="mt-1 text-sm text-zinc-400">{activeTab.desc}</p>
          </div>
        )}

        {tab === 'classes'     && <ClassesPage />}
        {tab === 'students'    && <StudentsPage />}
        {tab === 'exams'       && <ExamsPage />}
        {tab === 'submissions' && <SubmissionsPage />}
        {tab === 'results'     && <ResultsPage />}
        {tab === 'analytics'   && <AnalyticsPage />}
        {tab === 'ocr'         && <OcrPage />}
      </main>
    </div>
  )
}

export default function App() {
  return (
    <WorkflowProvider>
      <AppShell />
    </WorkflowProvider>
  )
}
