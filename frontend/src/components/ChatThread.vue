<script setup lang="ts">
/** Replies to one message, next to the conversation (like a thread in Discord or Teams). */
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import ChatComposer from './ChatComposer.vue'
import ChatMessageItem from './ChatMessageItem.vue'
import { api } from '@/lib/api'
import { errorText, t } from '@/lib/i18n'
import type { ChatMessage, ChatThread, MessageAction, UserBrief } from '@/lib/types'

const props = defineProps<{ channelId: number; parentId: number; members: UserBrief[]; canWrite: boolean; spaceId: number | null }>()
const emit = defineEmits<{
  close: []
  action: [kind: MessageAction, message: ChatMessage, value?: string | number[]]
  replied: [parent: ChatMessage]
}>()

const POLL_MS = 3000
const parent = ref<ChatMessage | null>(null)
const replies = ref<ChatMessage[]>([])
const error = ref<string | null>(null)
const scroller = ref<HTMLElement | null>(null)
const composer = ref<InstanceType<typeof ChatComposer> | null>(null)
let timer: number | undefined

async function load(scroll = false) {
  if (document.visibilityState !== 'visible') return
  try {
    const data = await api.get<ChatThread>(`/api/chat/messages/${props.parentId}/thread`)
    const el = scroller.value
    const stick = !el || el.scrollHeight - el.scrollTop - el.clientHeight < 80
    const grew = data.replies.length > replies.value.length
    parent.value = data.parent
    replies.value = data.replies
    error.value = null
    if (scroll || (grew && stick)) {
      await nextTick()
      if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
    }
  } catch (e) {
    error.value = errorText(e)
  }
}

/** A message changed (a reaction, an edit …): show it right away. */
function apply(message: ChatMessage) {
  if (parent.value?.id === message.id) parent.value = message
  replies.value = replies.value.map((m) => (m.id === message.id ? message : m))
}

async function sent(message: ChatMessage) {
  replies.value.push(message)
  await nextTick()
  if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
  if (parent.value) {
    parent.value = { ...parent.value, reply_count: (parent.value.reply_count ?? 0) + 1, last_reply_at: message.created_at }
    emit('replied', parent.value)
  }
}

defineExpose({ apply })
watch(() => props.parentId, () => {
  parent.value = null
  replies.value = []
  load(true)
})
onMounted(() => {
  load(true).then(() => composer.value?.focus())
  timer = window.setInterval(load, POLL_MS)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <aside class="thread" :aria-label="t('chat.thread')">
    <header class="side-head">
      <h3 class="h3">{{ t('chat.thread') }}</h3>
      <button type="button" class="btn btn-ghost btn-icon" :aria-label="t('app.close')" @click="emit('close')"><AppIcon name="close" :size="18" /></button>
    </header>
    <div ref="scroller" class="side-body" role="log" aria-live="polite">
      <p v-if="error" class="notice notice-danger small">{{ error }}</p>
      <template v-if="parent">
        <ChatMessageItem
          :message="parent"
          first
          in-thread
          :members="members"
          :can-write="canWrite"
          @react="(e) => emit('action', 'react', parent!, e)"
          @vote="(ids) => emit('action', 'vote', parent!, ids)"
          @close-poll="emit('action', 'closePoll', parent!)"
          @edit="emit('action', 'edit', parent!)"
          @remove="emit('action', 'remove', parent!)"
        />
        <p class="count muted small">{{ t('chat.replies', { n: replies.length }) }}</p>
        <ChatMessageItem
          v-for="(r, i) in replies"
          :key="r.id"
          :message="r"
          :first="i === 0 || replies[i - 1].author?.id !== r.author?.id"
          in-thread
          :members="members"
          :can-write="canWrite"
          @react="(e) => emit('action', 'react', r, e)"
          @edit="emit('action', 'edit', r)"
          @remove="emit('action', 'remove', r)"
        />
      </template>
    </div>
    <ChatComposer
      v-if="canWrite && parent && !parent.deleted"
      ref="composer"
      :channel-id="channelId"
      :parent-id="parentId"
      :members="members"
      :space-id="spaceId"
      input-id="thread-input"
      :placeholder="t('chat.replyPlaceholder')"
      @sent="sent"
    />
  </aside>
</template>

<style scoped>
.thread {
  display: grid;
  grid-template-rows: auto 1fr auto;
  min-height: 0;
  height: 100%;
  padding-bottom: var(--space-3);
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
  overscroll-behavior: contain;
}

.count {
  margin: var(--space-3) var(--space-5) 0;
  padding-bottom: var(--space-2);
  border-bottom: 1px solid var(--color-border);
}
</style>
