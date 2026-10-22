/**
 * A video meeting with OfficeHub's own interface. Two ways underneath, chosen by the portal:
 * - built in (lib/rtc.ts): browsers connect directly, no meeting server needed;
 * - the company's own Jitsi server via lib-jitsi-meet, served through the portal (/jitsi/libs/…).
 * Nothing loads from outside either way.
 */

import { reactive, ref, shallowRef } from 'vue'
import type { E2eeGroup, E2eeInfo, E2eeKeys, GroupMember, MediaCrypto, Sender } from './e2ee'
import { builtinSession, createRtcTracks } from './rtc'

/* eslint-disable @typescript-eslint/no-explicit-any -- lib-jitsi-meet has no type definitions here */
type Track = any
type Conference = any

declare global {
  interface Window {
    JitsiMeetJS?: any
  }
}

export type MeetingMode = 'builtin' | 'jitsi'

export interface JoinInfo {
  meeting_id: number
  title: string
  connection: {
    mode: MeetingMode
    room: string
    token: string
    display_name: string
    // Jitsi
    domain?: string
    muc?: string
    websocket?: string
    library?: string
    // built in
    signal?: string
    ice_servers?: RTCIceServer[]
    max_people?: number
    // who I am and whether I lead the meeting (mute everyone, breakout rooms, town hall stage …)
    who?: string
    moderator?: boolean
    town_hall?: boolean
    // end-to-end encrypted: the ticket for the meeting's MLS group
    e2ee?: E2eeInfo
  }
}

export interface Tile {
  id: string
  name: string
  local: boolean
  audio: Track | null
  video: Track | null
  audioMuted: boolean
  videoMuted: boolean
  screen: boolean
  speaking: boolean
  hand: boolean
  who: string // the person behind the tile (same in every room of the meeting)
  mod: boolean // leads the meeting
  reaction: string // a reaction shown for a few seconds
}

/** One line on the whiteboard; points are x,y pairs from 0 to 1000 so every screen size shows the same. */
export interface Stroke {
  id: string
  color: string
  size: number
  points: number[]
}

/** Small messages between the people in a meeting: reactions, whiteboard, moderation. */
export interface AppMessage {
  kind: string
  [key: string]: unknown
}

export type Notice = { key: number; text: string; params?: Record<string, string> }

export interface ChatLine {
  id: number
  from: string
  text: string
  at: number
  mine: boolean
}

export type MeetingStatus = 'idle' | 'connecting' | 'joined' | 'failed' | 'left'

export const JITSI_LIBRARY = '/jitsi/libs/lib-jitsi-meet.min.js'

/** The loudspeaker or headset chosen in the meeting (empty: the computer's default). */
export const speakerId = ref('')

let libraryPromise: Promise<any> | null = null

export function loadLibrary(src: string): Promise<any> {
  if (window.JitsiMeetJS) return Promise.resolve(window.JitsiMeetJS)
  if (!libraryPromise) {
    libraryPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script')
      script.src = src
      script.onload = () => {
        const lib = window.JitsiMeetJS
        if (!lib) return reject(new Error('library'))
        lib.init({ disableAudioLevels: false })
        lib.setLogLevel?.(lib.logLevels?.ERROR ?? 'error')
        resolve(lib)
      }
      script.onerror = () => {
        libraryPromise = null
        reject(new Error('library'))
      }
      document.head.appendChild(script)
    })
  }
  return libraryPromise
}

/** Camera and microphone before joining (the "check your camera" screen). */
export async function createLocalTracks(lib: any, devices: ('audio' | 'video')[], ids: { camera?: string; mic?: string } = {}): Promise<Track[]> {
  try {
    return await lib.createLocalTracks({ devices, cameraDeviceId: ids.camera, micDeviceId: ids.mic })
  } catch {
    // No camera (or it was refused): try with the microphone alone, then nothing
    if (devices.includes('video') && devices.includes('audio')) {
      try {
        return await lib.createLocalTracks({ devices: ['audio'], micDeviceId: ids.mic })
      } catch {
        return []
      }
    }
    return []
  }
}

