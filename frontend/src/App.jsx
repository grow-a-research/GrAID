import { useState } from 'react'
import OcrPage         from './pages/OcrPage'
import ClassesPage     from './pages/ClassesPage'
import StudentsPage    from './pages/StudentsPage'
import ExamsPage       from './pages/ExamsPage'
import SubmissionsPage from './pages/SubmissionsPage'
import ResultsPage     from './pages/ResultsPage'
import AnalyticsPage   from './pages/AnalyticsPage'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000'

const MAIN_TABS = [
  { id: 'classes',     label: 'Classes',     desc: 'Create course classes and manage student enrollment.' },
  { id: 'students',    label: 'Students',    desc: 'Manage the student registry.' },
  { id: 'exams',       label: 'Exams',       desc: 'Create exams, add questions, and generate printable PDF templates with ArUco markers.' },
  { id: 'submissions', label: 'Submissions', desc: 'Create submissions, upload scanned papers, and process them (OCR + AI grading).' },
  { id: 'results',     label: 'Results',     desc: 'View per-question OCR text, AI scores and feedback, and apply teacher overrides.' },
  { id: 'analytics',   label: 'Analytics',   desc: 'Class overview, per-exam question breakdown, and individual student score tracker.' },
]

const TOOL_TABS = [
  { id: 'ocr', label: 'OCR Tool', desc: 'Raw OCR test — upload an image and inspect Surya line detection + Qwen2.5-VL transcription output.' },
]

export default function App() {
  const [tab, setTab]           = useState('classes')
  const [toolsOpen, setToolsOpen] = useState(false)

  const allTabs    = [...MAIN_TABS, ...TOOL_TABS]
  const activeTab  = allTabs.find(t => t.id === tab)

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      {/* Top bar */}
      <header className="border-b border-zinc-800 bg-zinc-900/60 backdrop-blur sticky top-0 z-10">
        <div className="mx-auto max-w-7xl px-4">
          <div className="flex items-center gap-6 py-3 flex-wrap">

            {/* Brand */}
            <div className="flex items-center gap-2 shrink-0">
              <div className="h-2 w-2 rounded-full bg-emerald-400" />
              <span className="text-sm font-semibold text-zinc-100">GrAId</span>
              <span className="text-xs text-zinc-600">{API_BASE}</span>
            </div>

            {/* Main nav */}
            <nav className="flex gap-1 flex-wrap">
              {MAIN_TABS.map(t => (
                <button key={t.id} type="button"
                  onClick={() => { setTab(t.id); setToolsOpen(false) }}
                  className={[
                    'rounded-md px-3 py-1.5 text-sm transition',
                    tab === t.id && !toolsOpen
                      ? 'bg-zinc-700 text-zinc-100'
                      : 'text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800',
                  ].join(' ')}>
                  {t.label}
                </button>
              ))}
            </nav>

            {/* Tools dropdown */}
            <div className="relative ml-auto">
              <button
                type="button"
                onClick={() => setToolsOpen(o => !o)}
                className={[
                  'rounded-md px-3 py-1.5 text-sm transition border',
                  toolsOpen
                    ? 'border-zinc-600 bg-zinc-800 text-zinc-100'
                    : 'border-zinc-800 text-zinc-500 hover:text-zinc-300 hover:border-zinc-700',
                ].join(' ')}>
                Tools ▾
              </button>
              {toolsOpen && (
                <div className="absolute right-0 mt-1 w-40 rounded-lg border border-zinc-700 bg-zinc-900 shadow-lg py-1 z-20">
                  {TOOL_TABS.map(t => (
                    <button key={t.id} type="button"
                      onClick={() => { setTab(t.id); setToolsOpen(false) }}
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
