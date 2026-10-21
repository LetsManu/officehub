<script setup lang="ts">
/**
 * The box for writing a chat message: @mentions, "/" commands, sharing a file and recording a voice message.
 * Used for the conversation itself and for replies in a thread.
 */
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import UserAvatar from './UserAvatar.vue'
import { api } from '@/lib/api'
import { errorText, t } from '@/lib/i18n'
import { parseSlash, slashMatches, type SlashCommand } from '@/lib/slash'
import { findMentions } from '@/lib/spaces'
import { showToast } from '@/lib/toast'
import type { ChatMessage, SpaceFile, UserBrief } from '@/lib/types'

const props = defineProps<{
  channelId: number
  members: UserBrief[]
  placeholder: string
  inputId: string
  parentId?: number | null
  spaceId?: number | null
  commands?: boolean
}>()
const emit = defineEmits<{ sent: [message: ChatMessage]; command: [command: SlashCommand, rest: string] }>()

const VOICE_MAX_SECONDS = 300
const text = ref('')
const sending = ref(false)
const input = ref<HTMLTextAreaElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

async function post(fileId: number | null = null) {
  const body = text.value.trim()
  if ((!body && !fileId) || sending.value) return
  if (!fileId && props.commands) {
    const slash = parseSlash(body)
    if (slash) {
      text.value = ''
      emit('command', slash.command, slash.rest)
      return
    }
  }
  sending.value = true
  try {
    const message = await api.post<ChatMessage>(`/api/chat/${props.channelId}/messages`, {
      body, file_id: fileId, mentions: findMentions(body, props.members), parent_id: props.parentId ?? null,
    })
    if (!fileId) text.value = ''
    resize()
    emit('sent', message)
    input.value?.focus()
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    sending.value = false
  }
}

