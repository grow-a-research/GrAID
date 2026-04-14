import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { tw, ErrorBox } from '../ui'

function b64ToObjectUrlPng(b64) {
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))
  const blob = new Blob([bytes], { type: 'image/png' })
  return URL.createObjectURL(blob)
}

function downloadText(filename, text) {
  const blob = new Blob([text ?? ''], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename
  document.body.appendChild(a); a.click(); a.remove()
  URL.revokeObjectURL(url)
}

function downloadUrl(filename, url) {
  const a = document.createElement('a')
  a.href = url; a.download = filename
  document.body.appendChild(a); a.click(); a.remove()
}

export default function OcrPage() {
  const fileRef = useRef(null)
  const [file, setFile] = useState(null)
  const [status, setStatus] = useState('idle') // idle | uploading | done | error
  const [error, setError] = useState('')
  const [text, setText] = useState('')
  const [boxedB64, setBoxedB64] = useState('')

  const originalUrl = useMemo(() => (file ? URL.createObjectURL(file) : ''), [file])
  const boxedUrl = useMemo(() => (boxedB64 ? b64ToObjectUrlPng(boxedB64) : ''), [boxedB64])

  useEffect(() => {
    return () => {
      if (originalUrl) URL.revokeObjectURL(originalUrl)
      if (boxedUrl) URL.revokeObjectURL(boxedUrl)
    }
  }, [originalUrl, boxedUrl])

  async function onExtract() {
    if (!file) return
    setStatus('uploading'); setError(''); setText(''); setBoxedB64('')
    try {
      const data = await api.extract(file)
      setText(data.text ?? '')
      setBoxedB64(data.boxed_image_png_base64 ?? '')
      setStatus('done')
    } catch (e) {
      setStatus('error'); setError(e?.message ?? String(e))
    }
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
      <div className="lg:col-span-2 flex flex-col gap-6">
        <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-medium text-zinc-100">Upload image</div>
              <div className="text-xs text-zinc-400">JPG / PNG recommended</div>
            </div>
            <button className={tw.btnGhost} onClick={() => fileRef.current?.click()}>
              Choose file
            </button>
          </div>

          <input ref={fileRef} type="file" accept="image/*" className="hidden"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)} />

          <div className="mt-4 rounded-xl border border-zinc-800 bg-zinc-950/40 p-3">
            <div className="text-xs text-zinc-400">Selected</div>
            <div className="mt-1 truncate text-sm text-zinc-100">
              {file ? file.name : 'No file selected'}
            </div>
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            <button className={tw.btnPrimary} disabled={!file || status === 'uploading'} onClick={onExtract}>
              {status === 'uploading' ? 'Extracting…' : 'Extract text'}
            </button>
            <button className={tw.btnGhost} disabled={!text}
              onClick={() => navigator.clipboard.writeText(text)}>
              Copy text
            </button>
            <button className={tw.btnGhost} disabled={!text}
              onClick={() => downloadText(`${file?.name ?? 'extracted'}.txt`, text)}>
              Download .txt
            </button>
            <button className={tw.btnGhost} disabled={!boxedUrl}
              onClick={() => downloadUrl(`${file?.name ?? 'boxed'}.png`, boxedUrl)}>
              Download boxed
            </button>
          </div>

          {status === 'error' && <div className="mt-3"><ErrorBox msg={error} /></div>}
        </div>

        <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-5">
          <div className="text-sm font-medium text-zinc-100">Extracted text</div>
          <textarea
            className="mt-3 h-80 w-full resize-none rounded-xl border border-zinc-800 bg-zinc-950/40 p-3 text-sm leading-relaxed text-zinc-100 outline-none focus:border-emerald-500/60"
            value={text} readOnly placeholder="Run extraction to see text here…"
          />
        </div>
      </div>

      <div className="lg:col-span-3 flex flex-col gap-6">
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-5">
            <div className="text-sm font-medium text-zinc-100">Original</div>
            <div className="mt-3 aspect-[4/5] overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950/40">
              {originalUrl
                ? <img src={originalUrl} alt="Original" className="h-full w-full object-contain" />
                : <div className="flex h-full items-center justify-center text-xs text-zinc-500">No image</div>
              }
            </div>
          </div>
          <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-5">
            <div className="text-sm font-medium text-zinc-100">Detected lines (boxed)</div>
            <div className="mt-3 aspect-[4/5] overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950/40">
              {boxedUrl
                ? <img src={boxedUrl} alt="Boxed" className="h-full w-full object-contain" />
                : <div className="flex h-full items-center justify-center text-xs text-zinc-500">Run extraction first</div>
              }
            </div>
          </div>
        </div>

        <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-5">
          <div className="text-sm font-medium text-zinc-100">Tips</div>
          <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-zinc-300">
            <li>Keep images under ~3000 px on the long edge for fastest inference.</li>
            <li>After a server restart, the first request may be slower while models reload.</li>
            <li>This endpoint uses the legacy <code className="text-emerald-400">/extract</code> route (Phase 2 pipeline).</li>
          </ul>
        </div>
      </div>
    </div>
  )
}
