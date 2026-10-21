<script setup lang="ts">
/**
 * One conversation: messages grouped by day and person, a composer with @mentions and file sharing.
 * New messages are fetched every few seconds while the page is visible.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import BaseModal from './BaseModal.vue'
import UserAvatar from './UserAvatar.vue'
import { useRouter } from 'vue-router'
import { api } from '@/lib/api'
import { errorText, formatDateLong, locale, t } from '@/lib/i18n'
import { publicConfig } from '@/lib/session'
import { refreshSummary } from '@/lib/summary'
import { fileIcon, fileSize, fileTone, findMentions, isOffice } from '@/lib/spaces'
import { showToast } from '@/lib/toast'
import type { ChatMessage, ChatPage, Conversation, SpaceFile } from '@/lib/types'

const props = defineProps<{ channelId: number }>()
const emit = defineEmits<{ updated: [conversation: Conversation] }>()

const POLL_MS = 3000
const router = useRouter()
const calling = ref(false)
const messages = ref<ChatMessage[]>([])
const members = ref<ChatPage['members']>([])
const conversation = ref<Conversation | null>(null)
const hasMore = ref(false)
const loading = ref(true)
const error = ref<string | null>(null)
const text = ref('')
const sending = ref(false)
const scroller = ref<HTMLElement | null>(null)
const input = ref<HTMLTextAreaElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
let timer: number | undefined

const lastId = computed(() => messages.value.at(-1)?.id ?? 0)

function time(iso: string) {
  return new Date(iso).toLocaleTimeString(locale.value, { hour: '2-digit', minute: '2-digit' })
}

/** Messages with a day header where the day changes and the name only where the author changes. */
const rows = computed(() => {
  const out: { message: ChatMessage; day: string | null; first: boolean }[] = []
  let lastDay = ''
  let lastAuthor: number | null = null
  let lastTime = 0
  for (const m of messages.value) {
    const day = m.created_at.slice(0, 10)
    const at = new Date(m.created_at).getTime()
    const first = day !== lastDay || m.author?.id !== lastAuthor || at - lastTime > 5 * 60_000
    out.push({ message: m, day: day !== lastDay ? m.created_at : null, first })
    lastDay = day
    lastAuthor = m.author?.id ?? null
    lastTime = at
  }
  return out
})

/** Split text so that @mentions of members can be highlighted (text stays escaped). */
function parts(body: string) {
  const names = members.value.map((m) => `@${m.full_name}`).sort((a, b) => b.length - a.length)
  if (!names.length) return [{ text: body, mention: false }]
  const escaped = names.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  return body.split(new RegExp(`(${escaped.join('|')})`, 'g')).filter(Boolean).map((p) => ({ text: p, mention: names.includes(p) }))
}

/** Start a call here: a direct chat rings the other person, a channel gets a "join" message. */
async function startCall() {
  calling.value = true
  try {
    const call = await api.post<{ meeting_id: number }>('/api/calls', { channel_id: props.channelId })
    router.push({ path: `/meetings/${call.meeting_id}/room`, query: { call: conversation.value?.kind === 'direct' ? '1' : undefined, from: router.currentRoute.value.fullPath } })
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    calling.value = false
  }
}

