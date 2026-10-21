/**
 * Record a meeting in the browser, like the recording in Teams but without any server: the meeting area is drawn
 * onto a canvas as it looks on screen, everyone's microphone is mixed in, and the result is a video file
 * (WebM) on this computer. Everyone in the meeting sees that it is being recorded.
 */

const FPS = 25
const WIDTH = 1280
const HEIGHT = 720

export interface Recorder {
  stop(): Promise<Blob>
  seconds(): number
}

export function canRecord(): boolean {
  return typeof MediaRecorder !== 'undefined' && typeof HTMLCanvasElement.prototype.captureStream === 'function'
}

function drawCover(ctx: CanvasRenderingContext2D, video: HTMLVideoElement, x: number, y: number, w: number, h: number, contain: boolean) {
  const vw = video.videoWidth
  const vh = video.videoHeight
  if (!vw || !vh) return
  const scale = contain ? Math.min(w / vw, h / vh) : Math.max(w / vw, h / vh)
  const dw = vw * scale
  const dh = vh * scale
  ctx.save()
  ctx.beginPath()
  ctx.rect(x, y, w, h)
  ctx.clip()
  const mirrored = video.classList.contains('mirror')
  if (mirrored) {
    ctx.translate(x + w, 0)
    ctx.scale(-1, 1)
    ctx.drawImage(video, w - (w - dw) / 2 - dw, y + (h - dh) / 2, dw, dh)
  } else {
    ctx.drawImage(video, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh)
  }
  ctx.restore()
}

/** Start recording what `stage` shows and what `audio()` returns (checked again every few seconds). */
export function startRecording(stage: HTMLElement, audio: () => MediaStreamTrack[]): Recorder {
  const canvas = document.createElement('canvas')
  canvas.width = WIDTH
  canvas.height = HEIGHT
  const ctx = canvas.getContext('2d')!
  const audioContext = new AudioContext()
  const mix = audioContext.createMediaStreamDestination()
  const sources = new Map<string, MediaStreamAudioSourceNode>()
  const startedAt = Date.now()

  function connectAudio() {
    const tracks = audio().filter((t) => t.readyState === 'live')
    for (const track of tracks) {
      if (sources.has(track.id)) continue
      const source = audioContext.createMediaStreamSource(new MediaStream([track]))
      source.connect(mix)
      sources.set(track.id, source)
    }
    for (const [id, source] of sources) {
      if (!tracks.some((t) => t.id === id)) {
        source.disconnect()
        sources.delete(id)
      }
    }
  }

  function frame() {
    const area = stage.getBoundingClientRect()
    ctx.fillStyle = '#0f141c'
    ctx.fillRect(0, 0, WIDTH, HEIGHT)
    if (!area.width || !area.height) return
    const scale = Math.min(WIDTH / area.width, HEIGHT / area.height)
    const offX = (WIDTH - area.width * scale) / 2
    const offY = (HEIGHT - area.height * scale) / 2
    for (const tile of stage.querySelectorAll<HTMLElement>('figure.tile')) {
      const r = tile.getBoundingClientRect()
      const x = offX + (r.left - area.left) * scale
      const y = offY + (r.top - area.top) * scale
      const w = r.width * scale
      const h = r.height * scale
      ctx.fillStyle = '#1f2633'
      ctx.fillRect(x, y, w, h)
      const video = tile.querySelector('video')
      if (video && video.style.display !== 'none' && !video.hidden) drawCover(ctx, video, x, y, w, h, tile.classList.contains('screen'))
      else {
        ctx.fillStyle = '#e5e7eb'
        ctx.font = `600 ${Math.max(14, h / 6)}px system-ui, sans-serif`
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText(tile.querySelector('.initials')?.textContent ?? '', x + w / 2, y + h / 2)
      }
      const name = tile.querySelector('.name span')?.textContent ?? ''
      if (name) {
        ctx.font = `500 ${Math.max(11, h / 16)}px system-ui, sans-serif`
        ctx.textAlign = 'left'
        ctx.textBaseline = 'bottom'
        const padding = 8
        const width = ctx.measureText(name).width + padding * 2
        ctx.fillStyle = 'rgba(0,0,0,0.55)'
        ctx.fillRect(x + 6, y + h - 6 - 22, width, 22)
        ctx.fillStyle = '#fff'
        ctx.fillText(name, x + 6 + padding, y + h - 10)
      }
    }
    // The whiteboard, when it is open
    const board = stage.querySelector<HTMLCanvasElement>('canvas.board')
    if (board) {
      const r = board.getBoundingClientRect()
      ctx.fillStyle = '#fff'
      const x = offX + (r.left - area.left) * scale
      const y = offY + (r.top - area.top) * scale
      ctx.fillRect(x, y, r.width * scale, r.height * scale)
      ctx.drawImage(board, x, y, r.width * scale, r.height * scale)
    }
  }

  connectAudio()
  frame()
  const drawing = window.setInterval(frame, 1000 / FPS)
  const listening = window.setInterval(connectAudio, 2000)
  const stream = new MediaStream([...canvas.captureStream(FPS).getVideoTracks(), ...mix.stream.getAudioTracks()])
  const type = ['video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/webm', 'video/mp4'].find((t) => MediaRecorder.isTypeSupported(t)) ?? ''
  const recorder = new MediaRecorder(stream, type ? { mimeType: type, videoBitsPerSecond: 2_500_000 } : undefined)
  const chunks: Blob[] = []
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data)
  recorder.start(1000)

  return {
    seconds: () => Math.floor((Date.now() - startedAt) / 1000),
    stop: () =>
      new Promise<Blob>((resolve) => {
        recorder.onstop = () => {
          window.clearInterval(drawing)
          window.clearInterval(listening)
          stream.getTracks().forEach((t) => t.stop())
          audioContext.close().catch(() => undefined)
          resolve(new Blob(chunks, { type: recorder.mimeType || 'video/webm' }))
        }
        if (recorder.state !== 'inactive') recorder.stop()
        else recorder.onstop?.(new Event('stop'))
      }),
  }
}
