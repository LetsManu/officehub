/**
 * Built-in meetings: no meeting server needed. OfficeHub introduces the browsers to each other (/api/rtc),
 * then audio and video go directly between them (WebRTC). Each person sends to each other person, so this
 * is meant for calls and smaller meetings; with the company's own Jitsi server larger ones work too.
 */

import type { ChatLine, JoinInfo, MeetingState, Tile } from './meeting'

type Kind = 'audio' | 'video'

/** A camera, microphone or screen, local or from someone else, with the same methods VideoTile uses. */
export class RtcTrack {
  constructor(
    public track: MediaStreamTrack,
    private local: boolean,
    private participant = 'local',
    public videoType: 'camera' | 'desktop' = 'camera',
  ) {}

  getType(): Kind {
    return this.track.kind as Kind
  }

  isLocal() {
    return this.local
  }

  getParticipantId() {
    return this.participant
  }

  isMuted() {
    return !this.track.enabled || this.track.readyState === 'ended'
  }

  async mute() {
    this.track.enabled = false
  }

  async unmute() {
    this.track.enabled = true
  }

  attach(el: HTMLMediaElement) {
    el.srcObject = new MediaStream([this.track])
    el.play?.().catch(() => undefined)
  }

  detach(el: HTMLMediaElement) {
    el.srcObject = null
  }

  dispose() {
    if (this.local) this.track.stop()
  }
}

/** Camera and/or microphone; falls back to the microphone alone, then nothing. */
export async function createRtcTracks(devices: Kind[], ids: { camera?: string; mic?: string } = {}): Promise<RtcTrack[]> {
  const ask = (audio: boolean, video: boolean) =>
    navigator.mediaDevices.getUserMedia({
      audio: audio ? (ids.mic ? { deviceId: { exact: ids.mic }, echoCancellation: true } : { echoCancellation: true }) : false,
      video: video ? { ...(ids.camera ? { deviceId: { exact: ids.camera } } : {}), width: { ideal: 1280 }, height: { ideal: 720 } } : false,
    })
  const audio = devices.includes('audio')
  const video = devices.includes('video')
  let stream: MediaStream | null = null
  try {
    stream = await ask(audio, video)
  } catch {
    if (audio && video) stream = await ask(true, false).catch(() => null)
  }
  return stream ? stream.getTracks().map((t) => new RtcTrack(t, true)) : []
}

interface Message {
  seq: number
  type: 'join' | 'leave' | 'signal' | 'state' | 'chat'
  from: string
  data: Record<string, unknown>
}

interface PeerState {
  audioMuted?: boolean
  videoMuted?: boolean
  hand?: boolean
  screen?: boolean
  name?: string
}

interface Link {
  pc: RTCPeerConnection
  pending: RTCIceCandidateInit[]
  initiator: boolean
}

class RtcError extends Error {
  constructor(public status: number, public code: string) {
    super(code)
  }
}

const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms))

