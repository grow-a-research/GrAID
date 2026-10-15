import { useEffect, useRef, useState } from 'react'
import { tw, ErrorBox } from '../ui'

export const hasCameraApi =
  typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia

// Same live camera as the teacher's scan tool: rear camera preferred, A4
// alignment guide, optional flash, capture to a JPEG File. Opens on mount and
// always releases the camera on capture, cancel or unmount.
//   onCapture(file) — called with the captured photo
//   onCancel()      — called when the user closes the camera (or it fails)
export default function CameraCapture({ onCapture, onCancel }) {
  const videoRef = useRef(null)
  const canvasRef = useRef(null)
  const streamRef = useRef(null)
  const [ready, setReady] = useState(false)
  const [err, setErr] = useState('')
  const [torchOn, setTorchOn] = useState(false)
  const [torchSupported, setTorchSupported] = useState(false)

  // Torch is switched off with the stream: on some Android devices the LED
  // stays lit if the track is stopped while torch is still applied.
  function stopStream() {
    const track = streamRef.current?.getVideoTracks()[0]
    if (track) {
      try { track.applyConstraints({ advanced: [{ torch: false }] })?.catch(() => {}) } catch { /* ignored */ }
    }
    streamRef.current?.getTracks().forEach(t => t.stop())
    streamRef.current = null
  }

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: 'environment' }, width: { ideal: 3840 }, height: { ideal: 2160 } },
        })
        if (cancelled) { stream.getTracks().forEach(t => t.stop()); return }
        streamRef.current = stream
        if (videoRef.current) videoRef.current.srcObject = stream
        // Torch capability is only reported once the track is live; absent on
        // desktop and iOS Safari, where the button simply never renders.
        const caps = stream.getVideoTracks()[0]?.getCapabilities?.() ?? {}
        setTorchSupported(!!caps.torch)
        setReady(true)
      } catch (e) {
        if (!cancelled) setErr(`Camera error: ${e.message}. Use "Choose photo" instead.`)
      }
    })()
    return () => { cancelled = true; stopStream() }
  }, [])

  async function toggleTorch() {
    const track = streamRef.current?.getVideoTracks()[0]
    if (!track) return
    const next = !torchOn
    try {
      await track.applyConstraints({ advanced: [{ torch: next }] })
      setTorchOn(next)
    } catch (e) {
      setErr(`Could not toggle flash: ${e.message}`)
      setTorchSupported(false)
    }
  }

  function capture() {
    const video = videoRef.current
    const canvas = canvasRef.current
    if (!video || !canvas || !video.videoWidth) return
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    canvas.getContext('2d').drawImage(video, 0, 0)
    canvas.toBlob(blob => {
      if (!blob) return
      const file = new File([blob], `scan_${Date.now()}.jpg`, { type: 'image/jpeg' })
      stopStream()
      onCapture(file)
    }, 'image/jpeg', 0.95)
  }

  function cancel() {
    stopStream()
    onCancel()
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="relative w-full overflow-hidden rounded-lg border border-zinc-700 bg-zinc-950">
        <video ref={videoRef} autoPlay playsInline muted className="block w-full" />
        {/* A4 alignment guide (210:297) */}
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <div className="relative border border-white/50" style={{ aspectRatio: '210/297', height: '82%' }}>
            <span className="absolute left-0 top-0 h-5 w-5 border-l-2 border-t-2 border-white" />
            <span className="absolute right-0 top-0 h-5 w-5 border-r-2 border-t-2 border-white" />
            <span className="absolute bottom-0 left-0 h-5 w-5 border-b-2 border-l-2 border-white" />
            <span className="absolute bottom-0 right-0 h-5 w-5 border-b-2 border-r-2 border-white" />
            <span className="absolute inset-x-0 top-2 select-none text-center text-xs text-white/60">
              Align paper within frame
            </span>
          </div>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <button className={tw.btnPrimary} type="button" onClick={capture} disabled={!ready}>
          {ready ? 'Capture' : 'Starting camera…'}
        </button>
        {torchSupported && (
          <button type="button" onClick={toggleTorch} aria-pressed={torchOn}
            className={torchOn
              ? 'rounded-lg border border-amber-400/60 bg-amber-400/15 px-4 py-2 text-sm text-amber-200 hover:bg-amber-400/25 transition'
              : tw.btnGhost}>
            {torchOn ? 'Flash on' : 'Flash off'}
          </button>
        )}
        <button className={tw.btnGhost} type="button" onClick={cancel}>Cancel</button>
      </div>
      <ErrorBox msg={err} />
      <canvas ref={canvasRef} className="hidden" />
    </div>
  )
}