function atBottom() {
  const el = scroller.value
  return !el || el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

async function scrollDown() {
  await nextTick()
  if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
}

async function markRead() {
  if (!lastId.value || document.visibilityState !== 'visible') return
  await api.post(`/api/chat/${props.channelId}/read`, { last_id: lastId.value }).catch(() => undefined)
  refreshSummary(true)
}

async function load() {
  loading.value = true
  error.value = null
  try {
    const page = await api.get<ChatPage>(`/api/chat/${props.channelId}/messages`)
    messages.value = page.messages
    members.value = page.members
    conversation.value = page.conversation
    hasMore.value = page.has_more
    await scrollDown()
    markRead()
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

async function poll() {
  if (document.visibilityState !== 'visible' || loading.value) return
  try {
    const page = await api.get<ChatPage>(`/api/chat/${props.channelId}/messages?after=${lastId.value}`)
    if (page.messages.length) {
      const stick = atBottom()
      messages.value.push(...page.messages.filter((m) => !messages.value.some((x) => x.id === m.id)))
      if (stick) {
        await scrollDown()
        markRead()
      }
    }
    members.value = page.members
  } catch {
    /* try again next time */
  }
}

async function loadOlder() {
  const first = messages.value[0]?.id
  if (!first) return
  const el = scroller.value
  const before = el ? el.scrollHeight : 0
  const page = await api.get<ChatPage>(`/api/chat/${props.channelId}/messages?before=${first}`)
  messages.value.unshift(...page.messages)
  hasMore.value = page.has_more
  await nextTick()
  if (el) el.scrollTop = el.scrollHeight - before
}

async function send(fileId: number | null = null) {
  const body = text.value.trim()
  if ((!body && !fileId) || sending.value) return
  sending.value = true
  try {
    const message = await api.post<ChatMessage>(`/api/chat/${props.channelId}/messages`, {
      body, file_id: fileId, mentions: findMentions(body, members.value),
    })
    messages.value.push(message)
    if (!fileId) text.value = ''
    await scrollDown()
    input.value?.focus()
    if (conversation.value) emit('updated', conversation.value)
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
  if (!file || !conversation.value?.space_id) return
  const form = new FormData()
  form.append('file', file)
  try {
    const stored = await api.post<SpaceFile>(`/api/spaces/${conversation.value.space_id}/files`, form)
    await send(stored.id)
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

// ---------- @mentions ----------

const mentionQuery = ref<string | null>(null)
const mentionIndex = ref(0)
const suggestions = computed(() => {
  if (mentionQuery.value === null) return []
  const q = mentionQuery.value.toLowerCase()
  return members.value.filter((m) => m.full_name.toLowerCase().includes(q)).slice(0, 6)
})

function onInput() {
  const el = input.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 180)}px`
  const before = text.value.slice(0, el.selectionStart ?? text.value.length)
  const match = before.match(/(?:^|\s)@([\p{L} ]{0,30})$/u)
  mentionQuery.value = match ? match[1] : null
  mentionIndex.value = 0
}

function pick(member: { full_name: string }) {
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

function onKeydown(event: KeyboardEvent) {
  if (suggestions.value.length) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const step = event.key === 'ArrowDown' ? 1 : -1
      mentionIndex.value = (mentionIndex.value + step + suggestions.value.length) % suggestions.value.length
      return
    }
    if (event.key === 'Enter' || event.key === 'Tab') {
      event.preventDefault()
      pick(suggestions.value[mentionIndex.value])
      return
    }
    if (event.key === 'Escape') {
      mentionQuery.value = null
      return
    }
  }
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    send()
  }
}

// ---------- edit / delete own messages ----------

const editing = ref<ChatMessage | null>(null)
const editText = ref('')
const deleting = ref<ChatMessage | null>(null)

async function saveEdit() {
  if (!editing.value || !editText.value.trim()) return
  try {
    const updated = await api.put<ChatMessage>(`/api/chat/messages/${editing.value.id}`, { body: editText.value.trim() })
    messages.value = messages.value.map((m) => (m.id === updated.id ? updated : m))
    editing.value = null
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

async function confirmDelete() {
  if (!deleting.value) return
  try {
    await api.delete(`/api/chat/messages/${deleting.value.id}`)
    messages.value = messages.value.map((m) => (m.id === deleting.value!.id ? { ...m, deleted: true, body: '', file: null } : m))
    deleting.value = null
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

function onVisible() {
  if (document.visibilityState === 'visible') {
    poll()
    if (atBottom()) markRead()
  }
}

watch(() => props.channelId, load)
onMounted(() => {
  load()
  timer = window.setInterval(poll, POLL_MS)
  document.addEventListener('visibilitychange', onVisible)
})
onBeforeUnmount(() => {
  window.clearInterval(timer)
  document.removeEventListener('visibilitychange', onVisible)
})
</script>

<template>
  <section class="pane" :aria-label="conversation?.name ?? t('chat.title')">
    <header v-if="conversation" class="pane-head">
      <UserAvatar v-if="conversation.other" :id="conversation.other.id" :name="conversation.other.full_name" :photo-version="conversation.other.photo_version" :size="32" />
      <span v-else class="hash" aria-hidden="true">#</span>
      <div class="who">
        <h2 class="name">{{ conversation.name }}</h2>
        <p class="muted small">
          <template v-if="conversation.space_name">{{ conversation.space_name }} · </template>{{ t('chat.people', { n: members.length }) }}
        </p>
      </div>
      <button v-if="publicConfig?.meetings_enabled" type="button" class="btn btn-secondary call-btn" :disabled="calling" @click="startCall">
        <AppIcon name="video" :size="18" /><span>{{ conversation.kind === 'direct' ? t('chat.call') : t('chat.startCall') }}</span>
      </button>
    </header>

    <div ref="scroller" class="messages" role="log" aria-live="polite" :aria-busy="loading">
      <p v-if="error" class="notice notice-danger small">{{ error }}</p>
      <button v-if="hasMore" type="button" class="btn btn-ghost older" @click="loadOlder">{{ t('chat.older') }}</button>
      <p v-if="!loading && !messages.length && !error" class="empty muted">{{ t('chat.emptyConversation') }}</p>
      <template v-for="row in rows" :key="row.message.id">
        <div v-if="row.day" class="day"><span>{{ formatDateLong(row.day) }}</span></div>
        <article class="msg" :class="{ first: row.first, mine: row.message.mine }">
          <div class="avatar-col">
            <UserAvatar v-if="row.first && row.message.author" :id="row.message.author.id" :name="row.message.author.full_name" :photo-version="row.message.author.photo_version" :size="34" />
          </div>
          <div class="msg-body">
            <p v-if="row.first" class="meta">
              <strong>{{ row.message.author?.full_name ?? t('chat.formerColleague') }}</strong>
              <time :datetime="row.message.created_at" class="muted small">{{ time(row.message.created_at) }}</time>
            </p>
            <p v-if="row.message.deleted" class="muted deleted">{{ t('chat.deleted') }}</p>
            <template v-else>
              <div v-if="row.message.meeting" class="call-card" :class="{ over: !row.message.meeting.active }">
                <span class="call-icon"><AppIcon :name="row.message.meeting.active ? 'video' : 'phoneOff'" :size="18" /></span>
                <span class="call-text">{{ row.message.meeting.active ? t('chat.callActive') : t('chat.callEnded') }}</span>
                <RouterLink v-if="row.message.meeting.active" :to="{ path: `/meetings/${row.message.meeting.id}/room`, query: { from: router.currentRoute.value.fullPath } }" class="btn btn-primary">{{ t('chat.joinCall') }}</RouterLink>
              </div>
              <p v-if="row.message.body" class="text"><span v-for="(p, i) in parts(row.message.body)" :key="i" :class="{ mention: p.mention }">{{ p.text }}</span><span v-if="row.message.edited" class="muted small"> ({{ t('chat.edited') }})</span></p>
              <div v-if="row.message.file" class="file">
                <span class="ficon" :class="`pc-${fileTone(row.message.file.file_type)}`"><AppIcon :name="fileIcon(row.message.file.file_type)" :size="18" /></span>
                <span class="fname">{{ row.message.file.name }}<span class="muted small"> · {{ fileSize(row.message.file.size) }}</span></span>
                <RouterLink v-if="isOffice(row.message.file.file_type)" :to="`/office/${row.message.file.id}`" class="btn btn-ghost btn-icon" :aria-label="t('files.edit')"><AppIcon name="edit" :size="18" /></RouterLink>
                <a class="btn btn-ghost btn-icon" :href="`/api/spaces/files/${row.message.file.id}/download`" download :aria-label="t('files.download')"><AppIcon name="download" :size="18" /></a>
              </div>
            </template>
            <span v-if="!row.first" class="hover-time muted small" aria-hidden="true">{{ time(row.message.created_at) }}</span>
          </div>
          <div v-if="row.message.mine && !row.message.deleted" class="msg-actions">
            <button v-if="row.message.body" type="button" class="btn btn-ghost btn-icon" :aria-label="t('chat.edit')" @click="editing = row.message; editText = row.message.body"><AppIcon name="edit" :size="16" /></button>
            <button type="button" class="btn btn-ghost btn-icon" :aria-label="t('chat.delete')" @click="deleting = row.message"><AppIcon name="trash" :size="16" /></button>
          </div>
        </article>
      </template>
    </div>

    <form class="composer" @submit.prevent="send()">
      <ul v-if="suggestions.length" class="suggest" role="listbox" :aria-label="t('chat.mention')">
        <li v-for="(m, i) in suggestions" :key="m.id" role="option" :aria-selected="i === mentionIndex">
          <button type="button" :class="{ active: i === mentionIndex }" @mousedown.prevent="pick(m)">
            <UserAvatar :id="m.id" :name="m.full_name" :photo-version="m.photo_version" :size="24" />{{ m.full_name }}
          </button>
        </li>
      </ul>
      <button v-if="conversation?.space_id" type="button" class="btn btn-ghost btn-icon" :aria-label="t('chat.attach')" :title="t('chat.attach')" @click="fileInput?.click()"><AppIcon name="paperclip" /></button>
      <input ref="fileInput" type="file" class="visually-hidden" tabindex="-1" aria-hidden="true" @change="attach" />
      <label for="chat-input" class="visually-hidden">{{ t('chat.write') }}</label>
      <textarea
        id="chat-input"
        ref="input"
        v-model="text"
        class="textarea input-area"
        rows="1"
        maxlength="4000"
        :placeholder="conversation ? t('chat.writeTo', { name: conversation.name }) : t('chat.write')"
        @input="onInput"
        @keydown="onKeydown"
      />
      <button type="submit" class="btn btn-primary btn-icon send" :disabled="!text.trim() || sending" :aria-label="t('chat.send')"><AppIcon name="send" /></button>
    </form>
    <p class="hint muted small">{{ t('chat.hint') }}</p>

    <BaseModal :open="editing !== null" :title="t('chat.edit')" :confirm-label="t('app.save')" @close="editing = null" @confirm="saveEdit">
      <label for="chat-edit" class="visually-hidden">{{ t('chat.edit') }}</label>
      <textarea id="chat-edit" v-model="editText" class="textarea" rows="4" maxlength="4000" />
    </BaseModal>
    <BaseModal :open="deleting !== null" :title="t('chat.deleteTitle')" :description="t('chat.deleteText')" :confirm-label="t('chat.delete')" tone="danger" @close="deleting = null" @confirm="confirmDelete" />
  </section>
</template>

<style scoped>
.pane {
  display: grid;
  grid-template-rows: auto 1fr auto auto;
  min-height: 0;
  height: 100%;
  background: var(--color-surface);
}

.pane-head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--color-border);
}

.call-btn {
  margin-left: auto;
}

@media (max-width: 560px) {
  .call-btn span {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
}

.call-card {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  margin-top: 2px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
}

.call-icon {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border-radius: 50%;
  background: var(--color-success-soft);
  color: var(--color-success);
}

.call-card.over .call-icon {
  background: var(--color-neutral-soft);
  color: var(--color-text-muted);
}

.call-text {
  font-weight: 600;
}

.hash {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  background: var(--color-neutral-soft);
  color: var(--color-text-muted);
  font-weight: 700;
}

.name {
  font-size: var(--text-md);
}

.messages {
  min-height: 0;
  padding: var(--space-3) 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.older {
  display: block;
  margin: 0 auto var(--space-3);
}

.empty {
  padding: var(--space-8) var(--space-5);
  text-align: center;
}

.day {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin: var(--space-4) var(--space-5) var(--space-2);
  color: var(--color-text-muted);
  font-size: 0.78rem;
  font-weight: 600;
}

.day::before,
.day::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--color-border);
}

.msg {
  position: relative;
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) auto;
  gap: var(--space-2);
  padding: 2px var(--space-5);
}

.msg.first {
  margin-top: var(--space-3);
}

.msg:hover {
  background: var(--color-surface-muted);
}

.meta {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
}

.text {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.mention {
  padding: 0 3px;
  border-radius: 4px;
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
  font-weight: 600;
}

.deleted {
  font-style: italic;
}

.file {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  max-width: 100%;
  margin-top: 4px;
  padding: var(--space-2) var(--space-2) var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}

.fname {
  min-width: 0;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.hover-time {
  position: absolute;
  left: var(--space-5);
  top: 4px;
  width: 44px;
  text-align: center;
  font-size: 0.7rem;
  opacity: 0;
}

.msg:hover .hover-time {
  opacity: 1;
}

.msg-actions {
  display: flex;
  opacity: 0;
}

.msg:hover .msg-actions,
.msg:focus-within .msg-actions {
  opacity: 1;
}

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

.hint {
  padding: 4px var(--space-4) var(--space-3);
}

.suggest {
  position: absolute;
  left: var(--space-4);
  bottom: calc(100% - 4px);
  z-index: var(--z-popover);
  display: grid;
  min-width: 240px;
  margin: 0;
  padding: 6px;
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
  padding: 0 var(--space-2);
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

@media (hover: none) {
  .msg-actions {
    opacity: 1;
  }
}
</style>