export async function listDevices(): Promise<{ cameras: MediaDeviceInfo[]; mics: MediaDeviceInfo[]; speakers: MediaDeviceInfo[] }> {
  const all = await navigator.mediaDevices?.enumerateDevices?.().catch(() => []) ?? []
  return {
    cameras: all.filter((d) => d.kind === 'videoinput'),
    mics: all.filter((d) => d.kind === 'audioinput'),
    speakers: all.filter((d) => d.kind === 'audiooutput'),
  }
}

/** Camera and microphone before joining, for the way the meeting will run. */
export async function previewTracks(mode: MeetingMode, devices: ('audio' | 'video')[], ids: { camera?: string; mic?: string } = {}): Promise<Track[]> {
  if (mode === 'builtin') return createRtcTracks(devices, ids)
  return createLocalTracks(await loadLibrary(JITSI_LIBRARY), devices, ids)
}

function newState() {
  return reactive({
    status: 'idle' as MeetingStatus,
    error: '',
    tiles: [] as Tile[],
    chat: [] as ChatLine[],
    unread: 0,
    micOn: true,
    camOn: true,
    sharing: false,
    hand: false,
    dominant: '' as string,
    me: '' as string, // my "who"
    moderator: false,
    townHall: false,
    stage: [] as string[], // town hall: who may speak besides the people leading it
    spotlight: '' as string, // who everyone sees large
    recording: [] as string[], // tile ids of people recording
    strokes: [] as Stroke[],
    boardUnread: 0,
    breakoutsChanged: 0,
    moving: false, // switching to or from a breakout room
    notices: [] as Notice[],
    // end-to-end encryption (null: an ordinary meeting)
    e2ee: null as null | {
      status: 'connecting' | 'secure' | 'failed'
      code: string
      epoch: number
      members: GroupMember[]
      strict: boolean
      problem: string
      problemName: string
    },
  })
}

export type MeetingState = ReturnType<typeof newState>

function tileFinder(state: MeetingState, nameOf: (id: string) => string = () => '') {
  return (id: string, name?: string): Tile => {
    let t = state.tiles.find((x) => x.id === id)
    if (!t) {
      t = reactive({ id, name: name ?? (id === 'local' ? '' : nameOf(id)), local: id === 'local', audio: null, video: null, audioMuted: true, videoMuted: true, screen: false, speaking: false, hand: false, who: '', mod: false, reaction: '' })
      state.tiles.push(t)
    } else if (name) {
      t.name = name
    }
    return t
  }
}

type Session = ReturnType<typeof builtinSession>

/** Kinds that carry content: in an end-to-end encrypted meeting they travel only MLS-encrypted. */
const SEALED_KINDS = new Set(['react', 'wb', 'wb-clear', 'wb-all'])

/** Kinds that only count when they come from someone leading the meeting (the server checks this too). */
const MOD_KINDS = new Set(['mute', 'mute-all', 'spotlight', 'stage', 'lower-hand', 'sync', 'breakouts'])
const REACTION_MS = 4000
let noticeKey = 0

function notice(state: MeetingState, text: string, params?: Record<string, string>) {
  state.notices.push({ key: ++noticeKey, text, params })
}

