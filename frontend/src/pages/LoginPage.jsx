import { useState } from 'react'
import { api } from '../api'
import { tw, ErrorBox } from '../ui'

const ROLES = [
  { id: 'teacher', label: 'Teacher', blurb: 'Manage classes, exams and grading.' },
  { id: 'student', label: 'Student', blurb: 'Join your class, download templates and upload your work.' },
]

export default function LoginPage({ onAuthed }) {
  const [role, setRole] = useState('student')
  const [mode, setMode] = useState('login') // 'login' | 'register'
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [inviteCode, setInviteCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  function pickRole(r) { setRole(r); setErr('') }

  async function submit(e) {
    e.preventDefault()
    setBusy(true); setErr('')
    try {
      if (mode === 'login') {
        await api.auth.login(role, email.trim(), password)
      } else {
        const body = { email: email.trim(), full_name: fullName.trim(), password }
        if (role === 'teacher' && inviteCode.trim()) body.invite_code = inviteCode.trim()
        await api.auth.register(role, body)
      }
      onAuthed()
    } catch (e2) { setErr(e2.message) }
    setBusy(false)
  }

  const current = ROLES.find(r => r.id === role)

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2">
          <div className="h-2 w-2 rounded-full bg-emerald-400" />
          <span className="text-lg font-semibold">GrAId</span>
        </div>

        <div className="mb-4 grid grid-cols-2 gap-1 rounded-lg border border-zinc-800 bg-zinc-900/60 p-1">
          {ROLES.map(r => (
            <button key={r.id} type="button" onClick={() => pickRole(r.id)}
              className={[
                'rounded-md py-1.5 text-sm transition',
                role === r.id ? 'bg-zinc-700 text-zinc-100' : 'text-zinc-400 hover:text-zinc-100',
              ].join(' ')}>
              {r.label}
            </button>
          ))}
        </div>

        <form onSubmit={submit} className={`${tw.card} flex flex-col gap-3`}>
          <div>
            <h1 className={tw.heading}>
              {mode === 'login' ? `${current.label} sign in` : `Create ${current.label.toLowerCase()} account`}
            </h1>
            <p className={`${tw.muted} mt-0.5`}>{current.blurb}</p>
          </div>

          {mode === 'register' && (
            <input className={tw.input} placeholder="Full name" value={fullName}
              onChange={e => setFullName(e.target.value)} required />
          )}
          <input className={tw.input} type="email" placeholder="Email" autoComplete="username"
            value={email} onChange={e => setEmail(e.target.value)} required />
          <input className={tw.input} type="password" placeholder="Password (8+ characters)"
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            value={password} onChange={e => setPassword(e.target.value)} required minLength={mode === 'register' ? 8 : 1} />
          {/* Only needed when the server was started with TEACHER_INVITE_CODE set. */}
          {mode === 'register' && role === 'teacher' && (
            <input className={tw.input} placeholder="Teacher invite code (optional)"
              value={inviteCode} onChange={e => setInviteCode(e.target.value)} />
          )}

          <ErrorBox msg={err} />
          <button className={tw.btnPrimary} type="submit" disabled={busy}>
            {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
          </button>

          <button type="button" className="text-xs text-zinc-500 hover:text-zinc-300 underline underline-offset-2"
            onClick={() => { setMode(m => (m === 'login' ? 'register' : 'login')); setErr('') }}>
            {mode === 'login' ? 'No account yet? Create one' : 'Already have an account? Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
