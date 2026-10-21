<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import ChatPane from '@/components/ChatPane.vue'
import EmptyState from '@/components/EmptyState.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import { api } from '@/lib/api'
import { errorText, formatDateTime, t } from '@/lib/i18n'
import { currentUser } from '@/lib/session'
import { showToast } from '@/lib/toast'
import type { Conversation, DirectoryEntry } from '@/lib/types'

const props = defineProps<{ id?: string }>()
const router = useRouter()
const conversations = ref<Conversation[]>([])
const filter = ref('')
const loading = ref(true)
const selected = computed(() => (props.id ? Number(props.id) : null))
const people = ref<DirectoryEntry[]>([])
const pickerOpen = ref(false)
const pickerQuery = ref('')
let timer: number | undefined

const shown = computed(() => {
  const q = filter.value.trim().toLowerCase()
  return q ? conversations.value.filter((c) => `${c.name} ${c.space_name ?? ''}`.toLowerCase().includes(q)) : conversations.value
})
const pickable = computed(() => {
  const q = pickerQuery.value.trim().toLowerCase()
  return people.value.filter((p) => p.id !== currentUser.value?.id && (!q || `${p.full_name} ${p.department}`.toLowerCase().includes(q)))
})

async function load() {
  try {
    conversations.value = await api.get<Conversation[]>('/api/chat')
    if (!selected.value && conversations.value.length && window.matchMedia('(min-width: 900px)').matches) {
      router.replace(`/chat/${conversations.value[0].id}`)
    }
  } finally {
    loading.value = false
  }
}

async function openPicker() {
  pickerOpen.value = true
  pickerQuery.value = ''
  if (!people.value.length) people.value = await api.get<DirectoryEntry[]>('/api/directory')
}

async function startDirect(person: DirectoryEntry) {
  try {
    const conversation = await api.post<Conversation>('/api/chat/direct', { user_id: person.id })
    pickerOpen.value = false
    await load()
    router.push(`/chat/${conversation.id}`)
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

watch(selected, () => setTimeout(load, 500))
onMounted(() => {
  load()
  timer = window.setInterval(() => document.visibilityState === 'visible' && load(), 15000)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <div class="page chat-page">
    <div class="layout" :class="{ open: selected }">
      <aside class="list card card-flush" :aria-label="t('chat.conversations')">
        <div class="list-head">
          <h1 class="h3">{{ t('chat.title') }}</h1>
          <button type="button" class="btn btn-primary btn-icon" :aria-label="t('chat.newDirect')" :title="t('chat.newDirect')" @click="openPicker"><AppIcon name="plus" /></button>
        </div>
        <div class="search">
          <label for="chat-filter" class="visually-hidden">{{ t('chat.search') }}</label>
          <input id="chat-filter" v-model="filter" type="search" class="input" :placeholder="t('chat.search')" autocomplete="off" />
        </div>
        <ul v-if="shown.length" class="convs">
          <li v-for="c in shown" :key="c.id">
            <RouterLink :to="`/chat/${c.id}`" class="conv" :class="{ active: c.id === selected, unread: c.unread }" :aria-current="c.id === selected ? 'page' : undefined">
              <UserAvatar v-if="c.other" :id="c.other.id" :name="c.other.full_name" :photo-version="c.other.photo_version" :size="36" />
              <span v-else class="hash" aria-hidden="true">#</span>
              <span class="conv-main">
                <span class="conv-name">{{ c.name }}<span v-if="c.space_name" class="muted small"> · {{ c.space_name }}</span></span>
                <span v-if="c.last" class="muted small preview">{{ c.last.author ? `${c.last.author}: ` : '' }}{{ c.last.call ? t('chat.callPreview') : c.last.body }}</span>
              </span>
              <span class="conv-side">
                <span v-if="c.last" class="muted tiny">{{ formatDateTime(c.last.at) }}</span>
                <span v-if="c.unread" class="badge">{{ c.unread }}</span>
              </span>
            </RouterLink>
          </li>
        </ul>
        <EmptyState v-else-if="!loading" icon="chat" :message="t('chat.empty')" />
      </aside>
      <div class="pane-wrap card card-flush">
        <RouterLink v-if="selected" to="/chat" class="btn btn-ghost back"><AppIcon name="chevronLeft" :size="18" />{{ t('chat.conversations') }}</RouterLink>
        <ChatPane v-if="selected" :key="selected" :channel-id="selected" @updated="load" />
        <EmptyState v-else icon="chat" :message="t('chat.pick')" />
      </div>
    </div>

    <BaseModal :open="pickerOpen" :title="t('chat.newDirect')" hide-actions @close="pickerOpen = false">
      <label for="chat-person" class="visually-hidden">{{ t('chat.searchPerson') }}</label>
      <input id="chat-person" v-model="pickerQuery" class="input" type="search" :placeholder="t('chat.searchPerson')" autocomplete="off" />
      <ul class="picker">
        <li v-for="p in pickable" :key="p.id">
          <button type="button" class="pick" @click="startDirect(p)">
            <UserAvatar :id="p.id" :name="p.full_name" :photo-version="p.photo_version" :size="32" />
            <span><strong>{{ p.full_name }}</strong><span class="muted small block">{{ p.job_title || p.department }}</span></span>
          </button>
        </li>
      </ul>
    </BaseModal>
  </div>
</template>

<style scoped>
.chat-page {
  height: calc(100dvh - var(--header-height, 64px) - var(--space-6) - var(--space-7));
  min-height: 480px;
}

.layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: var(--space-4);
  height: 100%;
  min-height: 0;
}

.list,
.pane-wrap {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4) var(--space-4) var(--space-2);
}

.search {
  padding: 0 var(--space-4) var(--space-3);
}

.convs {
  flex: 1;
  margin: 0;
  padding: 0 var(--space-2) var(--space-2);
  overflow-y: auto;
  list-style: none;
}

.conv {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  color: var(--color-text);
  text-decoration: none;
}

.conv:hover {
  background: var(--color-surface-muted);
}

.conv.active {
  background: var(--color-primary-soft);
}

.hash {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  background: var(--color-neutral-soft);
  color: var(--color-text-muted);
  font-weight: 700;
}

.conv-main {
  display: grid;
  flex: 1;
  min-width: 0;
}

.conv-name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.unread .conv-name {
  font-weight: 700;
}

.preview {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.conv-side {
  display: grid;
  justify-items: end;
  gap: 2px;
}

.tiny {
  font-size: 0.7rem;
  white-space: nowrap;
}

.badge {
  display: grid;
  place-items: center;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 99px;
  background: var(--color-badge);
  color: var(--color-on-badge);
  font-size: 0.72rem;
  font-weight: 700;
}

.pane-wrap > :deep(.pane) {
  flex: 1;
}

.pane-wrap > :deep(.empty) {
  margin: auto;
}

.back {
  display: none;
}

.picker {
  display: grid;
  max-height: 50vh;
  margin: var(--space-3) 0 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}

.pick {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  padding: var(--space-2);
  border: 0;
  border-radius: var(--radius-md);
  background: none;
  color: var(--color-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.pick:hover,
.pick:focus-visible {
  background: var(--color-neutral-soft);
}

.block {
  display: block;
}

@media (max-width: 900px) {
  .chat-page {
    height: calc(100dvh - var(--header-height, 64px) - var(--space-5) - var(--space-7));
  }

  .layout {
    grid-template-columns: 1fr;
  }

  .layout.open .list,
  .layout:not(.open) .pane-wrap {
    display: none;
  }

  .back {
    display: inline-flex;
    align-self: flex-start;
    margin: var(--space-2);
  }
}
</style>