/** One meeting: the people in it, the chat and the controls; the way underneath follows the join info. */
export function useMeeting() {
  const state = newState()
  let session: Session | null = null
  let info: JoinInfo | null = null
  let group: E2eeGroup | null = null
  let media: MediaCrypto | null = null
  let sealedChat = 0
  const run = <K extends keyof Session>(key: K) => ((...args: Parameters<Session[K]>) => (session?.[key] as (...a: unknown[]) => unknown)?.(...args)) as Session[K]
  const tile = (id: string) => state.tiles.find((t) => t.id === id)
  const app = (message: AppMessage, to?: string) => {
    if (group && SEALED_KINDS.has(message.kind)) {
      group.seal({ app: message, to: to ?? '', peer: session?.selfId() ?? '' }).catch(() => undefined)
      return
    }
    session?.app(message, to)
  }

  /** A message from the encrypted group: a chat line, or a reaction / whiteboard stroke from someone's tile. */
  function onSealed(payload: Record<string, unknown>, from: Sender) {
    if (typeof payload.chat === 'string') {
      state.chat.push({ id: 1_000_000 + ++sealedChat, from: from.name || '?', text: payload.chat.slice(0, 1000), at: Date.now(), mine: false })
      state.unread += 1
      return
    }
    const message = payload.app as AppMessage | undefined
    if (!message || typeof message.kind !== 'string' || !SEALED_KINDS.has(message.kind)) return
    if (payload.to && payload.to !== session?.selfId()) return
    const peer = String(payload.peer ?? '')
    // The tile must belong to the person who encrypted the message
    if (tile(peer)?.who && tile(peer)?.who !== from.who) return
    onApp(peer, message)
  }

  function send(text: string) {
    const body = text.trim()
    if (!body) return
    if (!group) return session?.send(body)
    group.seal({ chat: body }).catch(() => undefined)
    state.chat.push({ id: 1_000_000 + ++sealedChat, from: tile('local')?.name ?? '', text: body, at: Date.now(), mine: true })
  }

  /** In a town hall, people in the audience listen until someone leading it brings them on stage. */
  const mayTalk = () => !state.townHall || state.moderator || state.stage.includes(state.me)

  async function silence() {
    if (state.micOn) await session?.toggleMic()
    if (state.camOn) await session?.toggleCam()
    if (state.sharing) await session?.stopShare()
  }

  function onApp(from: string, m: AppMessage) {
    const sender = tile(from)
    if (MOD_KINDS.has(m.kind) && !sender?.mod) return
    const name = sender?.name ?? ''
    switch (m.kind) {
      case 'react': {
        if (!sender || typeof m.emoji !== 'string') return
        sender.reaction = m.emoji.slice(0, 8)
        const shown = sender.reaction
        window.setTimeout(() => sender.reaction === shown && (sender.reaction = ''), REACTION_MS)
        break
      }
      case 'wb':
        if (isStroke(m.stroke) && !state.strokes.some((x) => x.id === (m.stroke as Stroke).id)) {
          state.strokes.push(m.stroke as Stroke)
          state.boardUnread += 1
        }
        break
      case 'wb-clear':
        state.strokes = []
        break
      case 'wb-req':
        sendBoard(from)
        break
      case 'wb-all':
        for (const stroke of Array.isArray(m.strokes) ? m.strokes : []) {
          if (isStroke(stroke) && !state.strokes.some((x) => x.id === stroke.id)) state.strokes.push(stroke)
        }
        break
      case 'rec':
        state.recording = state.recording.filter((id) => id !== from)
        if (m.on) {
          state.recording.push(from)
          notice(state, 'meeting.recordingStarted', { name })
        }
        break
      case 'sync-req':
        if (state.moderator) app({ kind: 'sync', spotlight: state.spotlight, stage: state.stage }, from)
        if (state.recording.includes('local')) app({ kind: 'rec', on: true }, from)
        break
      case 'mute':
        if (m.to !== state.me) return
      // falls through
      case 'mute-all':
        if (state.moderator && m.kind === 'mute-all') return
        if (state.micOn) {
          session?.toggleMic()
          notice(state, 'meeting.mutedBy', { name })
        }
        break
      case 'lower-hand':
        if ((m.to === state.me || !m.to) && state.hand) session?.toggleHand()
        break
      case 'spotlight':
      case 'sync':
        state.spotlight = typeof m.spotlight === 'string' ? m.spotlight : ''
        if (m.kind === 'spotlight') break
      // falls through (sync also carries the stage)
      case 'stage': {
        const before = mayTalk()
        state.stage = Array.isArray(m.stage) ? m.stage.map(String) : []
        if (state.townHall && !state.moderator) {
          if (!before && mayTalk()) notice(state, 'meeting.onStage')
          if (before && !mayTalk()) {
            silence()
            if (m.kind === 'stage') notice(state, 'meeting.offStage')
          }
        }
        break
      }
      case 'breakouts':
        state.breakoutsChanged += 1
        break
    }
  }

  /** The whiteboard for someone who joined later, in parts small enough for one message. */
  function sendBoard(to: string) {
    for (let i = 0; i < state.strokes.length; i += 40) app({ kind: 'wb-all', strokes: state.strokes.slice(i, i + 40) }, to)
  }

  async function start(joinInfo: JoinInfo, localTracks: Track[], displayName: string) {
    info = joinInfo
    const c = joinInfo.connection
    state.me = c.who ?? ''
    state.moderator = !!c.moderator
    state.townHall = !!c.town_hall
    state.e2ee = null
    if (c.e2ee) {
      const e2ee = await import('./e2ee')
      if (!e2ee.e2eeSupported()) {
        state.status = 'failed'
        state.error = 'e2ee_unsupported'
        for (const track of localTracks) track.dispose?.()
        throw Object.assign(new Error('e2ee_unsupported'), { code: 'e2ee_unsupported' })
      }
      // Who this browser is: its device key (people) or a key for this visit only (guests)
      const who = c.who ?? ''
      const device = /^\d+$/.test(who) ? await e2ee.myDevice(who) : await e2ee.guestDevice(who)
      const refuse = (code: string) => {
        state.status = 'failed'
        state.error = code
        for (const track of localTracks) track.dispose?.()
        throw Object.assign(new Error(code), { code })
      }
      if (!device) refuse('e2ee_unsupported')
      if (c.e2ee.policy === 'strict' && device!.pending && /^\d+$/.test(who)) refuse('e2ee_device_unconfirmed')
      const book = await e2ee.Trustbook.load(who)
      media = c.mode === 'builtin' ? new e2ee.MediaCrypto() : null
      group = new e2ee.E2eeGroup(
        c.e2ee,
        { device: device!, book },
        (keys: E2eeKeys) => {
          media?.setKeys(keys)
          session?.setMediaKeys?.(keys)
        },
        onSealed,
        () => {
          // Someone's key is not theirs (or not confirmed under the strict rule): no more sound or picture here
          media?.stop()
          void session?.leave()
        },
      )
      state.e2ee = group.view
    }
    session = c.mode === 'builtin' ? builtinSession(state, tileFinder(state), onApp, media) : jitsiSession(state, onApp, !!c.e2ee)
    const tracks = mayTalk() ? localTracks : []
    if (!mayTalk()) for (const track of localTracks) track.dispose?.()
    await group?.start()
    await session.join(joinInfo, tracks, displayName)
    const me = tileFinder(state)('local')
    me.who = state.me
    me.mod = state.moderator
    app({ kind: 'sync-req' })
    app({ kind: 'wb-req' })
  }

  return {
    state,
    mayTalk,
    get info() {
      return info
    },
    join: start,
    /** After checking someone's security number in person: show them as confirmed */
    recheckTrust: () => group?.recheck(),
    leave: async () => {
      group?.stop()
      media?.stop()
      group = media = null
      await session?.leave()
    },
    /** Go to a breakout room (or back): leave this room and join the other with fresh camera and microphone. */
    async move(next: JoinInfo, localTracks: Track[], displayName: string) {
      state.moving = true
      try {
        group?.stop()
        media?.stop()
        group = media = null
        await session?.leave()
        state.strokes = []
        state.spotlight = ''
        state.stage = []
        state.recording = state.recording.filter((id) => id === 'local')
        await start(next, localTracks, displayName)
      } finally {
        state.moving = false
      }
    },
    toggleMic: async () => {
      if (!state.micOn && !mayTalk()) return notice(state, 'meeting.audienceOnly')
      await session?.toggleMic()
    },
    toggleCam: async () => {
      if (!state.camOn && !mayTalk()) return notice(state, 'meeting.audienceOnly')
      await session?.toggleCam()
    },
    startShare: async () => {
      if (!mayTalk()) return notice(state, 'meeting.audienceOnly')
      await session?.startShare()
    },
    stopShare: run('stopShare'),
    toggleHand: run('toggleHand'),
    send,
    setNoiseSuppression: run('setNoiseSuppression'),
    audioTracks: () => session?.audioTracks() ?? [],
    react(emoji: string) {
      const me = tile('local')
      if (me) {
        me.reaction = emoji
        window.setTimeout(() => me.reaction === emoji && (me.reaction = ''), REACTION_MS)
      }
      app({ kind: 'react', emoji })
    },
    draw(stroke: Stroke) {
      state.strokes.push(stroke)
      app({ kind: 'wb', stroke })
    },
    clearBoard() {
      state.strokes = []
      app({ kind: 'wb-clear' })
    },
    setRecording(on: boolean) {
      state.recording = state.recording.filter((id) => id !== 'local')
      if (on) state.recording.push('local')
      app({ kind: 'rec', on })
    },
    // ---------- for the people leading the meeting ----------
    muteAll: () => app({ kind: 'mute-all' }),
    mute: (t: Tile) => session?.forceMute(t.id, t.who),
    lowerHand: (t: Tile) => app({ kind: 'lower-hand', to: t.who }),
    remove: (t: Tile) => session?.remove(t.id),
    setSpotlight(who: string) {
      state.spotlight = who
      app({ kind: 'spotlight', spotlight: who })
    },
    setStage(who: string, on: boolean) {
      state.stage = on ? [...new Set([...state.stage, who])] : state.stage.filter((w) => w !== who)
      app({ kind: 'stage', stage: state.stage })
    },
    breakoutsChanged: () => app({ kind: 'breakouts' }),
  }
}

