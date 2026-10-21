/**
 * A video meeting on the company's own Jitsi server, driven by lib-jitsi-meet with OfficeHub's own interface.
 * The library is served by the Jitsi server through the portal (/jitsi/libs/…), so nothing loads from outside.
 */

import { reactive, shallowRef } from 'vue'

/* eslint-disable @typescript-eslint/no-explicit-any -- lib-jitsi-meet has no type definitions here */
type Track = any
type Conference = any

declare global {
  interface Window {
    JitsiMeetJS?: any
  }
}

export interface JoinInfo {
  meeting_id: number
  title: string
  connection: { room: string; token: string; display_name: string; domain: string; muc: string; websocket: string; library: string }
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
}

export interface ChatLine {
  id: number
  from: string
  text: string
  at: number
  mine: boolean
}

export type MeetingStatus = 'idle' | 'connecting' | 'joined' | 'failed' | 'left'

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

/** One meeting session: connection, conference, the people in it and the chat. */
export function useMeeting() {
  const state = reactive({
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
  })
  const conference = shallowRef<Conference | null>(null)
  let lib: any = null
  let connection: any = null
  let localAudio: Track | null = null
  let localVideo: Track | null = null
  let cameraTrack: Track | null = null
  let chatId = 0

  function tile(id: string): Tile {
    let t = state.tiles.find((x) => x.id === id)
    if (!t) {
      const name = id === 'local' ? '' : conference.value?.getParticipantById(id)?.getDisplayName() ?? ''
      t = reactive({ id, name, local: id === 'local', audio: null, video: null, audioMuted: true, videoMuted: true, screen: false, speaking: false, hand: false })
      state.tiles.push(t)
    }
    return t
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
    lib = await loadLibrary(info.connection.library)
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

    const room = connection.initJitsiConference(c.room, { p2p: { enabled: true }, openBridgeChannel: true })
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
    })
    room.on(ce.CONFERENCE_FAILED, (e: unknown) => {
      state.status = 'failed'
      state.error = String(e)
    })
    room.on(ce.KICKED, () => {
      state.status = 'left'
    })
    await new Promise<void>((resolve) => {
      room.on(ce.CONFERENCE_JOINED, () => resolve())
      room.setDisplayName(displayName)
      for (const track of localTracks) {
        room.addTrack(track)
        if (track.getType() === 'audio') localAudio = track
        else localVideo = cameraTrack = track
        placeTrack(track)
      }
      const me = tile('local')
      me.name = displayName
      room.join()
    })
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

  return { state, join, leave, toggleMic, toggleCam, startShare, stopShare, toggleHand, send }
}