export function builtinSession(state: MeetingState, tile: (id: string, name?: string) => Tile) {
  let base = '/api/rtc'
  let token = ''
  let peerId = ''
  let ice: RTCIceServer[] = []
  let cursor = 0
  let active = false
  let chatId = 0
  let audio: RtcTrack | null = null
  let video: RtcTrack | null = null
  let camera: RtcTrack | null = null
  let levels: number | undefined
  let audioContext: AudioContext | null = null
  const meters = new Map<string, { analyser: AnalyserNode; data: Uint8Array; track: MediaStreamTrack }>()
  const links = new Map<string, Link>()

  async function call<T>(path: string, body: Record<string, unknown> = {}, keepalive = false): Promise<T> {
    const response = await fetch(`${base}${path}`, {
      method: 'POST',
      keepalive,
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'OfficeHub', 'X-Meeting-Token': token },
      body: JSON.stringify({ peer_id: peerId, ...body }),
    })
    if (response.status === 204) return null as T
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new RtcError(response.status, data.code ?? 'rtc')
    return data as T
  }

  function myState(): PeerState {
    return { audioMuted: !state.micOn, videoMuted: !state.camOn, hand: state.hand, screen: state.sharing, name: tile('local').name }
  }

  function sendState(to: string | null = null) {
    call('/send', { to, type: 'state', data: myState() }).catch(() => undefined)
  }

  function applyState(id: string, s: PeerState) {
    const t = tile(id)
    t.audioMuted = !!s.audioMuted
    t.videoMuted = !!s.videoMuted
    t.hand = !!s.hand
    t.screen = !!s.screen
    if (s.name) t.name = s.name
  }

  function signal(to: string, data: Record<string, unknown>) {
    call('/send', { to, type: 'signal', data }).catch(() => undefined)
  }

  /** Put the current microphone and camera (or screen) on every connection without asking anew. */
  function attachSenders(pc: RTCPeerConnection) {
    for (const transceiver of pc.getTransceivers()) {
      const kind = transceiver.receiver.track.kind
      transceiver.direction = 'sendrecv'
      transceiver.sender.replaceTrack(kind === 'audio' ? audio?.track ?? null : video?.track ?? null).catch(() => undefined)
    }
  }

  function replaceKind(kind: Kind, track: MediaStreamTrack | null) {
    for (const { pc } of links.values()) {
      for (const transceiver of pc.getTransceivers()) {
        if (transceiver.receiver.track.kind === kind) transceiver.sender.replaceTrack(track).catch(() => undefined)
      }
    }
  }

  function link(id: string, initiator: boolean): Link {
    const pc = new RTCPeerConnection({ iceServers: ice })
    const entry: Link = { pc, pending: [], initiator }
    links.set(id, entry)
    if (initiator) {
      pc.addTransceiver('audio', { direction: 'sendrecv' })
      pc.addTransceiver('video', { direction: 'sendrecv' })
      attachSenders(pc)
    }
    pc.onicecandidate = (event) => {
      if (event.candidate) signal(id, { candidate: event.candidate.toJSON() })
    }
    pc.ontrack = (event) => {
      const t = tile(id)
      const remote = new RtcTrack(event.track, false, id)
      if (event.track.kind === 'audio') t.audio = remote
      else t.video = remote
    }
    pc.onconnectionstatechange = () => {
      // Network changed (e.g. Wi-Fi to cable): the one who called starts over
      if (pc.connectionState === 'failed' && entry.initiator && active) offer(id, true).catch(() => undefined)
    }
    return entry
  }

  async function offer(id: string, iceRestart = false) {
    const { pc } = links.get(id) ?? link(id, true)
    const description = await pc.createOffer({ iceRestart })
    await pc.setLocalDescription(description)
    signal(id, { sdp: pc.localDescription?.toJSON() })
  }

  async function onSignal(from: string, data: { sdp?: RTCSessionDescriptionInit; candidate?: RTCIceCandidateInit }) {
    let entry = links.get(from)
    if (data.sdp) {
      if (data.sdp.type === 'offer') {
        entry ??= link(from, false)
        await entry.pc.setRemoteDescription(data.sdp)
        attachSenders(entry.pc)
        const answer = await entry.pc.createAnswer()
        await entry.pc.setLocalDescription(answer)
        signal(from, { sdp: entry.pc.localDescription?.toJSON() })
      } else if (entry) {
        await entry.pc.setRemoteDescription(data.sdp)
      }
      for (const candidate of entry?.pending.splice(0) ?? []) await entry!.pc.addIceCandidate(candidate).catch(() => undefined)
    } else if (data.candidate && entry) {
      if (entry.pc.remoteDescription) await entry.pc.addIceCandidate(data.candidate).catch(() => undefined)
      else entry.pending.push(data.candidate)
    }
  }

  function drop(id: string) {
    links.get(id)?.pc.close()
    links.delete(id)
    meters.delete(id)
    state.tiles = state.tiles.filter((t) => t.id !== id)
  }

  async function handle(message: Message) {
    const data = message.data
    if (message.type === 'join') {
      tile(message.from, String(data.name ?? ''))
      applyState(message.from, (data.state ?? {}) as PeerState)
    } else if (message.type === 'leave') {
      drop(message.from)
    } else if (message.type === 'signal') {
      await onSignal(message.from, data).catch(() => undefined)
    } else if (message.type === 'state') {
      applyState(message.from, data as PeerState)
    } else if (message.type === 'chat') {
      const from = state.tiles.find((t) => t.id === message.from)?.name || '?'
      state.chat.push({ id: ++chatId, from, text: String(data.text ?? ''), at: Date.now(), mine: false } satisfies ChatLine)
      state.unread += 1
    }
  }

  async function hello() {
    const reply = await call<{ peer_id: string; peers: { id: string; name: string; state: PeerState }[] }>('/hello')
    peerId = reply.peer_id
    cursor = 0
    for (const p of reply.peers) {
      tile(p.id, p.name)
      applyState(p.id, p.state)
      await offer(p.id)
    }
    sendState()
  }

  async function loop() {
    while (active) {
      try {
        const reply = await call<{ messages: Message[] }>('/poll', { after: cursor })
        for (const message of reply.messages) {
          cursor = message.seq
          await handle(message)
        }
      } catch (e) {
        if (!active) break
        if (e instanceof RtcError && (e.status === 410 || e.status === 401)) {
          // The portal was restarted: say hello again and reconnect everyone
          for (const id of [...links.keys()]) drop(id)
          await sleep(500)
          await hello().catch(() => sleep(2000))
        } else {
          await sleep(2000)
        }
      }
    }
  }

  /** Who is talking: a soft ring around the tile of everyone who is louder than a whisper. */
  function watchLevels() {
    try {
      audioContext ??= new AudioContext()
      audioContext.resume().catch(() => undefined)
    } catch {
      return
    }
    levels = window.setInterval(() => {
      let loudest = ''
      let top = 0
      for (const t of state.tiles) {
        const track = (t.local ? audio : t.audio) as RtcTrack | null
        if (!track || t.audioMuted) {
          t.speaking = false
          continue
        }
        let meter = meters.get(t.id)
        if (!meter || meter.track !== track.track) {
          const analyser = audioContext!.createAnalyser()
          analyser.fftSize = 256
          audioContext!.createMediaStreamSource(new MediaStream([track.track])).connect(analyser)
          meter = { analyser, data: new Uint8Array(analyser.fftSize), track: track.track }
          meters.set(t.id, meter)
        }
        meter.analyser.getByteTimeDomainData(meter.data)
        let sum = 0
        for (const v of meter.data) sum += ((v - 128) / 128) ** 2
        const level = Math.sqrt(sum / meter.data.length)
        t.speaking = level > 0.03
        if (level > top) {
          top = level
          loudest = t.id
        }
      }
      if (top > 0.03) state.dominant = loudest
    }, 300)
  }

  async function join(info: JoinInfo, localTracks: RtcTrack[], displayName: string) {
    const c = info.connection
    state.status = 'connecting'
    state.error = ''
    base = c.signal ?? base
    token = c.token
    ice = c.ice_servers ?? []
    const me = tile('local', displayName)
    for (const track of localTracks) {
      if (track.getType() === 'audio') {
        audio = track
        me.audio = track
      } else {
        video = camera = track
        me.video = track
      }
    }
    state.micOn = !!audio && !audio.isMuted()
    state.camOn = !!video
    me.audioMuted = !state.micOn
    me.videoMuted = !state.camOn
    try {
      await hello()
    } catch (e) {
      state.status = 'failed'
      state.error = e instanceof RtcError ? e.code : String(e)
      throw e
    }
    active = true
    loop()
    watchLevels()
    state.status = 'joined'
  }

  async function toggleMic() {
    if (!audio) {
      const [track] = await createRtcTracks(['audio'])
      if (!track) return
      audio = track
      tile('local').audio = track
      replaceKind('audio', track.track)
    } else {
      audio.track.enabled = !audio.track.enabled
    }
    state.micOn = audio.track.enabled
    tile('local').audioMuted = !state.micOn
    sendState()
  }

  async function toggleCam() {
    if (state.sharing) await stopShare()
    const me = tile('local')
    if (state.camOn && camera) {
      // Switch the camera off completely (its light goes out)
      camera.dispose()
      video = camera = null
      replaceKind('video', null)
      me.video = null
      state.camOn = false
    } else {
      const [track] = await createRtcTracks(['video'])
      if (!track || track.getType() !== 'video') return
      video = camera = track
      replaceKind('video', track.track)
      me.video = track
      state.camOn = true
    }
    me.videoMuted = !state.camOn
    sendState()
  }

  async function startShare() {
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false })
    } catch {
      return // cancelled in the browser's picker
    }
    const [track] = stream.getVideoTracks()
    if (!track) return
    track.onended = () => stopShare()
    const screen = new RtcTrack(track, true, 'local', 'desktop')
    video = screen
    replaceKind('video', track)
    const me = tile('local')
    me.video = screen
    me.screen = true
    me.videoMuted = false
    state.sharing = true
    sendState()
  }

  async function stopShare() {
    if (!state.sharing) return
    video?.dispose()
    video = camera
    replaceKind('video', camera?.track ?? null)
    const me = tile('local')
    me.video = camera
    me.screen = false
    me.videoMuted = !camera
    state.sharing = false
    sendState()
  }

  function toggleHand() {
    state.hand = !state.hand
    tile('local').hand = state.hand
    sendState()
  }

  function send(text: string) {
    const body = text.trim()
    if (!body) return
    call('/send', { type: 'chat', data: { text: body } }).catch(() => undefined)
    state.chat.push({ id: ++chatId, from: tile('local').name, text: body, at: Date.now(), mine: true })
  }

  async function leave() {
    if (active && peerId) call('/bye', {}, true).catch(() => undefined)
    active = false
    window.clearInterval(levels)
    for (const id of [...links.keys()]) drop(id)
    for (const track of [audio, video, camera]) track?.dispose()
    audio = video = camera = null
    audioContext?.close().catch(() => undefined)
    audioContext = null
    meters.clear()
    state.tiles = []
    state.status = 'left'
  }

  return { join, leave, toggleMic, toggleCam, startShare, stopShare, toggleHand, send }
}
