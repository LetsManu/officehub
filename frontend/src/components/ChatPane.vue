<script setup lang="ts">
/**
 * One conversation, like a channel in Discord: messages grouped by day and person with formatting, reactions,
 * threads, pins, polls and voice messages; "/" commands in the composer; notification settings per conversation.
 * New and changed messages are fetched every few seconds while the page is visible.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from './AppIcon.vue'
import BaseModal from './BaseModal.vue'
import ChatComposer from './ChatComposer.vue'
import ChatMessageItem from './ChatMessageItem.vue'
import ChatPollForm from './ChatPollForm.vue'
import ChatThread from './ChatThread.vue'
import UserAvatar from './UserAvatar.vue'
import { api } from '@/lib/api'
import { errorText, formatDateLong, t } from '@/lib/i18n'
import { startCall } from '@/lib/calls'
import { activityText, changeMyPresence, myPresence, presence, type ManualPresence } from '@/lib/presence'
import { currentUser, publicConfig } from '@/lib/session'
import type { SlashCommand } from '@/lib/slash'
import { refreshSummary } from '@/lib/summary'
import { showToast } from '@/lib/toast'
import type { ChatMessage, ChatPage, Conversation, MessageAction } from '@/lib/types'

const props = defineProps<{ channelId: number }>()
const emit = defineEmits<{ updated: [conversation: Conversation] }>()

const POLL_MS = 3000
const MUTE_CHOICES = [60, 8 * 60, 24 * 60, 7 * 24 * 60]
const route = useRoute()
const router = useRouter()
const calling = ref(false)
const messages = ref<ChatMessage[]>([])
const members = ref<ChatPage['members']>([])
const conversation = ref<Conversation | null>(null)
const hasMore = ref(false)
const loading = ref(true)
const error = ref<string | null>(null)
const scroller = ref<HTMLElement | null>(null)
const composer = ref<InstanceType<typeof ChatComposer> | null>(null)
const thread = ref<InstanceType<typeof ChatThread> | null>(null)
let serverTime = ''
let timer: number | undefined

const lastId = computed(() => messages.value.at(-1)?.id ?? 0)
const otherActivity = computed(() => (conversation.value?.other ? activityText(presence.get(conversation.value.other.id)) : ''))

/** Messages with a day header where the day changes and the name only where the author changes. */
const rows = computed(() => {
  const out: { message: ChatMessage; day: string | null; first: boolean }[] = []
  let lastDay = ''
  let lastAuthor: number | null = null
  let lastTime = 0
  for (const m of messages.value) {
    const day = m.created_at.slice(0, 10)
    const at = new Date(m.created_at).getTime()
    const first = day !== lastDay || m.author?.id !== lastAuthor || at - lastTime > 5 * 60_000 || m.kind === 'poll'
    out.push({ message: m, day: day !== lastDay ? m.created_at : null, first })
    lastDay = day
    lastAuthor = m.author?.id ?? null
    lastTime = at
  }
  return out
})

