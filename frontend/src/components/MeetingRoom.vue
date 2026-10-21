<script setup lang="ts">
/**
 * OfficeHub's own meeting screen (built in, or on the company's Jitsi server): check camera and microphone,
 * then the video grid with controls, chat, people (and guests waiting to be let in) and shared notes.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import VideoTile from './VideoTile.vue'
import { ApiError, api } from '@/lib/api'
import { errorText, t } from '@/lib/i18n'
import { listDevices, previewTracks as makePreview, useMeeting, type JoinInfo, type MeetingMode, type Tile } from '@/lib/meeting'
import { renderMarkdown } from '@/lib/markdown'
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
}>()
const emit = defineEmits<{ left: [] }>()

const meeting = useMeeting()
const phase = ref<'prejoin' | 'room' | 'ended'>('prejoin')
const preview = ref<HTMLVideoElement | null>(null)
const previewTracks = ref<any[]>([])
const prefs = reactive({ mic: true, cam: true, camera: '', micId: '' })
const devices = ref<{ cameras: MediaDeviceInfo[]; mics: MediaDeviceInfo[] }>({ cameras: [], mics: [] })
const joining = ref(false)
const panel = ref<'chat' | 'people' | 'notes' | null>(null)
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

const tiles = computed(() => meeting.state.tiles)
const screenTile = computed<Tile | undefined>(() => tiles.value.find((x) => x.screen))
const others = computed(() => tiles.value.filter((x) => x !== screenTile.value))
const gridClass = computed(() => `n${Math.min(others.value.length, 9)}`)
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
  previewTracks.value = await makePreview(mode.value, wanted, { camera: prefs.camera || undefined, mic: prefs.micId || undefined })
  const video = previewTracks.value.find((x) => x.getType() === 'video')
  await nextTick()
  if (video && preview.value) video.attach(preview.value)
  devices.value = await listDevices()
  if (!previewTracks.value.some((x) => x.getType() === 'video')) prefs.cam = false
  if (!previewTracks.value.some((x) => x.getType() === 'audio')) prefs.mic = false
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
  } catch (e) {
    phase.value = 'prejoin'
    const code = (e as { code?: string })?.code
    showToast(e instanceof ApiError ? errorText(e) : code === 'meeting_full' ? t('errors.meeting_full') : t('meeting.connectFailed'), 'error')
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

function togglePanel(name: 'chat' | 'people' | 'notes') {
  panel.value = panel.value === name ? null : name
  if (name === 'chat') meeting.state.unread = 0
}

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
  if (event.key === 'm' || event.key === 'M') meeting.toggleMic()
  if (event.key === 'v' || event.key === 'V') meeting.toggleCam()
}

watch(() => meeting.state.chat.length, () => {
  if (panel.value === 'chat') {
    meeting.state.unread = 0
    nextTick(() => chatList.value?.scrollTo({ top: chatList.value.scrollHeight }))
  }
})
watch(() => meeting.state.status, (s) => {
  if (s === 'failed' && !joining.value) showToast(t('meeting.connectFailed'), 'error')
  if (s === 'left' && phase.value === 'room') hangUp()
})

onMounted(async () => {
  window.addEventListener('keydown', onKey)
  window.addEventListener('beforeunload', onUnload)
  ticker = window.setInterval(() => (now.value = Date.now()), 1000)
  try {
    mode.value = props.join?.connection.mode ?? (await api.get<{ mode: MeetingMode }>('/api/meetings/config')).mode
    await refreshPreview()
  } catch {
    showToast(t('meeting.libraryMissing'), 'error')
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
  window.removeEventListener('beforeunload', onUnload)
  window.clearInterval(heartbeat)
  window.clearInterval(ticker)
  for (const track of previewTracks.value) track.dispose?.()
  if (phase.value === 'room') hangUp()
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
        <button type="button" class="btn btn-primary join-btn" :disabled="joining" @click="enter">
          <AppIcon name="video" />{{ joining ? t('meeting.joining') : t('meeting.joinNow') }}
        </button>
        <p class="muted-light small">{{ t('meeting.privacy') }}</p>
      </div>
    </section>

    <!-- In the meeting -->
    <template v-else-if="phase === 'room'">
      <header class="top">
        <h1 class="room-title">{{ title }}</h1>
        <span class="time" :aria-label="t('meeting.duration')">{{ duration }}</span>
        <span class="count"><AppIcon name="users" :size="16" />{{ tiles.length }}</span>
      </header>

      <div class="body" :class="{ 'with-panel': panel }">
        <div class="stage" :class="{ sharing: screenTile }">
          <p v-if="callMode && callStatus === 'ringing'" class="banner" role="status"><AppIcon name="phone" :size="18" />{{ t('meeting.ringing', { name: callee }) }}</p>
          <p v-else-if="callMode && callStatus === 'declined'" class="banner warn" role="status">{{ t('meeting.declined', { name: callee }) }}</p>
          <p v-else-if="callMode && callStatus === 'missed'" class="banner warn" role="status">{{ t('meeting.noAnswer', { name: callee }) }}</p>
          <div v-for="g in waiting" :key="g.id" class="banner guest" role="alert">
            <span>{{ t('meeting.guestWaiting', { name: g.name }) }}</span>
            <button type="button" class="btn btn-primary" @click="decide(g.id, 'admit')">{{ t('meeting.admit') }}</button>
            <button type="button" class="btn btn-ghost light" @click="decide(g.id, 'deny')">{{ t('meeting.deny') }}</button>
          </div>
          <VideoTile v-if="screenTile" :tile="screenTile" large class="screen-stage" />
          <div class="grid" :class="[gridClass, { strip: screenTile }]">
            <VideoTile v-for="tile in others" :key="tile.id" :tile="tile" />
          </div>
          <p v-if="meeting.state.status === 'connecting'" class="banner" role="status">{{ t('meeting.connecting') }}</p>
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
            <ul class="people">
              <li v-for="tile in tiles" :key="tile.id">
                <span>{{ tile.name }}<template v-if="tile.local"> ({{ t('meeting.you') }})</template></span>
                <AppIcon v-if="tile.hand" name="hand" :size="16" :label="t('meeting.handRaised')" />
                <AppIcon :name="tile.audioMuted ? 'micOff' : 'mic'" :size="16" :label="tile.audioMuted ? t('meeting.micMuted') : t('meeting.micOn')" />
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
        </aside>
      </div>

      <nav class="toolbar" :aria-label="t('meeting.controls')">
        <button type="button" class="ctrl" :class="{ off: !meeting.state.micOn }" :aria-pressed="meeting.state.micOn" @click="meeting.toggleMic()">
          <AppIcon :name="meeting.state.micOn ? 'mic' : 'micOff'" /><span>{{ meeting.state.micOn ? t('meeting.mute') : t('meeting.unmute') }}</span>
        </button>
        <button type="button" class="ctrl" :class="{ off: !meeting.state.camOn }" :aria-pressed="meeting.state.camOn" @click="meeting.toggleCam()">
          <AppIcon :name="meeting.state.camOn ? 'video' : 'videoOff'" /><span>{{ meeting.state.camOn ? t('meeting.camStop') : t('meeting.camStart') }}</span>
        </button>
        <button type="button" class="ctrl" :class="{ on: meeting.state.sharing }" :aria-pressed="meeting.state.sharing" @click="meeting.state.sharing ? meeting.stopShare() : meeting.startShare()">
          <AppIcon name="screen" /><span>{{ meeting.state.sharing ? t('meeting.stopShare') : t('meeting.share') }}</span>
        </button>
        <button type="button" class="ctrl" :class="{ on: meeting.state.hand }" :aria-pressed="meeting.state.hand" @click="meeting.toggleHand()">
          <AppIcon name="hand" /><span>{{ t('meeting.hand') }}</span>
        </button>
        <button type="button" class="ctrl" :class="{ on: panel === 'chat' }" :aria-pressed="panel === 'chat'" @click="togglePanel('chat')">
          <AppIcon name="chat" /><span>{{ t('meeting.panels.chat') }}</span>
          <span v-if="meeting.state.unread && panel !== 'chat'" class="dot">{{ meeting.state.unread }}</span>
        </button>
        <button type="button" class="ctrl" :class="{ on: panel === 'people' }" :aria-pressed="panel === 'people'" @click="togglePanel('people')">
          <AppIcon name="users" /><span>{{ t('meeting.panels.people') }}</span>
          <span v-if="waiting.length" class="dot">{{ waiting.length }}</span>
        </button>
        <button v-if="!guest" type="button" class="ctrl" :class="{ on: panel === 'notes' }" :aria-pressed="panel === 'notes'" @click="togglePanel('notes')">
          <AppIcon name="edit" /><span>{{ t('meeting.panels.notes') }}</span>
        </button>
        <button type="button" class="ctrl leave" @click="hangUp">
          <AppIcon name="phoneOff" /><span>{{ t('meeting.leave') }}</span>
        </button>
      </nav>
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
</style>
