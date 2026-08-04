// Shared Tailwind class strings used across all pages.
// Import with: import { tw } from '../ui'

export const tw = {
  btnPrimary:
    'rounded-lg bg-emerald-500 px-4 py-2 text-sm font-medium text-emerald-950 hover:bg-emerald-400 disabled:opacity-50 transition',
  btnGhost:
    'rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-2 text-sm text-zinc-100 hover:bg-zinc-800 disabled:opacity-50 transition',
  btnSm:
    'rounded-md border border-zinc-700 bg-zinc-900 px-3 py-1 text-xs text-zinc-300 hover:bg-zinc-800 disabled:opacity-50 transition',
  btnSmPrimary:
    'rounded-md bg-emerald-500 px-3 py-1 text-xs font-medium text-emerald-950 hover:bg-emerald-400 disabled:opacity-50 transition',
  input:
    'w-full rounded-lg border border-zinc-700 bg-zinc-950/60 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-emerald-500/60 placeholder:text-zinc-500',
  select:
    'w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-emerald-500/60',
  card:
    'rounded-xl border border-zinc-800 bg-zinc-900/40 p-4',
  cardActive:
    'rounded-xl border border-emerald-500/50 bg-emerald-500/10 p-4',
  row:
    'flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-900/40 px-4 py-3 cursor-pointer hover:border-zinc-700 transition',
  rowActive:
    'flex items-center justify-between rounded-lg border border-emerald-500/50 bg-emerald-500/10 px-4 py-3 cursor-pointer transition',
  heading: 'text-lg font-semibold text-zinc-100',
  label: 'text-xs font-medium text-zinc-400 uppercase tracking-wide',
  muted: 'text-sm text-zinc-500',
  error: 'rounded-lg border border-red-900/50 bg-red-950/40 px-3 py-2 text-xs text-red-300',
  badge: (color) => {
    const map = {
      draft:       'bg-zinc-800 text-zinc-400',
      submitted:   'bg-blue-950 text-blue-300',
      ocr_done:    'bg-emerald-950 text-emerald-300',
      graded:      'bg-violet-950 text-violet-300',
    }
    return `inline-block rounded-full px-2 py-0.5 text-xs font-medium ${map[color] ?? 'bg-zinc-800 text-zinc-400'}`
  },
}

export function ErrorBox({ msg }) {
  if (!msg) return null
  return <div className={tw.error}>{msg}</div>
}

export function Empty({ text = 'Nothing here yet.' }) {
  return <p className={tw.muted}>{text}</p>
}