async function attach(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = ''
  if (!file || !props.spaceId) return
  const form = new FormData()
  form.append('file', file)
  try {
    const stored = await api.post<SpaceFile>(`/api/spaces/${props.spaceId}/files`, form)
    await post(stored.id)
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

// ---------- @mentions and "/" commands ----------

const mentionQuery = ref<string | null>(null)
const index = ref(0)
const suggestions = computed(() => {
  if (mentionQuery.value === null) return []
  const q = mentionQuery.value.toLowerCase()
  return props.members.filter((m) => m.full_name.toLowerCase().includes(q)).slice(0, 6)
})
const commandList = computed(() => (props.commands ? slashMatches(text.value) : []))

function resize() {
  const el = input.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 180)}px`
}

function onInput() {
  const el = input.value
  if (!el) return
  resize()
  const before = text.value.slice(0, el.selectionStart ?? text.value.length)
  const match = before.match(/(?:^|\s)@([\p{L} ]{0,30})$/u)
  mentionQuery.value = match ? match[1] : null
  index.value = 0
}

function pickMember(member: { full_name: string }) {
  const el = input.value
  if (!el) return
  const cursor = el.selectionStart ?? text.value.length
  const before = text.value.slice(0, cursor).replace(/@([\p{L} ]{0,30})$/u, `@${member.full_name} `)
  text.value = before + text.value.slice(cursor)
  mentionQuery.value = null
  nextTick(() => {
    el.focus()
    el.setSelectionRange(before.length, before.length)
  })
}

function pickCommand(command: SlashCommand) {
  if (command.takesText) {
    text.value = `/${command.name} `
    nextTick(() => input.value?.focus())
  } else {
    text.value = ''
    emit('command', command, '')
  }
}

function onKeydown(event: KeyboardEvent) {
  const list = suggestions.value.length ? suggestions.value : commandList.value
  if (list.length) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const step = event.key === 'ArrowDown' ? 1 : -1
      index.value = (index.value + step + list.length) % list.length
      return
    }
    if (event.key === 'Enter' || event.key === 'Tab') {
      event.preventDefault()
      if (suggestions.value.length) pickMember(suggestions.value[index.value])
      else pickCommand(commandList.value[index.value % commandList.value.length])
      return
    }
    if (event.key === 'Escape') {
      mentionQuery.value = null
      if (commandList.value.length) text.value = ''
      return
    }
  }
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    post()
  }
}

// ---------- voice messages ----------

const recording = ref(false)
const seconds = ref(0)
let recorder: MediaRecorder | null = null
let chunks: Blob[] = []
let clock: number | undefined
let discard = false

function audioType() {
  for (const type of ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4']) {
    if (MediaRecorder.isTypeSupported(type)) return type
  }
  return ''
}

async function startRecording() {
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
    showToast(t('chat.voiceUnavailable'), 'error')
    return
  }
  let stream: MediaStream
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
  } catch {
    showToast(t('chat.voiceNoMic'), 'error')
    return
  }
  const type = audioType()
  recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined)
  chunks = []
  discard = false
  seconds.value = 0
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data)
  recorder.onstop = () => {
    stream.getTracks().forEach((track) => track.stop())
    window.clearInterval(clock)
    recording.value = false
    if (!discard && seconds.value >= 1) uploadVoice(new Blob(chunks, { type: recorder?.mimeType || type || 'audio/webm' }))
  }
  recorder.start(1000)
  recording.value = true
  clock = window.setInterval(() => {
    seconds.value += 1
    if (seconds.value >= VOICE_MAX_SECONDS) recorder?.stop()
  }, 1000)
}

function stopRecording(keep: boolean) {
  discard = !keep
  if (recorder?.state === 'recording') recorder.stop()
}

async function uploadVoice(blob: Blob) {
  const form = new FormData()
  form.append('file', blob, 'voice')
  form.append('seconds', String(Math.max(1, seconds.value)))
  if (props.parentId) form.append('parent_id', String(props.parentId))
  sending.value = true
  try {
    emit('sent', await api.post<ChatMessage>(`/api/chat/${props.channelId}/voice`, form))
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    sending.value = false
  }
}

const elapsed = computed(() => `${Math.floor(seconds.value / 60)}:${String(seconds.value % 60).padStart(2, '0')}`)

function focus() {
  input.value?.focus()
}

defineExpose({ focus })
onBeforeUnmount(() => stopRecording(false))
</script>

<template>
  <div class="composer-wrap">
    <form class="composer" @submit.prevent="post()">
      <ul v-if="suggestions.length" class="suggest" role="listbox" :aria-label="t('chat.mention')">
        <li v-for="(m, i) in suggestions" :key="m.id" role="option" :aria-selected="i === index">
          <button type="button" :class="{ active: i === index }" @mousedown.prevent="pickMember(m)">
            <UserAvatar :id="m.id" :name="m.full_name" :photo-version="m.photo_version" :size="24" />{{ m.full_name }}
          </button>
        </li>
      </ul>
      <ul v-else-if="commandList.length" class="suggest" role="listbox" :aria-label="t('chat.commands')">
        <li v-for="(c, i) in commandList" :key="c.name" role="option" :aria-selected="i === index % commandList.length">
          <button type="button" :class="{ active: i === index % commandList.length }" @mousedown.prevent="pickCommand(c)">
            <AppIcon :name="c.icon" :size="18" />
            <span class="cmd"><strong>/{{ c.name }}</strong><span class="muted small">{{ t(`chat.slash.${c.name}`) }}</span></span>
          </button>
        </li>
      </ul>

      <template v-if="recording">
        <span class="rec" role="status"><span class="rec-dot" aria-hidden="true" />{{ t('chat.recording', { time: elapsed }) }}</span>
        <button type="button" class="btn btn-ghost" @click="stopRecording(false)">{{ t('app.cancel') }}</button>
        <button type="button" class="btn btn-primary" @click="stopRecording(true)"><AppIcon name="send" :size="18" />{{ t('chat.send') }}</button>
      </template>
      <template v-else>
        <button v-if="spaceId" type="button" class="btn btn-ghost btn-icon" :aria-label="t('chat.attach')" :title="t('chat.attach')" @click="fileInput?.click()"><AppIcon name="paperclip" /></button>
        <input ref="fileInput" type="file" class="visually-hidden" tabindex="-1" aria-hidden="true" @change="attach" />
        <label :for="inputId" class="visually-hidden">{{ t('chat.write') }}</label>
        <textarea
          :id="inputId"
          ref="input"
          v-model="text"
          class="textarea input-area"
          rows="1"
          maxlength="4000"
          :placeholder="placeholder"
          @input="onInput"
          @keydown="onKeydown"
        />
        <button v-if="!text.trim()" type="button" class="btn btn-ghost btn-icon" :disabled="sending" :aria-label="t('chat.recordVoice')" :title="t('chat.recordVoice')" @click="startRecording"><AppIcon name="mic" /></button>
        <button v-else type="submit" class="btn btn-primary btn-icon send" :disabled="sending" :aria-label="t('chat.send')"><AppIcon name="send" /></button>
      </template>
    </form>
  </div>
</template>

<style scoped>
.composer {
  position: relative;
  display: flex;
  align-items: flex-end;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4) 0;
  border-top: 1px solid var(--color-border);
}

.input-area {
  flex: 1;
  min-height: 44px;
  max-height: 180px;
  resize: none;
}

.send {
  flex-shrink: 0;
}

.rec {
  display: inline-flex;
  flex: 1;
  align-items: center;
  gap: var(--space-2);
  min-height: 44px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.rec-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--color-danger);
  animation: blink 1.2s ease-in-out infinite;
}

@keyframes blink {
  50% {
    opacity: 0.3;
  }
}

@media (prefers-reduced-motion: reduce) {
  .rec-dot {
    animation: none;
  }
}

.suggest {
  position: absolute;
  left: var(--space-4);
  bottom: calc(100% - 4px);
  z-index: var(--z-popover);
  display: grid;
  min-width: 260px;
  max-height: 320px;
  margin: 0;
  padding: 6px;
  overflow-y: auto;
  list-style: none;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-raised);
  box-shadow: var(--shadow-hover);
}

.suggest button {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  min-height: 38px;
  padding: 4px var(--space-2);
  border: 0;
  border-radius: var(--radius-sm);
  background: none;
  color: var(--color-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.suggest button.active,
.suggest button:hover {
  background: var(--color-neutral-soft);
}

.cmd {
  display: grid;
}
</style>
