import { useEffect, useMemo, useRef, useState } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000'

function b64ToObjectUrlPng(b64) {
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))
  const blob = new Blob([bytes], { type: 'image/png' })
  return URL.createObjectURL(blob)
}

function downloadText(filename, text) {
  const blob = new Blob([text ?? ''], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

function downloadUrl(filename, url) {
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
}

export default function App() {
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
    setStatus('uploading')
    setError('')
    setText('')
    setBoxedB64('')

    try {
      const fd = new FormData()
      fd.append('file', file)

      const resp = await fetch(`${API_BASE}/extract`, { method: 'POST', body: fd })
      if (!resp.ok) {
        const msg = await resp.text()
        throw new Error(`HTTP ${resp.status}: ${msg}`)
      }
      const data = await resp.json()
      setText(data.text ?? '')
      setBoxedB64(data.boxed_image_png_base64 ?? '')
      setStatus('done')
    } catch (e) {
      setStatus('error')
      setError(e?.message ?? String(e))
    }
  }

  return (
    <div className="min-h-full">
      <div className="mx-auto max-w-6xl px-4 py-10">
        <div className="flex flex-col gap-2">
          <div className="inline-flex items-center gap-2">
            <div className="h-2 w-2 rounded-full bg-emerald-400" />
            <span className="text-sm text-zinc-300">Backend</span>
            <span className="text-sm text-zinc-400">{API_BASE}</span>
          </div>
          <h1 className="text-balance text-3xl font-semibold tracking-tight text-zinc-50">
            Handwritten Test Paper OCR
          </h1>
          <p className="max-w-3xl text-sm leading-relaxed text-zinc-300">
            Upload a test paper image. The backend detects lines with Surya and transcribes with Qwen2.5-VL.
            You’ll get extracted text and a boxed preview.
          </p>
        </div>

        <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-5">
          <div className="lg:col-span-2">
            <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-5">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-zinc-100">Upload</div>
                  <div className="text-xs text-zinc-400">JPG/PNG recommended</div>
                </div>
                <button
                  type="button"
                  className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs text-zinc-100 hover:bg-zinc-800 disabled:opacity-50"
                  onClick={() => fileRef.current?.click()}
                >
                  Choose file
                </button>
              </div>

              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />

              <div className="mt-4 rounded-xl border border-zinc-800 bg-zinc-950/40 p-3">
                <div className="text-xs text-zinc-400">Selected</div>
                <div className="mt-1 truncate text-sm text-zinc-100">
                  {file ? file.name : 'No file selected'}
                </div>
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  type="button"
                  className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-medium text-emerald-950 hover:bg-emerald-400 disabled:opacity-50"
                  disabled={!file || status === 'uploading'}
                  onClick={onExtract}
                >
                  {status === 'uploading' ? 'Extracting…' : 'Extract text'}
                </button>
                <button
                  type="button"
                  className="rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-2 text-sm text-zinc-100 hover:bg-zinc-800 disabled:opacity-50"
                  disabled={!text}
                  onClick={() => navigator.clipboard.writeText(text)}
                >
                  Copy text
                </button>
                <button
                  type="button"
                  className="rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-2 text-sm text-zinc-100 hover:bg-zinc-800 disabled:opacity-50"
                  disabled={!text}
                  onClick={() => downloadText(`${file?.name ?? 'extracted'}.txt`, text)}
                >
                  Download .txt
                </button>
                <button
                  type="button"
                  className="rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-2 text-sm text-zinc-100 hover:bg-zinc-800 disabled:opacity-50"
                  disabled={!boxedUrl}
                  onClick={() => downloadUrl(`${file?.name ?? 'boxed'}.png`, boxedUrl)}
                >
                  Download boxed
                </button>
              </div>

              {status === 'error' && (
                <div className="mt-4 rounded-xl border border-red-900/50 bg-red-950/40 p-3 text-xs text-red-200">
                  {error}
                </div>
              )}
            </div>

            <div className="mt-6 rounded-2xl border border-zinc-800 bg-zinc-900/40 p-5">
              <div className="text-sm font-medium text-zinc-100">Extracted text</div>
              <textarea
                className="mt-3 h-80 w-full resize-none rounded-xl border border-zinc-800 bg-zinc-950/40 p-3 text-sm leading-relaxed text-zinc-100 outline-none focus:border-emerald-500/60"
                value={text}
                readOnly
                placeholder="Run extraction to see text here…"
              />
            </div>
          </div>

          <div className="lg:col-span-3">
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-5">
                <div className="text-sm font-medium text-zinc-100">Original</div>
                <div className="mt-3 aspect-[4/5] overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950/40">
                  {originalUrl ? (
                    <img
                      src={originalUrl}
                      alt="Original upload"
                      className="h-full w-full object-contain"
                    />
                  ) : (
                    <div className="flex h-full items-center justify-center text-xs text-zinc-500">
                      No image
                    </div>
                  )}
                </div>
              </div>

              <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-5">
                <div className="text-sm font-medium text-zinc-100">Detected lines (boxed)</div>
                <div className="mt-3 aspect-[4/5] overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950/40">
                  {boxedUrl ? (
                    <img
                      src={boxedUrl}
                      alt="Processed with bounding boxes"
                      className="h-full w-full object-contain"
                    />
                  ) : (
                    <div className="flex h-full items-center justify-center text-xs text-zinc-500">
                      Run extraction to see boxed image
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="mt-6 rounded-2xl border border-zinc-800 bg-zinc-900/40 p-5">
              <div className="text-sm font-medium text-zinc-100">Tips</div>
              <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-zinc-300">
                <li>For fastest inference, keep images under ~3000px on the long edge.</li>
                <li>If the backend restarts (reload), the first request may be slower while models load.</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