function isStroke(value: unknown): value is Stroke {
  const s = value as Stroke
  return !!s && typeof s.id === 'string' && typeof s.color === 'string' && /^#[0-9a-f]{6}$/i.test(s.color)
    && typeof s.size === 'number' && Array.isArray(s.points) && s.points.length <= 4000 && s.points.every((n) => typeof n === 'number')
}

/** `encrypted`: the meeting is end-to-end encrypted; the keys come from its MLS group (setMediaKeys) and the
 * Jitsi server's own frame encryption uses them (lib-jitsi-meet, externally managed key). */
function jitsiSession(state: MeetingState, onApp: (from: string, message: AppMessage) => void, encrypted = false) {
  const conference = shallowRef<Conference | null>(null)
  let keyed: () => void = () => undefined
  const firstKey = new Promise<void>((resolve) => (keyed = resolve))
  let lib: any = null
  let connection: any = null
  let localAudio: Track | null = null
  let localVideo: Track | null = null
  let cameraTrack: Track | null = null
  let chatId = 0

  const tile = tileFinder(state, (id) => conference.value?.getParticipantById(id)?.getDisplayName() ?? '')

  /** Who someone is and whether they lead the meeting: shared as participant properties. Only Jitsi moderators
   * (people with an account; guests never are) can lead, so a guest cannot pretend to. */
  function roles(participant: any) {
    const t = tile(participant.getId())
    t.who = participant.getProperty?.('ohwho') ?? t.who
    t.mod = participant.getRole?.() === 'moderator' && participant.getProperty?.('ohmod') === 'true'
  }

  function placeTrack(track: Track) {
    const id = track.isLocal() ? 'local' : track.getParticipantId()
    const t = tile(id)
    if (track.getType() === 'audio') {
      t.audio = track
      t.audioMuted = track.isMuted()
    } else {
      t.video = track
      t.videoMuted = track.isMuted()
      t.screen = track.videoType === 'desktop'
    }
  }

  async function join(info: JoinInfo, localTracks: Track[], displayName: string) {
    state.status = 'connecting'
    state.error = ''
    lib = await loadLibrary(info.connection.library ?? JITSI_LIBRARY)
    const c = info.connection
    const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const options = {
      hosts: { domain: c.domain, muc: c.muc },
      serviceUrl: `${scheme}://${window.location.host}${c.websocket}?room=${encodeURIComponent(c.room)}`,
    }
    connection = new lib.JitsiConnection(null, c.token, options)
    const events = lib.events
    await new Promise<void>((resolve, reject) => {
      connection.addEventListener(events.connection.CONNECTION_ESTABLISHED, () => resolve())
      connection.addEventListener(events.connection.CONNECTION_FAILED, (e: unknown) => reject(new Error(String(e))))
      connection.connect()
    }).catch((e) => {
      state.status = 'failed'
      state.error = String(e)
      throw e
    })
    connection.addEventListener(events.connection.CONNECTION_DISCONNECTED, () => {
      if (state.status === 'joined') state.status = 'left'
    })

    // Everything goes through the company's videobridge, also calls between two people (no direct connection)
    const room = connection.initJitsiConference(c.room, {
      p2p: { enabled: false },
      openBridgeChannel: true,
      ...(encrypted ? { e2ee: { externallyManagedKey: true }, enableEncodedTransformSupport: true } : {}),
    })
    conference.value = room
    const ce = events.conference
    room.on(ce.TRACK_ADDED, (track: Track) => {
      if (!track.isLocal()) placeTrack(track)
    })
    room.on(ce.TRACK_REMOVED, (track: Track) => {
      const t = state.tiles.find((x) => x.audio === track || x.video === track)
      if (!t) return
      if (t.audio === track) t.audio = null
      if (t.video === track) t.video = null
    })
    room.on(ce.TRACK_MUTE_CHANGED, (track: Track) => {
      const id = track.isLocal() ? 'local' : track.getParticipantId()
      const t = state.tiles.find((x) => x.id === id)
      if (!t) return
      if (track.getType() === 'audio') t.audioMuted = track.isMuted()
      else t.videoMuted = track.isMuted()
    })
    room.on(ce.USER_JOINED, (id: string, user: any) => {
      tile(id).name = user.getDisplayName() ?? ''
      roles(user)
    })
    room.on(ce.USER_ROLE_CHANGED, (id: string) => {
      const participant = room.getParticipantById(id)
      if (participant) roles(participant)
    })
    room.on(ce.ENDPOINT_MESSAGE_RECEIVED, (participant: any, payload: any) => {
      const message = payload?.officehub
      if (!participant || participant.getId?.() === room.myUserId() || !message || typeof message.kind !== 'string') return
      roles(participant)
      onApp(participant.getId(), message)
    })
    room.on(ce.DISPLAY_NAME_CHANGED, (id: string, name: string) => {
      tile(id).name = name
    })
    room.on(ce.USER_LEFT, (id: string) => {
      state.tiles = state.tiles.filter((t) => t.id !== id)
    })
    room.on(ce.DOMINANT_SPEAKER_CHANGED, (id: string) => {
      state.dominant = id
      for (const t of state.tiles) t.speaking = t.id === id || (t.local && id === room.myUserId())
    })
    room.on(ce.MESSAGE_RECEIVED, (id: string, text: string, ts?: number) => {
      const from = state.tiles.find((t) => t.id === id)?.name || '?'
      state.chat.push({ id: ++chatId, from, text, at: ts ? Number(ts) : Date.now(), mine: false })
      state.unread += 1
    })
    room.on(ce.PARTICIPANT_PROPERTY_CHANGED, (participant: any, name: string, _old: unknown, value: string) => {
      if (name === 'raisedHand') tile(participant.getId()).hand = value === 'true'
      if (name === 'ohwho' || name === 'ohmod') roles(participant)
    })
    room.on(ce.CONFERENCE_FAILED, (e: unknown) => {
      state.status = 'failed'
      state.error = String(e)
    })
    room.on(ce.KICKED, () => {
      state.notices.push({ key: Date.now(), text: 'meeting.removed' })
      state.status = 'left'
    })
    await new Promise<void>((resolve) => {
      room.on(ce.CONFERENCE_JOINED, () => resolve())
      room.setDisplayName(displayName)
      for (const track of localTracks) {
        // Encrypted: nothing is sent before the first key is set (below)
        if (!encrypted) room.addTrack(track)
        if (track.getType() === 'audio') localAudio = track
        else localVideo = cameraTrack = track
        placeTrack(track)
      }
      const me = tile('local')
      me.name = displayName
      room.setLocalParticipantProperty?.('ohwho', info.connection.who ?? '')
      room.setLocalParticipantProperty?.('ohmod', String(!!info.connection.moderator))
      room.join()
    })
    if (encrypted) {
      if (!room.isE2EESupported?.()) {
        state.status = 'failed'
        state.error = 'e2ee_unsupported'
        await leave()
        throw Object.assign(new Error('e2ee_unsupported'), { code: 'e2ee_unsupported' })
      }
      room.toggleE2EE(true)
      await firstKey
      for (const track of [localAudio, localVideo]) if (track) await room.addTrack(track)
    }
    state.micOn = !!localAudio && !localAudio.isMuted()
    state.camOn = !!localVideo && !localVideo.isMuted()
    state.status = 'joined'
  }

  async function toggleMic() {
    if (!localAudio) {
      const [track] = await createLocalTracks(lib, ['audio'])
      if (!track) return
      localAudio = track
      await conference.value?.addTrack(track)
      placeTrack(track)
    } else if (localAudio.isMuted()) {
      await localAudio.unmute()
    } else {
      await localAudio.mute()
    }
    state.micOn = !localAudio.isMuted()
    tile('local').audioMuted = localAudio.isMuted()
  }

  async function toggleCam() {
    if (state.sharing) await stopShare()
    if (!localVideo) {
      const [track] = await createLocalTracks(lib, ['video'])
      if (!track) return
      localVideo = cameraTrack = track
      await conference.value?.addTrack(track)
      placeTrack(track)
    } else if (localVideo.isMuted()) {
      await localVideo.unmute()
    } else {
      await localVideo.mute()
    }
    state.camOn = !localVideo.isMuted()
    tile('local').videoMuted = localVideo.isMuted()
  }

  async function startShare() {
    let desktop: Track
    try {
      ;[desktop] = await lib.createLocalTracks({ devices: ['desktop'] })
    } catch {
      return // cancelled in the browser's picker
    }
    if (!desktop) return
    desktop.addEventListener?.(lib.events.track.LOCAL_TRACK_STOPPED, () => stopShare())
    await conference.value?.replaceTrack(localVideo, desktop)
    localVideo = desktop
    placeTrack(desktop)
    state.sharing = true
  }

  async function stopShare() {
    if (!state.sharing) return
    const desktop = localVideo
    await conference.value?.replaceTrack(desktop, cameraTrack ?? null)
    desktop?.dispose?.()
    localVideo = cameraTrack
    const me = tile('local')
    me.video = cameraTrack
    me.screen = false
    me.videoMuted = cameraTrack ? cameraTrack.isMuted() : true
    state.sharing = false
  }

  function toggleHand() {
    state.hand = !state.hand
    tile('local').hand = state.hand
    conference.value?.setLocalParticipantProperty?.('raisedHand', String(state.hand))
  }

  function send(text: string) {
    const body = text.trim()
    if (!body || !conference.value) return
    conference.value.sendTextMessage(body)
    state.chat.push({ id: ++chatId, from: tile('local').name, text: body, at: Date.now(), mine: true })
  }

  /** Reactions, whiteboard and moderation go as JSON messages through the meeting server. */
  function app(message: AppMessage, to?: string) {
    try {
      conference.value?.sendMessage({ officehub: message }, to ?? '')
    } catch {
      /* not connected */
    }
  }

  function remove(id: string) {
    conference.value?.kickParticipant?.(id)
  }

  function forceMute(id: string, who: string) {
    conference.value?.muteParticipant?.(id, 'audio')
    app({ kind: 'mute', to: who })
  }

  async function setNoiseSuppression(on: boolean) {
    await localAudio?.getTrack?.()?.applyConstraints({ noiseSuppression: on, echoCancellation: true, autoGainControl: on }).catch(() => undefined)
  }

  function audioTracks(): MediaStreamTrack[] {
    return state.tiles.map((t) => t.audio?.getTrack?.()).filter(Boolean)
  }

  async function leave() {
    try {
      await conference.value?.leave()
    } catch {
      /* already gone */
    }
    for (const track of [localAudio, localVideo, cameraTrack]) track?.dispose?.()
    localAudio = localVideo = cameraTrack = null
    connection?.disconnect()
    connection = null
    conference.value = null
    state.tiles = []
    state.status = 'left'
  }

  async function setMediaKeys(keys: E2eeKeys) {
    const encryptionKey = await crypto.subtle.importKey('raw', keys.shared as BufferSource, 'AES-GCM', false, ['encrypt', 'decrypt'])
    conference.value?.setMediaEncryptionKey?.({ encryptionKey, index: keys.epoch % 16 })
    keyed()
  }

  return {
    join, leave, toggleMic, toggleCam, startShare, stopShare, toggleHand, send, app, remove, forceMute, setNoiseSuppression, audioTracks,
    selfId: () => (conference.value?.myUserId?.() as string | undefined) ?? '',
    setMediaKeys: (keys: E2eeKeys) => void setMediaKeys(keys),
  }
}
