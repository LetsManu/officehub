<script setup lang="ts">
/**
 * OfficeHub's own meeting screen (built in, or on the company's Jitsi server): check camera, microphone and
 * loudspeaker, then the video grid with controls like in Teams and Webex – reactions, gallery or speaker view,
 * picture-in-picture, whiteboard, recording, breakout rooms, town hall stage – plus chat, people (and guests
 * waiting to be let in) and shared notes. People leading the meeting can mute, highlight or remove others.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import BaseModal from './BaseModal.vue'
import MeetingBreakouts from './MeetingBreakouts.vue'
import MeetingWhiteboard from './MeetingWhiteboard.vue'
import VideoTile from './VideoTile.vue'
import { ApiError, api } from '@/lib/api'
import { errorText, t } from '@/lib/i18n'
import { breakoutJoin, breakoutState, saveBreakouts, type BreakoutState } from '@/lib/breakouts'
import { listDevices, previewTracks as makePreview, speakerId, useMeeting, type JoinInfo, type MeetingMode, type Tile } from '@/lib/meeting'
import { canRecord, startRecording, type Recorder } from '@/lib/recorder'
import { renderMarkdown } from '@/lib/markdown'
import { setActivity } from '@/lib/summary'
import { showToast } from '@/lib/toast'

/* eslint-disable @typescript-eslint/no-explicit-any -- lib-jitsi-meet tracks */
const props = defineProps<{
  meetingId: number
  title: string
  displayName: string
  guest?: boolean
  join?: JoinInfo | null // guests already have it
  callMode?: boolean // started a call: show who it is ringing
  guestLink?: string | null
  spaceId?: number | null // recordings can be saved to the space's files
}>()
const emit = defineEmits<{ left: [] }>()

const meeting = useMeeting()
const phase = ref<'prejoin' | 'room' | 'ended'>('prejoin')
// Others see "in a meeting" next to my name while I am in the room (not for guests: they have no account)
watch(() => phase.value === 'room', (inRoom) => !props.guest && setActivity(inRoom ? `meeting:${props.meetingId}` : ''))
const preview = ref<HTMLVideoElement | null>(null)
const previewTracks = ref<any[]>([])
const prefs = reactive({ mic: true, cam: true, camera: '', micId: '' })
const devices = ref<{ cameras: MediaDeviceInfo[]; mics: MediaDeviceInfo[]; speakers: MediaDeviceInfo[] }>({ cameras: [], mics: [], speakers: [] })
const joining = ref(false)
type Panel = 'chat' | 'people' | 'notes' | 'breakouts' | 'settings'
const panel = ref<Panel | null>(null)
const chatText = ref('')
const chatList = ref<HTMLElement | null>(null)
const live = ref<{ id: number | null; name: string; guest: boolean }[]>([])
const waiting = ref<{ id: number; name: string }[]>([])
const callStatus = ref<'ringing' | 'active' | 'declined' | 'missed' | 'ended' | ''>('')
const callee = ref('')
const started = ref(Date.now())
const now = ref(Date.now())
const notes = reactive({ text: '', version: 0, saved: '', saving: false })
let heartbeat: number | undefined
let ticker: number | undefined
const mode = ref<MeetingMode | null>(null)
/** Why there is no camera or microphone: the page is not https://, or the browser/person said no. */
const mediaProblem = ref<'' | 'insecure' | 'blocked'>('')

const tiles = computed(() => meeting.state.tiles)
/** In a town hall only the stage is shown: the people leading it and those they brought up. */
const visible = computed(() => (meeting.state.townHall
  ? tiles.value.filter((x) => x.mod || meeting.state.stage.includes(x.who) || (x.local && meeting.mayTalk()))
  : tiles.value))
