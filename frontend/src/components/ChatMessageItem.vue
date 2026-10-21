<script setup lang="ts">
/**
 * One chat message, like in Discord: formatted text with @mentions, a shared file, a call, a poll or a voice
 * message; reactions below; and on hover: react, reply in a thread, pin, edit, delete.
 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from './AppIcon.vue'
import UserAvatar from './UserAvatar.vue'
import { locale, t } from '@/lib/i18n'
import { renderChat } from '@/lib/markdown'
import { fileIcon, fileSize, fileTone, isOffice } from '@/lib/spaces'
import type { ChatMessage, UserBrief } from '@/lib/types'

const props = defineProps<{ message: ChatMessage; first: boolean; members: UserBrief[]; inThread?: boolean; canWrite?: boolean }>()
const emit = defineEmits<{
  react: [emoji: string]
  reply: []
  pin: []
  edit: []
  remove: []
  vote: [optionIds: number[]]
  closePoll: []
}>()

const QUICK = ['👍', '❤️', '😂', '🎉', '👀', '🙏']
const MORE = ['✅', '🔥', '😮', '😢', '👏', '💯', '🤔', '🚀', '☕', '👋', '😅', '❌']

const router = useRouter()
const picker = ref(false)
const m = computed(() => props.message)
const html = computed(() => renderChat(m.value.body, props.members.map((x) => x.full_name)))

function time(iso: string) {
  return new Date(iso).toLocaleTimeString(locale.value, { hour: '2-digit', minute: '2-digit' })
}

function pick(emoji: string) {
  picker.value = false
  emit('react', emoji)
}

function choose(optionId: number) {
  const poll = m.value.poll
  if (!poll || poll.closed) return
  const mine = poll.options.filter((o) => o.mine).map((o) => o.id)
  if (poll.multi) emit('vote', mine.includes(optionId) ? mine.filter((id) => id !== optionId) : [...mine, optionId])
  else emit('vote', mine.includes(optionId) ? [] : [optionId])
}

function percent(votes: number) {
  const total = m.value.poll?.options.reduce((sum, o) => sum + o.votes, 0) ?? 0
  return total ? Math.round((votes / total) * 100) : 0
}

const duration = computed(() => {
  const s = m.value.audio_seconds ?? 0
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
})
</script>

<template>
  <article class="msg" :class="{ first, mine: m.mine, pinned: m.pinned }">
    <div class="avatar-col">
      <UserAvatar v-if="first && m.author" :id="m.author.id" :name="m.author.full_name" :photo-version="m.author.photo_version" :size="34" />
    </div>
    <div class="msg-body">
      <p v-if="first" class="meta">
        <strong>{{ m.author?.full_name ?? t('chat.formerColleague') }}</strong>
        <time :datetime="m.created_at" class="muted small">{{ time(m.created_at) }}</time>
        <span v-if="m.pinned" class="pin-tag"><AppIcon name="pin" :size="12" />{{ t('chat.pinned') }}</span>
      </p>
      <p v-if="m.deleted" class="muted deleted">{{ t('chat.deleted') }}</p>
      <template v-else>
        <div v-if="m.meeting" class="call-card" :class="{ over: !m.meeting.active }">
          <span class="call-icon"><AppIcon :name="m.meeting.active ? 'video' : 'phoneOff'" :size="18" /></span>
          <span class="call-text">{{ m.meeting.active ? t('chat.callActive') : t('chat.callEnded') }}</span>
          <RouterLink v-if="m.meeting.active" :to="{ path: `/meetings/${m.meeting.id}/room`, query: { from: router.currentRoute.value.fullPath } }" class="btn btn-primary">{{ t('chat.joinCall') }}</RouterLink>
        </div>

        <!-- Poll -->
        <div v-if="m.kind === 'poll' && m.poll" class="poll" role="group" :aria-label="m.body">
          <p class="poll-q"><AppIcon name="chart" :size="16" />{{ m.body }}</p>
          <button
            v-for="o in m.poll.options"
            :key="o.id"
            type="button"
            class="option"
            :class="{ mine: o.mine }"
            :aria-pressed="o.mine"
            :disabled="m.poll.closed"
            :title="o.voters.join(', ')"
            @click="choose(o.id)"
          >
            <span class="bar" :style="{ width: `${percent(o.votes)}%` }" aria-hidden="true" />
            <span class="otext"><AppIcon v-if="o.mine" name="check" :size="14" />{{ o.text }}</span>
            <span class="ocount">{{ o.votes }} · {{ percent(o.votes) }} %</span>
          </button>
          <p class="muted small">
            {{ t('chat.pollVoters', { n: m.poll.total }) }}<template v-if="m.poll.multi"> · {{ t('chat.pollMulti') }}</template><template v-if="m.poll.closed"> · {{ t('chat.pollClosed') }}</template>
            <button v-if="m.mine && !m.poll.closed" type="button" class="link-btn" @click="emit('closePoll')">{{ t('chat.pollClose') }}</button>
          </p>
        </div>

        <!-- Voice message -->
        <div v-else-if="m.kind === 'voice'" class="voice">
          <AppIcon name="mic" :size="16" />
          <audio controls preload="none" :src="`/api/chat/messages/${m.id}/audio`" :aria-label="t('chat.voiceMessage', { time: duration })" />
          <span class="muted small">{{ duration }}</span>
        </div>

        <!-- eslint-disable-next-line vue/no-v-html -- renderChat escapes HTML first -->
        <div v-else-if="m.body" class="text" v-html="html" />
        <span v-if="m.edited" class="muted small"> ({{ t('chat.edited') }})</span>

        <div v-if="m.file" class="file">
          <span class="ficon" :class="`pc-${fileTone(m.file.file_type)}`"><AppIcon :name="fileIcon(m.file.file_type)" :size="18" /></span>
          <span class="fname">{{ m.file.name }}<span class="muted small"> · {{ fileSize(m.file.size) }}</span></span>
          <RouterLink v-if="isOffice(m.file.file_type)" :to="`/office/${m.file.id}`" class="btn btn-ghost btn-icon" :aria-label="t('files.edit')"><AppIcon name="edit" :size="18" /></RouterLink>
          <a class="btn btn-ghost btn-icon" :href="`/api/spaces/files/${m.file.id}/download`" download :aria-label="t('files.download')"><AppIcon name="download" :size="18" /></a>
        </div>

        <ul v-if="m.reactions?.length" class="reactions">
          <li v-for="r in m.reactions" :key="r.emoji">
            <button type="button" class="reaction" :class="{ mine: r.mine }" :aria-pressed="r.mine" :title="r.names.join(', ')" :aria-label="t('chat.reactionLabel', { emoji: r.emoji, n: r.count, names: r.names.join(', ') })" @click="emit('react', r.emoji)">
              <span aria-hidden="true">{{ r.emoji }}</span>{{ r.count }}
            </button>
          </li>
        </ul>

        <button v-if="!inThread && m.reply_count" type="button" class="thread-link" @click="emit('reply')">
          <AppIcon name="message" :size="14" />{{ t('chat.replies', { n: m.reply_count }) }}
          <span class="muted small">{{ m.reply_people?.join(', ') }}<template v-if="m.last_reply_at"> · {{ time(m.last_reply_at) }}</template></span>
        </button>
      </template>
      <span v-if="!first" class="hover-time muted small" aria-hidden="true">{{ time(m.created_at) }}</span>
    </div>

    <div v-if="!m.deleted" class="msg-actions" :class="{ open: picker }">
      <button v-for="e in QUICK.slice(0, 3)" :key="e" type="button" class="btn btn-ghost btn-icon emoji" :aria-label="t('chat.react', { emoji: e })" @click="emit('react', e)">{{ e }}</button>
      <div class="picker-wrap">
        <button type="button" class="btn btn-ghost btn-icon" :aria-label="t('chat.moreReactions')" :aria-expanded="picker" @click="picker = !picker"><AppIcon name="plus" :size="16" /></button>
        <div v-if="picker" class="picker" role="menu">
          <button v-for="e in [...QUICK, ...MORE]" :key="e" type="button" role="menuitem" class="emoji-btn" :aria-label="t('chat.react', { emoji: e })" @click="pick(e)">{{ e }}</button>
        </div>
      </div>
      <button v-if="!inThread && canWrite" type="button" class="btn btn-ghost btn-icon" :aria-label="t('chat.replyThread')" :title="t('chat.replyThread')" @click="emit('reply')"><AppIcon name="message" :size="16" /></button>
      <button v-if="!inThread && canWrite" type="button" class="btn btn-ghost btn-icon" :aria-label="m.pinned ? t('chat.unpin') : t('chat.pin')" :title="m.pinned ? t('chat.unpin') : t('chat.pin')" @click="emit('pin')"><AppIcon name="pin" :size="16" /></button>
      <button v-if="m.mine && m.kind !== 'poll' && m.kind !== 'voice' && m.body" type="button" class="btn btn-ghost btn-icon" :aria-label="t('chat.edit')" @click="emit('edit')"><AppIcon name="edit" :size="16" /></button>
      <button v-if="m.mine" type="button" class="btn btn-ghost btn-icon" :aria-label="t('chat.delete')" @click="emit('remove')"><AppIcon name="trash" :size="16" /></button>
    </div>
  </article>
</template>

<style scoped>
.msg {
  position: relative;
  display: grid;
  grid-template-columns: 42px 1fr;
  gap: var(--space-3);
  padding: 2px var(--space-5);
}

.msg.first {
  margin-top: var(--space-3);
}

.msg:hover,
.msg:focus-within {
  background: var(--color-surface-muted);
}

.msg.pinned {
  box-shadow: inset 3px 0 0 var(--color-warning);
}

.meta {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--space-2);
  margin: 0;
}

.pin-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  color: var(--color-warning);
  font-size: 0.75rem;
  font-weight: 600;
}

.msg-body {
  position: relative;
  min-width: 0;
}

.text {
  overflow-wrap: anywhere;
  line-height: 1.5;
}

.text :deep(.mention) {
  padding: 0 3px;
  border-radius: 4px;
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
  font-weight: 600;
}

.text :deep(pre) {
  margin: 4px 0;
  padding: var(--space-2) var(--space-3);
  overflow-x: auto;
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
  font-size: 0.85rem;
}

.text :deep(code) {
  padding: 0 4px;
  border-radius: 4px;
  background: var(--color-surface-muted);
  font-size: 0.88em;
}

.deleted {
  margin: 0;
  font-style: italic;
}

.call-card,
.file,
.poll,
.voice {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  margin-top: 4px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}

.call-icon,
.ficon {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border-radius: 50%;
  background: var(--color-success-soft);
  color: var(--color-success);
}

.ficon {
  border-radius: 8px;
}

.call-card.over .call-icon {
  background: var(--color-neutral-soft);
  color: var(--color-text-muted);
}

.call-text {
  font-weight: 600;
}

.fname {
  min-width: 0;
  overflow-wrap: anywhere;
}

.poll {
  display: grid;
  width: min(440px, 100%);
  gap: 6px;
}

.poll-q {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  font-weight: 700;
}

.poll p {
  margin: 0;
}

.option {
  position: relative;
  display: flex;
  justify-content: space-between;
  gap: var(--space-2);
  overflow: hidden;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.option.mine {
  border-color: var(--color-primary);
}

.option:disabled {
  cursor: default;
}

.bar {
  position: absolute;
  inset: 0 auto 0 0;
  background: var(--color-primary-soft);
  transition: width var(--t-med, 200ms) ease;
}

.otext,
.ocount {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.ocount {
  color: var(--color-text-muted);
  font-size: 0.82rem;
  white-space: nowrap;
}

.link-btn {
  margin-left: var(--space-2);
  padding: 0;
  border: 0;
  background: none;
  color: var(--color-primary);
  font: inherit;
  text-decoration: underline;
  cursor: pointer;
}

.voice audio {
  height: 34px;
  max-width: 260px;
}

.reactions {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin: 4px 0 0;
  padding: 0;
  list-style: none;
}

.reaction {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 8px;
  border: 1px solid var(--color-border);
  border-radius: 99px;
  background: var(--color-surface);
  color: var(--color-text);
  font: inherit;
  font-size: 0.82rem;
  cursor: pointer;
}

.reaction.mine {
  border-color: var(--color-primary);
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
}

.thread-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
  padding: 2px 6px;
  border: 0;
  border-radius: 6px;
  background: none;
  color: var(--color-primary);
  font: inherit;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
}

.thread-link:hover {
  background: var(--color-primary-soft);
}

.hover-time {
  position: absolute;
  top: 2px;
  left: -46px;
  visibility: hidden;
}

.msg:hover .hover-time {
  visibility: visible;
}

.msg-actions {
  position: absolute;
  top: -14px;
  right: var(--space-5);
  display: none;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-raised);
  box-shadow: var(--shadow-sm, 0 1px 3px rgb(0 0 0 / 10%));
}

.msg:hover .msg-actions,
.msg:focus-within .msg-actions,
.msg-actions.open {
  display: flex;
}

.emoji {
  font-size: 1rem;
}

.picker-wrap {
  position: relative;
}

.picker {
  position: absolute;
  z-index: 10;
  top: calc(100% + 4px);
  right: 0;
  display: grid;
  grid-template-columns: repeat(6, 34px);
  gap: 2px;
  padding: 6px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-raised);
  box-shadow: var(--shadow-overlay);
}

.emoji-btn {
  width: 34px;
  height: 34px;
  border: 0;
  border-radius: 6px;
  background: none;
  font-size: 1.1rem;
  cursor: pointer;
}

.emoji-btn:hover,
.emoji-btn:focus-visible {
  background: var(--color-primary-soft);
}

@media (hover: none) {
  .msg-actions {
    position: static;
    display: flex;
    grid-column: 2;
    justify-self: start;
    margin-top: 2px;
    border: 0;
    box-shadow: none;
    background: none;
  }
}
</style>