/** Start a call here: a direct chat rings the other person, a channel gets a "join" message. */
async function call() {
  calling.value = true
  await startCall(router, { channel_id: props.channelId }, conversation.value?.kind === 'direct')
  calling.value = false
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
    serverTime = page.server_time ?? ''
    await scrollDown()
    markRead()
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

/** Show a changed message everywhere it appears (conversation, thread, pinned list). */
function apply(message: ChatMessage) {
  if (message.parent_id == null) messages.value = messages.value.map((m) => (m.id === message.id ? message : m))
  pins.value = message.pinned ? (pins.value.some((m) => m.id === message.id) ? pins.value.map((m) => (m.id === message.id ? message : m)) : pins.value) : pins.value.filter((m) => m.id !== message.id)
  thread.value?.apply(message)
}

async function poll() {
  if (document.visibilityState !== 'visible' || loading.value) return
  try {
    const since = serverTime ? `&since=${encodeURIComponent(serverTime)}` : ''
    const page = await api.get<ChatPage>(`/api/chat/${props.channelId}/messages?after=${lastId.value}${since}`)
    serverTime = page.server_time ?? serverTime
    for (const m of page.changed ?? []) apply(m)
    if (page.messages.length) {
      const stick = atBottom()
      messages.value.push(...page.messages.filter((m) => !messages.value.some((x) => x.id === m.id)))
      if (stick) {
        await scrollDown()
        markRead()
      }
    }
    members.value = page.members
    conversation.value = page.conversation
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

async function sent(message: ChatMessage) {
  messages.value.push(message)
  await scrollDown()
  if (conversation.value) emit('updated', conversation.value)
}

// ---------- reactions, pins, polls, edit and delete ----------

const editing = ref<ChatMessage | null>(null)
const editText = ref('')
const deleting = ref<ChatMessage | null>(null)

async function act(kind: MessageAction | 'pin', message: ChatMessage, value?: string | number[]) {
  if (kind === 'edit') {
    editing.value = message
    editText.value = message.body
    return
  }
  if (kind === 'remove') {
    deleting.value = message
    return
  }
  const base = `/api/chat/messages/${message.id}`
  try {
    if (kind === 'react') apply(await api.post<ChatMessage>(`${base}/reactions`, { emoji: value }))
    else if (kind === 'vote') apply(await api.post<ChatMessage>(`${base}/vote`, { option_ids: value }))
    else if (kind === 'closePoll') apply(await api.post<ChatMessage>(`${base}/close-poll`))
    else if (kind === 'pin') {
      const updated = await api.post<ChatMessage>(`${base}/pin`)
      apply(updated)
      if (updated.pinned) pins.value.unshift(updated)
      showToast(updated.pinned ? t('chat.pinnedToast') : t('chat.unpinnedToast'))
    }
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

async function saveEdit() {
  if (!editing.value || !editText.value.trim()) return
  try {
    apply(await api.put<ChatMessage>(`/api/chat/messages/${editing.value.id}`, { body: editText.value.trim() }))
    editing.value = null
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

async function confirmDelete() {
  const message = deleting.value
  if (!message) return
  try {
    await api.delete(`/api/chat/messages/${message.id}`)
    apply({ ...message, deleted: true, body: '', file: null, poll: null, reactions: [], pinned: false, audio_seconds: null })
    deleting.value = null
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

// ---------- thread and pinned messages (shown next to the conversation) ----------

const threadId = computed(() => (typeof route.query.thread === 'string' && /^\d+$/.test(route.query.thread) ? Number(route.query.thread) : null))
const pinsOpen = ref(false)
const pins = ref<ChatMessage[]>([])

function openThread(message: ChatMessage) {
  pinsOpen.value = false
  router.replace({ query: { ...route.query, thread: String(message.id) } })
}

function closeSide() {
  pinsOpen.value = false
  if (threadId.value !== null) {
    const { thread: _drop, ...rest } = route.query
    router.replace({ query: rest })
  }
}

async function togglePins() {
  if (pinsOpen.value) {
    pinsOpen.value = false
    return
  }
  closeSide()
  pinsOpen.value = true
  try {
    pins.value = await api.get<ChatMessage[]>(`/api/chat/${props.channelId}/pins`)
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

function jumpTo(message: ChatMessage) {
  const el = document.getElementById(`msg-${message.id}`)
  if (!el) {
    showToast(t('chat.pinNotLoaded'))
    return
  }
  el.scrollIntoView({ block: 'center', behavior: 'smooth' })
  el.classList.add('flash')
  window.setTimeout(() => el.classList.remove('flash'), 1600)
  if (window.matchMedia('(max-width: 899px)').matches) pinsOpen.value = false
}

// ---------- notification settings for this conversation ----------

const notifyOpen = ref(false)
const notifyRoot = ref<HTMLElement | null>(null)

async function saveSettings(change: { notify?: 'all' | 'mentions' | 'none'; mute_minutes?: number }) {
  if (!conversation.value) return
  try {
    conversation.value = await api.put<Conversation>(`/api/chat/${props.channelId}/settings`, { notify: conversation.value.notify ?? 'all', ...change })
    emit('updated', conversation.value)
    refreshSummary(true)
    if (change.mute_minutes !== undefined) showToast(change.mute_minutes ? t('chat.mutedToast') : t('chat.unmutedToast'))
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

function muteLabel(minutes: number) {
  return t(`chat.muteFor.m${minutes}`)
}

function onDocumentClick(event: MouseEvent) {
  if (notifyOpen.value && notifyRoot.value && !notifyRoot.value.contains(event.target as Node)) notifyOpen.value = false
}

// ---------- "/" commands ----------

const pollOpen = ref(false)
const pollQuestion = ref('')

async function setPresence(manual: ManualPresence, text = myPresence.value.text) {
  try {
    await changeMyPresence(manual, text, currentUser.value?.id)
    showToast(t('chat.statusSet', { state: t(`presence.choices.${manual}`) }))
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

function command(c: SlashCommand, rest: string) {
  const space = conversation.value?.space_id
  switch (c.name) {
    case 'umfrage':
      pollQuestion.value = rest
      pollOpen.value = true
      break
    case 'anruf':
      if (publicConfig.value?.meetings_enabled) call()
      break
    case 'meeting':
      router.push('/meetings?new=1')
      break
    case 'status':
      setPresence(myPresence.value.manual, rest.slice(0, 120))
      break
    case 'nichtstoeren':
      setPresence('dnd')
      break
    case 'weg':
      setPresence('away')
      break
    case 'da':
      setPresence('auto')
      break
    case 'urlaub':
      router.push('/requests/new/vacation')
      break
    case 'homeoffice':
      router.push('/requests/new/home_office')
      break
    case 'raum':
      router.push('/rooms')
      break
    case 'aufgabe':
      router.push(space ? `/spaces/${space}/board` : '/tasks')
      break
  }
}

async function pollCreated(message: ChatMessage) {
  pollOpen.value = false
  await sent(message)
}

function onVisible() {
  if (document.visibilityState === 'visible') {
    poll()
    if (atBottom()) markRead()
  }
}

watch(() => props.channelId, () => {
  closeSide()
  load()
})
onMounted(() => {
  load()
  timer = window.setInterval(poll, POLL_MS)
  document.addEventListener('visibilitychange', onVisible)
  document.addEventListener('click', onDocumentClick)
})
onBeforeUnmount(() => {
  window.clearInterval(timer)
  document.removeEventListener('visibilitychange', onVisible)
  document.removeEventListener('click', onDocumentClick)
})
</script>

<template>
  <section class="pane" :aria-label="conversation?.name ?? t('chat.title')">
    <header v-if="conversation" class="pane-head">
      <UserAvatar v-if="conversation.other" :id="conversation.other.id" :name="conversation.other.full_name" :photo-version="conversation.other.photo_version" :size="32" status />
      <span v-else class="hash" aria-hidden="true">#</span>
      <div class="who">
        <h2 class="name">{{ conversation.name }}</h2>
        <p class="muted small">
          <template v-if="otherActivity"><span class="activity">{{ otherActivity }}</span></template>
          <template v-else><template v-if="conversation.space_name">{{ conversation.space_name }} · </template>{{ t('chat.people', { n: members.length }) }}</template>
        </p>
      </div>
      <div class="head-actions">
        <button type="button" class="btn btn-ghost btn-icon" :aria-pressed="pinsOpen" :aria-label="t('chat.pinnedTitle')" :title="t('chat.pinnedTitle')" @click="togglePins"><AppIcon name="pin" :size="18" /></button>
        <div ref="notifyRoot" class="notify">
          <button
            type="button"
            class="btn btn-ghost btn-icon"
            :class="{ quiet: conversation.muted || conversation.notify !== 'all' }"
            aria-haspopup="true"
            :aria-expanded="notifyOpen"
            :aria-label="t('chat.notifyTitle')"
            :title="t('chat.notifyTitle')"
            @click="notifyOpen = !notifyOpen"
          >
            <AppIcon name="bell" :size="18" /><span v-if="conversation.muted" class="muted-mark" aria-hidden="true" />
          </button>
          <div v-if="notifyOpen" class="menu" role="menu" :aria-label="t('chat.notifyTitle')" @keydown.esc="notifyOpen = false">
            <p class="menu-label">{{ t('chat.notifyTitle') }}</p>
            <button v-for="level in (['all', 'mentions', 'none'] as const)" :key="level" type="button" role="menuitemradio" :aria-checked="(conversation.notify ?? 'all') === level" class="menu-item" @click="saveSettings({ notify: level })">
              <span class="grow">{{ t(`chat.notify.${level}`) }}</span>
              <AppIcon v-if="(conversation.notify ?? 'all') === level" name="check" :size="16" />
            </button>
            <p class="menu-label">{{ conversation.muted ? t('chat.mutedNow') : t('chat.mute') }}</p>
            <button v-if="conversation.muted" type="button" role="menuitem" class="menu-item" @click="saveSettings({ mute_minutes: 0 }); notifyOpen = false">{{ t('chat.unmute') }}</button>
            <button v-for="minutes in MUTE_CHOICES" v-else :key="minutes" type="button" role="menuitem" class="menu-item" @click="saveSettings({ mute_minutes: minutes }); notifyOpen = false">{{ muteLabel(minutes) }}</button>
          </div>
        </div>
        <button v-if="publicConfig?.meetings_enabled" type="button" class="btn btn-secondary call-btn" :disabled="calling" @click="call">
          <AppIcon name="video" :size="18" /><span>{{ conversation.kind === 'direct' ? t('chat.call') : t('chat.startCall') }}</span>
        </button>
      </div>
    </header>

    <div class="body" :class="{ split: threadId !== null || pinsOpen }">
      <div class="main">
        <div ref="scroller" class="messages" role="log" aria-live="polite" :aria-busy="loading">
          <p v-if="error" class="notice notice-danger small">{{ error }}</p>
          <button v-if="hasMore" type="button" class="btn btn-ghost older" @click="loadOlder">{{ t('chat.older') }}</button>
          <p v-if="!loading && !messages.length && !error" class="empty muted">{{ t('chat.emptyConversation') }}</p>
          <template v-for="row in rows" :key="row.message.id">
            <div v-if="row.day" class="day"><span>{{ formatDateLong(row.day) }}</span></div>
            <ChatMessageItem
              :id="`msg-${row.message.id}`"
              :message="row.message"
              :first="row.first"
              :members="members"
              can-write
              @react="(e) => act('react', row.message, e)"
              @reply="openThread(row.message)"
              @pin="act('pin', row.message)"
              @vote="(ids) => act('vote', row.message, ids)"
              @close-poll="act('closePoll', row.message)"
              @edit="act('edit', row.message)"
              @remove="act('remove', row.message)"
            />
          </template>
        </div>
        <ChatComposer
          ref="composer"
          :channel-id="channelId"
          :members="members"
          :space-id="conversation?.space_id"
          input-id="chat-input"
          commands
          :placeholder="conversation ? t('chat.writeTo', { name: conversation.name }) : t('chat.write')"
          @sent="sent"
          @command="command"
        />
        <p class="hint muted small">{{ t('chat.hint') }}</p>
      </div>

      <ChatThread
        v-if="threadId !== null"
        ref="thread"
        :channel-id="channelId"
        :parent-id="threadId"
        :members="members"
        :space-id="conversation?.space_id ?? null"
        can-write
        @close="closeSide"
        @action="act"
        @replied="apply"
      />
      <aside v-else-if="pinsOpen" class="side" :aria-label="t('chat.pinnedTitle')">
        <header class="side-head">
          <h3 class="h3">{{ t('chat.pinnedTitle') }}</h3>
          <button type="button" class="btn btn-ghost btn-icon" :aria-label="t('app.close')" @click="closeSide"><AppIcon name="close" :size="18" /></button>
        </header>
        <div class="side-body">
          <p v-if="!pins.length" class="empty muted">{{ t('chat.noPins') }}</p>
          <div v-for="p in pins" :key="p.id" class="pinned-item">
            <ChatMessageItem :message="p" first in-thread :members="members" @react="(e) => act('react', p, e)" @vote="(ids) => act('vote', p, ids)" @edit="act('edit', p)" @remove="act('remove', p)" />
            <div class="pinned-actions">
              <button type="button" class="link-btn" @click="jumpTo(p)">{{ t('chat.jumpTo') }}</button>
              <button type="button" class="link-btn" @click="act('pin', p)">{{ t('chat.unpin') }}</button>
            </div>
          </div>
        </div>
      </aside>
    </div>

    <BaseModal :open="editing !== null" :title="t('chat.edit')" :confirm-label="t('app.save')" @close="editing = null" @confirm="saveEdit">
      <label for="chat-edit" class="visually-hidden">{{ t('chat.edit') }}</label>
      <textarea id="chat-edit" v-model="editText" class="textarea" rows="4" maxlength="4000" />
    </BaseModal>
    <BaseModal :open="deleting !== null" :title="t('chat.deleteTitle')" :description="t('chat.deleteText')" :confirm-label="t('chat.delete')" tone="danger" @close="deleting = null" @confirm="confirmDelete" />
    <ChatPollForm :open="pollOpen" :channel-id="channelId" :question="pollQuestion" @close="pollOpen = false" @created="pollCreated" />
  </section>
</template>

<style scoped>
.pane {
  position: relative;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
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

.who {
  min-width: 0;
}

.activity {
  color: var(--color-primary-text);
  font-weight: 600;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: var(--space-1, 4px);
  margin-left: auto;
}

.call-btn {
  margin-left: var(--space-2);
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

.notify {
  position: relative;
}

.quiet {
  color: var(--color-text-muted);
}

.muted-mark {
  position: absolute;
  width: 22px;
  height: 2px;
  background: currentColor;
  transform: rotate(-45deg);
}

.menu {
  position: absolute;
  z-index: var(--z-popover);
  top: calc(100% + 6px);
  right: 0;
  display: grid;
  width: 260px;
  padding: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface-raised);
  box-shadow: var(--shadow-overlay);
}

.menu-label {
  margin: var(--space-2) var(--space-2) 2px;
  color: var(--color-text-muted);
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.menu-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 40px;
  padding: 0 var(--space-2);
  border: 0;
  border-radius: var(--radius-md);
  background: none;
  color: var(--color-text);
  font: inherit;
  font-size: var(--text-sm);
  text-align: left;
  cursor: pointer;
}

.menu-item:hover {
  background: var(--color-surface-muted);
}

.grow {
  flex: 1;
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

.body {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  min-height: 0;
}

.body.split {
  grid-template-columns: minmax(0, 1fr) minmax(300px, 380px);
}

.main {
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto auto;
  min-height: 0;
}

@media (max-width: 899px) {
  .body.split {
    grid-template-columns: minmax(0, 1fr);
  }

  .body.split > :last-child {
    position: absolute;
    inset: 0;
    z-index: 5;
    border-left: 0;
  }
}

.messages {
  min-height: 0;
  padding: var(--space-3) 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.messages :deep(.msg.flash) {
  background: var(--color-warning-soft, var(--color-surface-muted));
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

.hint {
  padding: 4px var(--space-4) var(--space-3);
}

.side {
  display: grid;
  grid-template-rows: auto 1fr;
  min-height: 0;
  border-left: 1px solid var(--color-border);
  background: var(--color-surface);
}

.side-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.side-body {
  min-height: 0;
  padding-bottom: var(--space-3);
  overflow-y: auto;
}

.pinned-item {
  border-bottom: 1px solid var(--color-border);
  padding-bottom: var(--space-2);
}

.pinned-actions {
  display: flex;
  gap: var(--space-4);
  padding: 2px var(--space-5) 0 calc(var(--space-5) + 54px);
}
.pinned-actions .link-btn {
  min-height: 32px;
  padding: 0;
  border: 0;
  background: none;
  color: var(--color-primary);
  font: inherit;
  font-size: var(--text-sm);
  font-weight: 600;
  cursor: pointer;
}

.pinned-actions .link-btn:hover {
  text-decoration: underline;
}
</style>