const audience = computed(() => tiles.value.length - visible.value.length)
const view = ref<'gallery' | 'speaker'>('gallery')
const pinnedId = ref('') // pinned for me only
const screenTile = computed<Tile | undefined>(() => visible.value.find((x) => x.screen))
/** Who is shown large: a shared screen, then my pin, then the spotlight for everyone, then (speaker view) who talks. */
const featured = computed<Tile | undefined>(() => {
  if (screenTile.value) return screenTile.value
  const byId = (id: string) => visible.value.find((x) => x.id === id)
  const pinned = pinnedId.value ? byId(pinnedId.value) : undefined
  if (pinned) return pinned
  const spot = meeting.state.spotlight ? visible.value.find((x) => x.who === meeting.state.spotlight) : undefined
  if (spot) return spot
  if (view.value === 'speaker' && visible.value.length > 1) {
    return byId(meeting.state.dominant) ?? visible.value.find((x) => !x.local) ?? visible.value[0]
  }
  return undefined
})
const others = computed(() => visible.value.filter((x) => x !== featured.value))
const gridClass = computed(() => `n${Math.min(others.value.length, 9)}`)
const boardOpen = ref(false)
const stageEl = ref<HTMLElement | null>(null)
const duration = computed(() => {
  const s = Math.max(0, Math.floor((now.value - started.value) / 1000))
  const m = Math.floor(s / 60)
  return `${Math.floor(m / 60) ? `${Math.floor(m / 60)}:` : ''}${String(m % 60).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
})

// ---------- before joining ----------

async function refreshPreview() {
  for (const track of previewTracks.value) track.dispose?.()
  previewTracks.value = []
  const wanted: ('audio' | 'video')[] = []
  if (prefs.mic) wanted.push('audio')
  if (prefs.cam) wanted.push('video')
  if (!wanted.length || !mode.value) return
  if (!window.isSecureContext) {
    mediaProblem.value = 'insecure'
    prefs.mic = prefs.cam = false
    return
  }
  previewTracks.value = await makePreview(mode.value, wanted, { camera: prefs.camera || undefined, mic: prefs.micId || undefined })
  mediaProblem.value = previewTracks.value.length ? '' : 'blocked'
  const video = previewTracks.value.find((x) => x.getType() === 'video')
  await nextTick()
  if (video && preview.value) video.attach(preview.value)
  devices.value = await listDevices()
  if (!previewTracks.value.some((x) => x.getType() === 'video')) prefs.cam = false
  if (!previewTracks.value.some((x) => x.getType() === 'audio')) prefs.mic = false
  watchMicLevel()
}

// ---------- device test: microphone level and a test sound on the chosen loudspeaker ----------

const micLevel = ref(0)
let levelContext: AudioContext | null = null
let levelTimer: number | undefined

function mediaTrack(track: any): MediaStreamTrack | null {
  return track?.track instanceof MediaStreamTrack ? track.track : track?.getTrack?.() ?? null
}

function watchMicLevel() {
  window.clearInterval(levelTimer)
  micLevel.value = 0
  const track = mediaTrack(previewTracks.value.find((x) => x.getType() === 'audio'))
  if (!track) return
  try {
    levelContext ??= new AudioContext()
    levelContext.resume().catch(() => undefined)
    const analyser = levelContext.createAnalyser()
    analyser.fftSize = 512
    levelContext.createMediaStreamSource(new MediaStream([track])).connect(analyser)
    const data = new Uint8Array(analyser.fftSize)
    levelTimer = window.setInterval(() => {
      analyser.getByteTimeDomainData(data)
      let sum = 0
      for (const v of data) sum += ((v - 128) / 128) ** 2
      micLevel.value = Math.min(1, Math.sqrt(sum / data.length) * 4)
    }, 100)
  } catch {
    /* no level meter in this browser */
  }
}

const speaker = computed({ get: () => speakerId.value, set: (v: string) => (speakerId.value = v) })
const speakerChoice = computed(() => devices.value.speakers.length > 1 && 'setSinkId' in HTMLMediaElement.prototype)

/** A short friendly tone on the chosen loudspeaker or headset. */
async function testSound() {
  const context = new AudioContext()
  const target = context.createMediaStreamDestination()
  for (const [i, frequency] of [523.25, 659.25, 783.99].entries()) {
    const tone = context.createOscillator()
    const gain = context.createGain()
    tone.frequency.value = frequency
    gain.gain.setValueAtTime(0.0001, context.currentTime + i * 0.18)
    gain.gain.exponentialRampToValueAtTime(0.25, context.currentTime + i * 0.18 + 0.03)
    gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + i * 0.18 + 0.5)
    tone.connect(gain).connect(target)
    tone.start(context.currentTime + i * 0.18)
    tone.stop(context.currentTime + i * 0.18 + 0.55)
  }
  const player = new Audio() as HTMLAudioElement & { setSinkId?: (id: string) => Promise<void> }
  player.srcObject = target.stream
  await player.setSinkId?.(speakerId.value).catch(() => undefined)
  await player.play().catch(() => undefined)
  window.setTimeout(() => {
    player.srcObject = null
    context.close().catch(() => undefined)
  }, 1200)
}

async function enter() {
  joining.value = true
  try {
    const info = props.join ?? (await api.post<JoinInfo>(`/api/meetings/${props.meetingId}/join`))
    if (info.connection.mode !== mode.value) {
      // The meeting server was started or stopped in the meantime: get camera and microphone the other way
      mode.value = info.connection.mode
      await refreshPreview()
    }
    phase.value = 'room'
    started.value = Date.now()
    await meeting.join(info, previewTracks.value, info.connection.display_name || props.displayName)
    previewTracks.value = []
    if (!props.guest) {
      beat()
      heartbeat = window.setInterval(beat, 10_000)
      loadNotes()
    }
    if (props.callMode) watchCall()
    if (!props.callMode) pollBreakouts()
    if (!noiseSuppression.value) meeting.setNoiseSuppression(false)
  } catch (e) {
    phase.value = 'prejoin'
    const code = (e as { code?: string })?.code
    const known = code ? t(`errors.${code}`) : ''
    showToast(e instanceof ApiError ? errorText(e) : code && known !== `errors.${code}` ? known : t('meeting.connectFailed'), 'error')
  } finally {
    joining.value = false
  }
}

// ---------- while in the meeting ----------

async function beat() {
  try {
    const p = await api.post<{ live: typeof live.value; waiting: typeof waiting.value; ended: boolean }>(`/api/meetings/${props.meetingId}/presence`)
    live.value = p.live
    waiting.value = p.waiting
  } catch {
    /* next time */
  }
}

async function decide(id: number, decision: 'admit' | 'deny') {
  const p = await api.post<{ live: typeof live.value; waiting: typeof waiting.value }>(`/api/meetings/${props.meetingId}/guests/${id}/${decision}`)
  live.value = p.live
  waiting.value = p.waiting
}

async function watchCall() {
  const check = async () => {
    if (phase.value !== 'room') return
    try {
      const state = await api.get<{ status: typeof callStatus.value; people: { person: { full_name: string }; response: string }[] }>(`/api/calls/${props.meetingId}`)
      callStatus.value = state.status
      callee.value = state.people.map((p) => p.person.full_name).join(', ')
      if (state.status === 'ringing') window.setTimeout(check, 2000)
      if (state.status === 'declined' || state.status === 'missed') window.setTimeout(hangUp, 4000)
    } catch {
      window.setTimeout(check, 4000)
    }
  }
  check()
}

async function loadNotes() {
  const d = await api.get<{ notes: string; notes_version: number }>(`/api/meetings/${props.meetingId}`)
  notes.text = d.notes
  notes.version = d.notes_version
  notes.saved = d.notes
}

async function saveNotes() {
  if (notes.text === notes.saved) return
  notes.saving = true
  try {
    const d = await api.put<{ notes: string; notes_version: number }>(`/api/meetings/${props.meetingId}/notes`, { notes: notes.text, base_version: notes.version })
    notes.version = d.notes_version
    notes.saved = d.notes
  } catch (e) {
    if (e instanceof ApiError && e.code === 'notes_conflict') {
      // Someone else saved: keep both texts so nothing gets lost
      const d = await api.get<{ notes: string; notes_version: number }>(`/api/meetings/${props.meetingId}`)
      notes.text = `${d.notes}\n\n---\n${notes.text}`
      notes.version = d.notes_version
      showToast(t('meeting.notesMerged'))
      await saveNotes()
    } else {
      showToast(errorText(e), 'error')
    }
  } finally {
    notes.saving = false
  }
}

function sendChat() {
  meeting.send(chatText.value)
  chatText.value = ''
  nextTick(() => chatList.value?.scrollTo({ top: chatList.value.scrollHeight }))
}

function togglePanel(name: Panel) {
  panel.value = panel.value === name ? null : name
  moreOpen.value = false
  if (name === 'chat') meeting.state.unread = 0
  if (name === 'breakouts') pollBreakouts()
}

// ---------- reactions, views, picture-in-picture, whiteboard ----------

const REACTIONS = ['👍', '❤️', '😂', '👏', '🎉', '😮']
const reactOpen = ref(false)
const moreOpen = ref(false)

function react(emoji: string) {
  meeting.react(emoji)
  reactOpen.value = false
}

function pin(tile: Tile) {
  pinnedId.value = pinnedId.value === tile.id ? '' : tile.id
}

const pipSupported = typeof document !== 'undefined' && 'pictureInPictureEnabled' in document && document.pictureInPictureEnabled

/** Keep the most important video in a small window above other programs. */
async function pictureInPicture() {
  moreOpen.value = false
  if (document.pictureInPictureElement) {
    await document.exitPictureInPicture().catch(() => undefined)
    return
  }
  const candidates = [featured.value, tiles.value.find((x) => x.id === meeting.state.dominant), ...others.value.filter((x) => !x.local)]
  for (const tile of candidates) {
    const video = tile && !tile.videoMuted ? document.querySelector<HTMLVideoElement>(`[data-tile="${tile.id}"] video`) : null
    if (video && video.readyState >= 2) {
      await video.requestPictureInPicture().catch(() => showToast(t('meeting.pipFailed'), 'error'))
      return
    }
  }
  showToast(t('meeting.pipNoVideo'))
}

function toggleBoard() {
  boardOpen.value = !boardOpen.value
  meeting.state.boardUnread = 0
  moreOpen.value = false
}

// ---------- recording ----------

let recorder: Recorder | null = null
const recording = ref(false)
const recordingDone = ref<Blob | null>(null)
const recordingSaving = ref(false)
const someoneRecording = computed(() => meeting.state.recording
  .map((id) => (id === 'local' ? t('meeting.you') : tiles.value.find((x) => x.id === id)?.name))
  .filter(Boolean)
  .join(', '))

function toggleRecording() {
  moreOpen.value = false
  if (recording.value) stopRecording()
  else recordConfirm.value = true
}

const recordConfirm = ref(false)

function beginRecording() {
  recordConfirm.value = false
  if (!stageEl.value || !canRecord()) {
    showToast(t('meeting.recordUnsupported'), 'error')
    return
  }
  recorder = startRecording(stageEl.value, () => meeting.audioTracks())
  recording.value = true
  meeting.setRecording(true)
}

async function stopRecording() {
  if (!recorder) return
  const r = recorder
  recorder = null
  recording.value = false
  meeting.setRecording(false)
  const blob = await r.stop()
  if (blob.size) {
    recordingDone.value = blob
    downloadRecording()
  }
}

function recordingName() {
  const day = new Date().toISOString().slice(0, 16).replace('T', ' ').replace(':', '-')
  return `${props.title || t('meeting.title')} ${day}.webm`.replace(/[\\/:*?"<>|]/g, '-')
}

function downloadRecording() {
  if (!recordingDone.value) return
  const url = URL.createObjectURL(recordingDone.value)
  const link = document.createElement('a')
  link.href = url
  link.download = recordingName()
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

async function saveRecordingToSpace() {
  if (!recordingDone.value || !props.spaceId) return
  recordingSaving.value = true
  const form = new FormData()
  form.append('file', new File([recordingDone.value], recordingName(), { type: recordingDone.value.type }))
  try {
    await api.post(`/api/spaces/${props.spaceId}/files`, form)
    showToast(t('meeting.recordingSaved'))
    recordingDone.value = null
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    recordingSaving.value = false
  }
}

// ---------- audio settings: noise suppression, push to talk ----------

function pref(key: string, fallback: boolean) {
  try {
    const v = localStorage.getItem(`officehub-meeting-${key}`)
    return v === null ? fallback : v === '1'
  } catch {
    return fallback
  }
}

function savePref(key: string, value: boolean) {
  try {
    localStorage.setItem(`officehub-meeting-${key}`, value ? '1' : '0')
  } catch {
    /* private window */
  }
}

const noiseSuppression = ref(pref('noise', true))
const pushToTalk = ref(pref('ptt', false))
const talking = ref(false) // holding the space bar

watch(noiseSuppression, (on) => {
  savePref('noise', on)
  meeting.setNoiseSuppression(on)
})
watch(pushToTalk, (on) => savePref('ptt', on))

// ---------- leading the meeting ----------

const removing = ref<Tile | null>(null)

function confirmRemove() {
  if (removing.value) meeting.remove(removing.value)
  removing.value = null
}

function spotlight(tile: Tile) {
  meeting.setSpotlight(meeting.state.spotlight === tile.who ? '' : tile.who)
}

const onStage = (tile: Tile) => meeting.state.stage.includes(tile.who)

// ---------- breakout rooms ----------

const breakouts = ref<BreakoutState | null>(null)
const inRoom = ref<number | null>(null)
const breakoutBusy = ref(false)
let breakoutTimer: number | undefined

async function pollBreakouts() {
  window.clearTimeout(breakoutTimer)
  const token = meeting.info?.connection.token
  if (phase.value !== 'room' || !token) return
  try {
    const s = await breakoutState(token)
    breakouts.value = s
    if (!meeting.state.moving && !breakoutBusy.value) {
      if (!s.moderator && s.open && s.mine !== null && inRoom.value !== s.mine) await moveTo(s.mine)
      else if ((!s.open || (!s.moderator && s.mine === null)) && inRoom.value !== null) await moveTo(null)
    }
  } catch {
    /* next time */
  }
  breakoutTimer = window.setTimeout(pollBreakouts, 5000)
}

async function moveTo(room: number | null) {
  const token = meeting.info?.connection.token
  if (!token) return
  breakoutBusy.value = true
  try {
    const info = await breakoutJoin(token, room, props.meetingId, props.title)
    const wanted: ('audio' | 'video')[] = []
    if (meeting.state.micOn) wanted.push('audio')
    if (meeting.state.camOn && !meeting.state.sharing) wanted.push('video')
    const tracks = wanted.length ? await makePreview(info.connection.mode, wanted, { camera: prefs.camera || undefined, mic: prefs.micId || undefined }) : []
    if (recording.value) await stopRecording()
    boardOpen.value = false
    pinnedId.value = ''
    await meeting.move(info, tracks, info.connection.display_name || props.displayName)
    inRoom.value = room
    showToast(room === null ? t('meeting.breakouts.welcomeBack') : t('meeting.breakouts.moved', { name: breakouts.value?.rooms[room] ?? '' }))
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    breakoutBusy.value = false
  }
}

async function saveRooms(body: { rooms: string[]; assign: Record<string, number>; open: boolean; minutes: number | null }) {
  const token = meeting.info?.connection.token
  if (!token) return
  breakoutBusy.value = true
  try {
    breakouts.value = await saveBreakouts(token, body)
    meeting.breakoutsChanged()
    showToast(body.open ? t('meeting.breakouts.opened') : t('meeting.breakouts.closed'))
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    breakoutBusy.value = false
  }
  if (!body.open && inRoom.value !== null) await moveTo(null)
}

const breakoutLeft = computed(() => {
  const end = breakouts.value?.open ? breakouts.value.ends_at : null
  if (!end) return ''
  const s = Math.max(0, Math.round(end - now.value / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
})
const roomLabel = computed(() => (inRoom.value !== null ? breakouts.value?.rooms[inRoom.value] ?? '' : ''))

async function copyGuestLink() {
  if (!props.guestLink) return
  const url = `${window.location.origin}${props.guestLink}`
  try {
    await navigator.clipboard.writeText(url)
    showToast(t('meeting.linkCopied'))
  } catch {
    window.prompt(t('meeting.guestLink'), url)
  }
}

async function hangUp() {
  window.clearInterval(heartbeat)
  window.clearTimeout(breakoutTimer)
  if (recording.value) await stopRecording()
  if (document.pictureInPictureElement) document.exitPictureInPicture().catch(() => undefined)
  if (!props.guest) {
    await saveNotes().catch(() => undefined)
    await api.delete(`/api/meetings/${props.meetingId}/presence`).catch(() => undefined)
  }
  await meeting.leave()
  phase.value = 'ended'
  emit('left')
}

function onKey(event: KeyboardEvent) {
  if (phase.value !== 'room' || (event.target as HTMLElement)?.closest('input, textarea, select')) return
  // Push to talk: hold the space bar to speak while muted (not while a button has the focus: space presses it)
  if (event.key === ' ' && pushToTalk.value && !(event.target as HTMLElement)?.closest('button, canvas')) {
    event.preventDefault()
    if (!event.repeat && !meeting.state.micOn && meeting.mayTalk()) {
      talking.value = true
      meeting.toggleMic()
    }
    return
  }
  if (event.key === 'm' || event.key === 'M') meeting.toggleMic()
  if (event.key === 'v' || event.key === 'V') meeting.toggleCam()
}

function onKeyUp(event: KeyboardEvent) {
  if (event.key === ' ' && talking.value) {
    talking.value = false
    if (meeting.state.micOn) meeting.toggleMic()
  }
}

// Messages for me: muted by the organizer, brought on stage, someone records …
watch(() => meeting.state.notices.length, (n, old) => {
  for (const item of meeting.state.notices.slice(old ?? 0, n)) showToast(t(item.text, item.params ?? {}), item.text === 'meeting.removed' ? 'error' : 'success')
})
watch(() => meeting.state.breakoutsChanged, () => pollBreakouts())

watch(() => meeting.state.chat.length, () => {
  if (panel.value === 'chat') {
    meeting.state.unread = 0
    nextTick(() => chatList.value?.scrollTo({ top: chatList.value.scrollHeight }))
  }
})
watch(() => meeting.state.status, (s) => {
  if (s === 'failed' && !joining.value) showToast(t('meeting.connectFailed'), 'error')
  if (s === 'left' && phase.value === 'room' && !meeting.state.moving) hangUp()
})

onMounted(async () => {
  window.addEventListener('keydown', onKey)
  window.addEventListener('keyup', onKeyUp)
  window.addEventListener('beforeunload', onUnload)
  ticker = window.setInterval(() => (now.value = Date.now()), 1000)
  try {
    mode.value = props.join?.connection.mode ?? (await api.get<{ mode: MeetingMode }>('/api/meetings/config')).mode
  } catch {
    showToast(t('meeting.connectFailed'), 'error')
    return
  }
  try {
    await refreshPreview()
  } catch {
    // The Jitsi page could not be loaded; built in, only camera or microphone can fail
    if (mode.value === 'jitsi') showToast(t('meeting.libraryMissing'), 'error')
    else mediaProblem.value = 'blocked'
  }
})

function onUnload() {
  if (phase.value !== 'room') return
  // Tell the others and the portal right away that we left (keepalive survives the page closing)
  meeting.leave()
  if (!props.guest) {
    fetch(`/api/meetings/${props.meetingId}/presence`, { method: 'DELETE', keepalive: true, headers: { 'X-Requested-With': 'OfficeHub' } }).catch(() => undefined)
  }
}

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('keyup', onKeyUp)
  window.removeEventListener('beforeunload', onUnload)
  window.clearInterval(levelTimer)
  window.clearTimeout(breakoutTimer)
  levelContext?.close().catch(() => undefined)
  window.clearInterval(heartbeat)
  window.clearInterval(ticker)
  for (const track of previewTracks.value) track.dispose?.()
  if (phase.value === 'room') hangUp()
  if (!props.guest) setActivity('')
})
</script>

<template>
  <div class="meeting" :class="`phase-${phase}`">
    <!-- Check camera and microphone -->
    <section v-if="phase === 'prejoin'" class="prejoin" :aria-label="t('meeting.prejoin')">
      <div class="preview-box">
        <video v-show="prefs.cam" ref="preview" autoplay playsinline muted class="preview mirror" />
        <div v-if="!prefs.cam" class="preview off"><AppIcon name="videoOff" :size="40" />{{ t('meeting.camOff') }}</div>
        <div class="pre-controls">
          <button type="button" class="round" :class="{ off: !prefs.mic }" :aria-pressed="prefs.mic" :aria-label="prefs.mic ? t('meeting.muteMic') : t('meeting.unmuteMic')" @click="prefs.mic = !prefs.mic; refreshPreview()">
            <AppIcon :name="prefs.mic ? 'mic' : 'micOff'" />
          </button>
          <button type="button" class="round" :class="{ off: !prefs.cam }" :aria-pressed="prefs.cam" :aria-label="prefs.cam ? t('meeting.camStop') : t('meeting.camStart')" @click="prefs.cam = !prefs.cam; refreshPreview()">
            <AppIcon :name="prefs.cam ? 'video' : 'videoOff'" />
          </button>
        </div>
      </div>
      <div class="pre-side">
        <p class="eyebrow">{{ t('meeting.readyTo') }}</p>
        <h1 class="pre-title">{{ title }}</h1>
        <p class="muted-light">{{ t('meeting.joinAs', { name: displayName }) }}</p>
        <p v-if="mediaProblem" class="media-note" role="status">{{ t(`meeting.media.${mediaProblem}`) }}</p>
        <label v-if="devices.cameras.length > 1" class="field">
          <span>{{ t('meeting.camera') }}</span>
          <select v-model="prefs.camera" class="select" @change="refreshPreview">
            <option value="">{{ t('meeting.defaultDevice') }}</option>
            <option v-for="d in devices.cameras" :key="d.deviceId" :value="d.deviceId">{{ d.label || t('meeting.camera') }}</option>
          </select>
        </label>
        <label v-if="devices.mics.length > 1" class="field">
          <span>{{ t('meeting.microphone') }}</span>
          <select v-model="prefs.micId" class="select" @change="refreshPreview">
            <option value="">{{ t('meeting.defaultDevice') }}</option>
            <option v-for="d in devices.mics" :key="d.deviceId" :value="d.deviceId">{{ d.label || t('meeting.microphone') }}</option>
          </select>
        </label>
        <div v-if="prefs.mic" class="level-row">
          <span class="small muted-light">{{ t('meeting.micTest') }}</span>
          <span class="meter" role="meter" :aria-label="t('meeting.micTest')" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="Math.round(micLevel * 100)">
            <span class="meter-fill" :style="{ transform: `scaleX(${micLevel})` }" />
          </span>
        </div>
        <label v-if="speakerChoice" class="field">
          <span>{{ t('meeting.speaker') }}</span>
          <select v-model="speaker" class="select">
            <option value="">{{ t('meeting.defaultDevice') }}</option>
            <option v-for="d in devices.speakers" :key="d.deviceId" :value="d.deviceId">{{ d.label || t('meeting.speaker') }}</option>
          </select>
        </label>
        <button type="button" class="btn btn-ghost light test-sound" @click="testSound"><AppIcon name="bell" :size="18" />{{ t('meeting.testSound') }}</button>
        <button type="button" class="btn btn-primary join-btn" :disabled="joining" @click="enter">
          <AppIcon name="video" />{{ joining ? t('meeting.joining') : t('meeting.joinNow') }}
        </button>
        <p class="muted-light small">{{ t('meeting.privacy') }}</p>
      </div>
    </section>

    <!-- In the meeting -->
    <template v-else-if="phase === 'room'">
      <header class="top">
        <h1 class="room-title">{{ title }}<template v-if="roomLabel"> · {{ roomLabel }}</template></h1>
        <span v-if="recording || someoneRecording" class="rec-pill" role="status"><span class="rec-dot" aria-hidden="true" />{{ t('meeting.recordingShort') }}</span>
        <span v-if="breakoutLeft" class="time" :aria-label="t('meeting.breakouts.timeLeft')"><AppIcon name="clock" :size="16" />{{ breakoutLeft }}</span>
        <span class="time" :aria-label="t('meeting.duration')">{{ duration }}</span>
        <span class="count"><AppIcon name="users" :size="16" />{{ tiles.length }}</span>
      </header>

      <div class="body" :class="{ 'with-panel': panel }">
        <div ref="stageEl" class="stage" :class="{ sharing: featured || boardOpen }">
          <p v-if="callMode && callStatus === 'ringing'" class="banner" role="status"><AppIcon name="phone" :size="18" />{{ t('meeting.ringing', { name: callee }) }}</p>
          <p v-else-if="callMode && callStatus === 'declined'" class="banner warn" role="status">{{ t('meeting.declined', { name: callee }) }}</p>
          <p v-else-if="callMode && callStatus === 'missed'" class="banner warn" role="status">{{ t('meeting.noAnswer', { name: callee }) }}</p>
          <div v-for="g in waiting" :key="g.id" class="banner guest" role="alert">
            <span>{{ t('meeting.guestWaiting', { name: g.name }) }}</span>
            <button type="button" class="btn btn-primary" @click="decide(g.id, 'admit')">{{ t('meeting.admit') }}</button>
            <button type="button" class="btn btn-ghost light" @click="decide(g.id, 'deny')">{{ t('meeting.deny') }}</button>
          </div>
          <p v-if="someoneRecording" class="banner rec" role="status"><span class="rec-dot" aria-hidden="true" />{{ t('meeting.recordingBanner', { names: someoneRecording }) }}</p>
          <p v-if="meeting.state.townHall && !meeting.mayTalk()" class="banner" role="status"><AppIcon name="users" :size="18" />{{ t('meeting.audienceBanner') }}</p>
          <p v-if="recordingDone" class="banner" role="status">
            {{ t('meeting.recordingReady') }}
            <button type="button" class="btn btn-ghost light" @click="downloadRecording"><AppIcon name="download" :size="16" />{{ t('meeting.recordingDownload') }}</button>
            <button v-if="spaceId && !guest" type="button" class="btn btn-primary" :disabled="recordingSaving" @click="saveRecordingToSpace">{{ t('meeting.recordingToSpace') }}</button>
            <button type="button" class="icon-btn" :aria-label="t('app.close')" @click="recordingDone = null"><AppIcon name="close" :size="16" /></button>
          </p>
          <MeetingWhiteboard v-if="boardOpen" :strokes="meeting.state.strokes" class="screen-stage board-stage" @draw="meeting.draw" @clear="meeting.clearBoard" @close="boardOpen = false" />
          <VideoTile v-else-if="featured" :tile="featured" large class="screen-stage" :pinned="pinnedId === featured.id" :spotlight="!!featured.who && featured.who === meeting.state.spotlight" @pin="pin(featured)" />
          <div class="grid" :class="[gridClass, { strip: featured || boardOpen }]">
            <VideoTile v-for="tile in (boardOpen ? visible : others)" :key="tile.id" :tile="tile" :pinned="pinnedId === tile.id" :spotlight="!!tile.who && tile.who === meeting.state.spotlight" @pin="pin(tile)" />
          </div>
          <p v-if="audience > 0" class="audience muted-light small">{{ t('meeting.audienceCount', { n: audience }) }}</p>
          <p v-if="meeting.state.status === 'connecting'" class="banner" role="status">{{ meeting.state.moving ? t('meeting.breakouts.moving') : t('meeting.connecting') }}</p>
        </div>

        <aside v-if="panel" class="panel" :aria-label="t(`meeting.panels.${panel}`)">
          <div class="panel-head">
            <h2>{{ t(`meeting.panels.${panel}`) }}</h2>
            <button type="button" class="icon-btn" :aria-label="t('app.close')" @click="panel = null"><AppIcon name="close" :size="18" /></button>
          </div>

          <template v-if="panel === 'chat'">
            <ol ref="chatList" class="chat">
              <li v-for="line in meeting.state.chat" :key="line.id" :class="{ mine: line.mine }">
                <strong>{{ line.mine ? t('meeting.you') : line.from }}</strong>
                <span>{{ line.text }}</span>
              </li>
              <li v-if="!meeting.state.chat.length" class="muted-light small">{{ t('meeting.chatEmpty') }}</li>
            </ol>
            <form class="chat-form" @submit.prevent="sendChat">
              <label for="mt-chat" class="visually-hidden">{{ t('meeting.chatWrite') }}</label>
              <input id="mt-chat" v-model="chatText" class="input" maxlength="1000" :placeholder="t('meeting.chatWrite')" autocomplete="off" />
              <button type="submit" class="icon-btn" :aria-label="t('chat.send')"><AppIcon name="send" :size="18" /></button>
            </form>
          </template>

          <template v-else-if="panel === 'people'">
            <button v-if="meeting.state.moderator && tiles.length > 1" type="button" class="btn btn-secondary" @click="meeting.muteAll(); showToast(t('meeting.mutedAll'))"><AppIcon name="micOff" :size="18" />{{ t('meeting.muteAll') }}</button>
            <ul class="people">
              <li v-for="tile in tiles" :key="tile.id">
                <div class="person">
                  <span class="pname">{{ tile.name }}<template v-if="tile.local"> ({{ t('meeting.you') }})</template><span v-if="tile.mod" class="tag">{{ t('meeting.leadBadge') }}</span><span v-else-if="meeting.state.townHall && onStage(tile)" class="tag">{{ t('meeting.stageBadge') }}</span></span>
                  <AppIcon v-if="tile.hand" name="hand" :size="16" :label="t('meeting.handRaised')" />
                  <AppIcon :name="tile.audioMuted ? 'micOff' : 'mic'" :size="16" :label="tile.audioMuted ? t('meeting.micMuted') : t('meeting.micOn')" />
                </div>
                <div v-if="meeting.state.moderator && !tile.local" class="mod-actions">
                  <button v-if="!tile.audioMuted" type="button" class="mini" @click="meeting.mute(tile)">{{ t('meeting.muteOne') }}</button>
                  <button v-if="tile.hand" type="button" class="mini" @click="meeting.lowerHand(tile)">{{ t('meeting.lowerHand') }}</button>
                  <button v-if="tile.who" type="button" class="mini" :aria-pressed="meeting.state.spotlight === tile.who" @click="spotlight(tile)">{{ meeting.state.spotlight === tile.who ? t('meeting.spotlightOff') : t('meeting.spotlightOn') }}</button>
                  <button v-if="meeting.state.townHall && !tile.mod && tile.who" type="button" class="mini" @click="meeting.setStage(tile.who, !onStage(tile))">{{ onStage(tile) ? t('meeting.stageOff') : t('meeting.stageOn') }}</button>
                  <button v-if="!tile.mod" type="button" class="mini danger" @click="removing = tile">{{ t('meeting.remove') }}</button>
                </div>
              </li>
            </ul>
            <div v-if="waiting.length" class="waiting">
              <h3>{{ t('meeting.lobby') }}</h3>
              <div v-for="g in waiting" :key="g.id" class="waiting-row">
                <span>{{ g.name }}</span>
                <button type="button" class="btn btn-primary" @click="decide(g.id, 'admit')">{{ t('meeting.admit') }}</button>
                <button type="button" class="btn btn-ghost light" @click="decide(g.id, 'deny')">{{ t('meeting.deny') }}</button>
              </div>
            </div>
            <button v-if="guestLink" type="button" class="btn btn-secondary invite" @click="copyGuestLink"><AppIcon name="link" :size="18" />{{ t('meeting.copyGuestLink') }}</button>
          </template>

          <template v-else-if="panel === 'notes'">
            <p class="muted-light small">{{ t('meeting.notesHint') }}</p>
            <label for="mt-notes" class="visually-hidden">{{ t('meeting.panels.notes') }}</label>
            <textarea id="mt-notes" v-model="notes.text" class="textarea notes" :placeholder="t('meeting.notesPlaceholder')" @blur="saveNotes" />
            <p class="muted-light small">{{ notes.saving ? t('app.saving') : notes.text === notes.saved ? t('meeting.notesSaved') : t('meeting.notesUnsaved') }}</p>
            <!-- eslint-disable-next-line vue/no-v-html -- renderMarkdown escapes HTML first -->
            <div v-if="notes.text.trim()" class="markdown notes-preview" v-html="renderMarkdown(notes.text)" />
          </template>

          <MeetingBreakouts v-else-if="panel === 'breakouts'" :state="breakouts" :tiles="tiles" :in-room="inRoom" :busy="breakoutBusy" @save="saveRooms" @visit="moveTo" />

          <template v-else-if="panel === 'settings'">
            <label class="switch-row"><input v-model="noiseSuppression" type="checkbox" /><span><strong>{{ t('meeting.noise') }}</strong><span class="muted-light small block">{{ t('meeting.noiseHint') }}</span></span></label>
            <label class="switch-row"><input v-model="pushToTalk" type="checkbox" /><span><strong>{{ t('meeting.ptt') }}</strong><span class="muted-light small block">{{ t('meeting.pttHint') }}</span></span></label>
            <label v-if="speakerChoice" class="field">
              <span>{{ t('meeting.speaker') }}</span>
              <select v-model="speaker" class="select">
                <option value="">{{ t('meeting.defaultDevice') }}</option>
                <option v-for="d in devices.speakers" :key="d.deviceId" :value="d.deviceId">{{ d.label || t('meeting.speaker') }}</option>
              </select>
            </label>
            <button type="button" class="btn btn-ghost light" @click="testSound"><AppIcon name="bell" :size="18" />{{ t('meeting.testSound') }}</button>
            <p class="muted-light small">{{ t('meeting.shortcuts') }}</p>
          </template>
        </aside>
      </div>

      <nav class="toolbar" :aria-label="t('meeting.controls')">
        <button type="button" class="ctrl" :class="{ off: !meeting.state.micOn, locked: !meeting.mayTalk() }" :aria-pressed="meeting.state.micOn" @click="meeting.toggleMic()">
          <AppIcon :name="meeting.state.micOn ? 'mic' : 'micOff'" /><span>{{ talking ? t('meeting.talking') : meeting.state.micOn ? t('meeting.mute') : t('meeting.unmute') }}</span>
        </button>
        <button type="button" class="ctrl" :class="{ off: !meeting.state.camOn, locked: !meeting.mayTalk() }" :aria-pressed="meeting.state.camOn" @click="meeting.toggleCam()">
          <AppIcon :name="meeting.state.camOn ? 'video' : 'videoOff'" /><span>{{ meeting.state.camOn ? t('meeting.camStop') : t('meeting.camStart') }}</span>
        </button>
        <button type="button" class="ctrl" :class="{ on: meeting.state.sharing, locked: !meeting.mayTalk() }" :aria-pressed="meeting.state.sharing" @click="meeting.state.sharing ? meeting.stopShare() : meeting.startShare()">
          <AppIcon name="screen" /><span>{{ meeting.state.sharing ? t('meeting.stopShare') : t('meeting.share') }}</span>
        </button>
        <div class="pop-wrap">
          <button type="button" class="ctrl" :class="{ on: reactOpen }" aria-haspopup="true" :aria-expanded="reactOpen" @click="reactOpen = !reactOpen; moreOpen = false">
            <AppIcon name="thumbsUp" /><span>{{ t('meeting.react') }}</span>
          </button>
          <div v-if="reactOpen" class="pop reactions-pop" role="menu" :aria-label="t('meeting.react')" @keydown.esc="reactOpen = false">
            <button v-for="e in REACTIONS" :key="e" type="button" role="menuitem" class="emoji" :aria-label="t('meeting.reactWith', { emoji: e })" @click="react(e)">{{ e }}</button>
          </div>
        </div>
        <button type="button" class="ctrl" :class="{ on: meeting.state.hand }" :aria-pressed="meeting.state.hand" @click="meeting.toggleHand()">
          <AppIcon name="hand" /><span>{{ t('meeting.hand') }}</span>
        </button>
        <button type="button" class="ctrl" :class="{ on: panel === 'chat' }" :aria-pressed="panel === 'chat'" @click="togglePanel('chat')">
          <AppIcon name="chat" /><span>{{ t('meeting.panels.chat') }}</span>
          <span v-if="meeting.state.unread && panel !== 'chat'" class="dot">{{ meeting.state.unread }}</span>
        </button>
        <button type="button" class="ctrl" :class="{ on: panel === 'people' }" :aria-pressed="panel === 'people'" @click="togglePanel('people')">
          <AppIcon name="users" /><span>{{ t('meeting.panels.people') }}</span>
          <span v-if="waiting.length || tiles.some((x) => x.hand)" class="dot">{{ waiting.length || tiles.filter((x) => x.hand).length }}</span>
        </button>
        <button type="button" class="ctrl" :class="{ on: boardOpen }" :aria-pressed="boardOpen" @click="toggleBoard">
          <AppIcon name="edit" /><span>{{ t('meeting.board.title') }}</span>
          <span v-if="meeting.state.boardUnread && !boardOpen" class="dot" aria-hidden="true">•</span>
        </button>
        <div class="pop-wrap">
          <button type="button" class="ctrl" :class="{ on: moreOpen }" aria-haspopup="true" :aria-expanded="moreOpen" @click="moreOpen = !moreOpen; reactOpen = false">
            <AppIcon name="dots" /><span>{{ t('meeting.more') }}</span>
          </button>
          <div v-if="moreOpen" class="pop more-pop" role="menu" :aria-label="t('meeting.more')" @keydown.esc="moreOpen = false">
            <button type="button" role="menuitemradio" :aria-checked="view === 'gallery'" class="item" @click="view = 'gallery'; moreOpen = false"><AppIcon name="dashboard" :size="18" />{{ t('meeting.viewGallery') }}</button>
            <button type="button" role="menuitemradio" :aria-checked="view === 'speaker'" class="item" @click="view = 'speaker'; moreOpen = false"><AppIcon name="user" :size="18" />{{ t('meeting.viewSpeaker') }}</button>
            <button v-if="pipSupported" type="button" role="menuitem" class="item" @click="pictureInPicture"><AppIcon name="external" :size="18" />{{ t('meeting.pip') }}</button>
            <button v-if="!guest || recording" type="button" role="menuitem" class="item" @click="toggleRecording"><span class="rec-dot" aria-hidden="true" />{{ recording ? t('meeting.recordStop') : t('meeting.recordStart') }}</button>
            <button v-if="!callMode" type="button" role="menuitem" class="item" @click="togglePanel('breakouts')"><AppIcon name="spaces" :size="18" />{{ t('meeting.panels.breakouts') }}</button>
            <button v-if="!guest" type="button" role="menuitem" class="item" @click="togglePanel('notes')"><AppIcon name="clipboard" :size="18" />{{ t('meeting.panels.notes') }}</button>
            <button type="button" role="menuitem" class="item" @click="togglePanel('settings')"><AppIcon name="settings" :size="18" />{{ t('meeting.panels.settings') }}</button>
          </div>
        </div>
        <button type="button" class="ctrl leave" @click="hangUp">
          <AppIcon name="phoneOff" /><span>{{ t('meeting.leave') }}</span>
        </button>
      </nav>

      <BaseModal :open="recordConfirm" :title="t('meeting.recordTitle')" :description="t('meeting.recordText')" :confirm-label="t('meeting.recordStart')" @close="recordConfirm = false" @confirm="beginRecording" />
      <BaseModal :open="removing !== null" :title="t('meeting.removeTitle', { name: removing?.name ?? '' })" :description="t('meeting.removeText')" :confirm-label="t('meeting.remove')" tone="danger" @close="removing = null" @confirm="confirmRemove" />
    </template>

    <section v-else class="ended">
      <AppIcon name="checkCircle" :size="40" />
      <h1>{{ t('meeting.ended') }}</h1>
      <slot name="ended" />
    </section>
  </div>
</template>

<style scoped>
.meeting {
  --m-bg: #0f141c;
  --m-surface: #181f2b;
  --m-raised: #222b3a;
  --m-text: #eef1f6;
  --m-muted: #a9b3c3;
  --m-border: #2e384a;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  height: 100%;
  min-height: 0;
  background: var(--m-bg);
  color: var(--m-text);
}

.meeting.phase-room {
  grid-template-rows: auto 1fr auto;
}

.muted-light {
  color: var(--m-muted);
}

/* before joining */
.prejoin {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(280px, 1fr);
  gap: var(--space-6);
  align-items: center;
  max-width: 1100px;
  width: 100%;
  margin: auto;
  justify-self: center;
  padding: var(--space-6);
}

.preview-box {
  position: relative;
}

.preview {
  display: grid;
  place-items: center;
  gap: var(--space-2);
  width: 100%;
  aspect-ratio: 16 / 9;
  border-radius: 16px;
  background: #000;
  object-fit: cover;
}

.preview.off {
  align-content: center;
  padding-bottom: 72px; /* room for the buttons below */
  background: var(--m-surface);
  color: var(--m-muted);
}

.mirror {
  transform: scaleX(-1);
}

.pre-controls {
  position: absolute;
  left: 50%;
  bottom: 16px;
  display: flex;
  gap: var(--space-3);
  transform: translateX(-50%);
}

.round {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  border: 0;
  border-radius: 50%;
  background: rgb(255 255 255 / 0.16);
  color: #fff;
  cursor: pointer;
  backdrop-filter: blur(6px);
}

.round.off {
  background: #dc2626;
}

.pre-side {
  display: grid;
  gap: var(--space-3);
}

.eyebrow {
  color: var(--m-muted);
  font-weight: 600;
}

.media-note {
  margin: 0;
  padding: var(--space-3);
  border-radius: 10px;
  background: rgb(250 204 21 / 14%);
  color: #fde68a;
  font-size: var(--text-sm);
}

.pre-title {
  font-size: var(--text-2xl, 1.8rem);
}

.field {
  display: grid;
  gap: 4px;
  font-size: var(--text-sm);
  color: var(--m-muted);
}

.field .select {
  background: var(--m-surface);
  border-color: var(--m-border);
  color: var(--m-text);
}

.join-btn {
  min-height: 52px;
  font-size: var(--text-md);
}

/* in the meeting */
.top {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-5);
}

.room-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  font-size: var(--text-md);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.time,
.count {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--m-muted);
  font-variant-numeric: tabular-nums;
}

.body {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  min-height: 0;
  padding: 0 var(--space-4);
  gap: var(--space-4);
}

.body.with-panel {
  grid-template-columns: minmax(0, 1fr) 340px;
}

.stage {
  position: relative;
  display: grid;
  align-content: center;
  gap: var(--space-3);
  min-height: 0;
  overflow: auto;
}

.stage.sharing {
  grid-template-rows: 1fr auto;
  align-content: stretch;
}

.screen-stage {
  width: 100%;
  height: 100%;
  aspect-ratio: auto;
}

.grid {
  display: grid;
  gap: var(--space-3);
  width: 100%;
  max-width: 1400px;
  margin: 0 auto;
}

.grid.n1 {
  max-width: 1000px;
}

.grid.n2 {
  grid-template-columns: repeat(2, 1fr);
}

.grid.n3,
.grid.n4 {
  grid-template-columns: repeat(2, 1fr);
  max-width: 1100px;
}

.grid.n5,
.grid.n6,
.grid.n7,
.grid.n8,
.grid.n9 {
  grid-template-columns: repeat(3, 1fr);
}

.grid.strip {
  grid-template-columns: repeat(auto-fill, minmax(180px, 220px));
  justify-content: center;
}

.banner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  margin: 0 auto;
  padding: var(--space-2) var(--space-4);
  border-radius: 12px;
  background: var(--m-raised);
  font-weight: 600;
}

.banner.warn {
  background: #78350f;
}

.banner.guest {
  background: #1e3a8a;
}

.panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-height: 0;
  padding: var(--space-4);
  border-radius: 14px;
  background: var(--m-surface);
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.panel-head h2 {
  font-size: var(--text-md);
}

.icon-btn {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--m-text);
  cursor: pointer;
}

.icon-btn:hover {
  background: var(--m-raised);
}

.chat {
  display: grid;
  align-content: start;
  gap: var(--space-3);
  flex: 1;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}

.chat li {
  display: grid;
  gap: 2px;
  overflow-wrap: anywhere;
}

.chat li strong {
  font-size: 0.8rem;
  color: var(--m-muted);
}

.chat li.mine strong {
  color: #93c5fd;
}

.chat-form {
  display: flex;
  gap: var(--space-2);
}

.chat-form .input,
.notes {
  background: var(--m-bg);
  border-color: var(--m-border);
  color: var(--m-text);
}

.people {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.people li {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.people li span {
  flex: 1;
}

.waiting {
  display: grid;
  gap: var(--space-2);
  padding-top: var(--space-3);
  border-top: 1px solid var(--m-border);
}

.waiting h3 {
  font-size: var(--text-sm);
}

.waiting-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}

.waiting-row span {
  flex: 1;
}

.light {
  color: var(--m-text);
}

.invite {
  margin-top: auto;
}

.notes {
  flex: 1;
  min-height: 180px;
}

.notes-preview {
  max-height: 30%;
  overflow-y: auto;
  padding: var(--space-3);
  border-radius: 10px;
  background: var(--m-bg);
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4) var(--space-4);
}

.ctrl {
  position: relative;
  display: grid;
  justify-items: center;
  gap: 4px;
  min-width: 76px;
  padding: var(--space-2) var(--space-3);
  border: 0;
  border-radius: 12px;
  background: var(--m-raised);
  color: var(--m-text);
  font: inherit;
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 150ms ease-out;
}

.ctrl:hover {
  background: #2c3749;
}

.ctrl:focus-visible,
.round:focus-visible,
.icon-btn:focus-visible {
  outline: 3px solid #93c5fd;
  outline-offset: 2px;
}

.ctrl.off {
  background: #7f1d1d;
}

.ctrl.on {
  background: #1d4ed8;
}

.ctrl.leave {
  background: #dc2626;
}

.ctrl.leave:hover {
  background: #b91c1c;
}

.dot {
  position: absolute;
  top: 4px;
  right: 10px;
  display: grid;
  place-items: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 99px;
  background: #f59e0b;
  color: #1a1203;
  font-size: 0.7rem;
}

.ended {
  display: grid;
  place-items: center;
  align-content: center;
  gap: var(--space-4);
  padding: var(--space-6);
  text-align: center;
}

@media (max-width: 900px) {
  .prejoin {
    grid-template-columns: 1fr;
  }

  .body.with-panel {
    grid-template-columns: 1fr;
    grid-template-rows: 1fr 45%;
  }

  .grid.n3,
  .grid.n4,
  .grid.n5,
  .grid.n6,
  .grid.n7,
  .grid.n8,
  .grid.n9 {
    grid-template-columns: repeat(2, 1fr);
  }

  .grid.n2 {
    grid-template-columns: 1fr;
  }

  .ctrl {
    min-width: 0;
    padding: var(--space-2);
  }

  /* Icons only on small screens; the text stays for screen readers */
  .ctrl span:not(.dot) {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
}

@media (prefers-reduced-motion: reduce) {
  .ctrl {
    transition: none;
  }
}
/* device test */
.level-row {
  display: grid;
  gap: 4px;
}

.meter {
  display: block;
  height: 8px;
  overflow: hidden;
  border-radius: 99px;
  background: var(--m-raised);
}

.meter-fill {
  display: block;
  height: 100%;
  background: #4ade80;
  transform-origin: left;
  transition: transform 100ms linear;
}

.test-sound {
  justify-self: start;
}

/* recording */
.rec-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 10px;
  border-radius: 99px;
  background: #7f1d1d;
  font-size: 0.8rem;
  font-weight: 700;
}

.rec-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #ef4444;
}

.banner.rec {
  background: #7f1d1d;
}

.board-stage {
  min-height: 320px;
}

.audience {
  margin: 0;
  text-align: center;
}

/* people and moderation */
.people li {
  display: grid;
  gap: 4px;
  padding-bottom: var(--space-2);
  border-bottom: 1px solid var(--m-border);
}

.person {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.pname {
  flex: 1;
  min-width: 0;
}

.tag {
  margin-left: 6px;
  padding: 1px 7px;
  border-radius: 99px;
  background: var(--m-raised);
  color: var(--m-muted);
  font-size: 0.72rem;
  font-weight: 700;
}

.mod-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.mini {
  min-height: 30px;
  padding: 0 10px;
  border: 1px solid var(--m-border);
  border-radius: 8px;
  background: var(--m-raised);
  color: var(--m-text);
  font: inherit;
  font-size: 0.78rem;
  cursor: pointer;
}

.mini:hover {
  background: #2c3749;
}

.mini.danger {
  border-color: #7f1d1d;
  color: #fca5a5;
}

.switch-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  cursor: pointer;
}

.switch-row input {
  margin-top: 4px;
}

.block {
  display: block;
}

/* reactions and "more" menus */
.pop-wrap {
  position: relative;
}

.pop {
  position: absolute;
  z-index: 20;
  bottom: calc(100% + 8px);
  left: 50%;
  padding: 6px;
  border: 1px solid var(--m-border);
  border-radius: 14px;
  background: var(--m-surface);
  box-shadow: 0 12px 32px rgb(0 0 0 / 0.45);
  transform: translateX(-50%);
}

.reactions-pop {
  display: flex;
  gap: 2px;
}

.emoji {
  width: 44px;
  height: 44px;
  border: 0;
  border-radius: 10px;
  background: none;
  font-size: 1.5rem;
  cursor: pointer;
  transition: transform 120ms ease-out;
}

.emoji:hover {
  background: var(--m-raised);
  transform: scale(1.15);
}

.more-pop {
  display: grid;
  min-width: 240px;
}

.item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-height: 42px;
  padding: 0 var(--space-3);
  border: 0;
  border-radius: 8px;
  background: none;
  color: var(--m-text);
  font: inherit;
  font-size: var(--text-sm);
  text-align: left;
  cursor: pointer;
}

.item:hover,
.item[aria-checked='true'] {
  background: var(--m-raised);
}

.ctrl.locked {
  opacity: 0.55;
}

.emoji:focus-visible,
.item:focus-visible,
.mini:focus-visible {
  outline: 3px solid #93c5fd;
  outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  .ctrl,
  .meter-fill,
  .emoji {
    transition: none;
  }
}
</style>
