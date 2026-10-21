<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import ChatPane from '@/components/ChatPane.vue'
import FormField from '@/components/FormField.vue'
import { api } from '@/lib/api'
import { errorText, t } from '@/lib/i18n'
import { useSpace } from '@/lib/spaceContext'
import type { Conversation } from '@/lib/types'

const { space, reload } = useSpace()
const channels = ref<Conversation[]>([])
const selected = ref<number | null>(null)
const newOpen = ref(false)
const newName = ref('')
const newError = ref('')

async function load() {
  const all = await api.get<Conversation[]>('/api/chat')
  channels.value = all.filter((c) => c.space_id === space.value?.id).sort((a, b) => a.id - b.id)
  if (!selected.value && channels.value.length) selected.value = channels.value[0].id
}

async function create() {
  newError.value = newName.value.trim() ? '' : t('validation.name_required')
  if (newError.value) return
  try {
    const channel = await api.post<Conversation>('/api/chat/channels', { space_id: space.value!.id, name: newName.value.trim() })
    newOpen.value = false
    await load()
    selected.value = channel.id
  } catch (e) {
    newError.value = errorText(e)
  }
}

onMounted(load)
</script>

<template>
  <div class="space-chat">
    <aside class="channels card card-flush" :aria-label="t('chat.channels')">
      <ul>
        <li v-for="c in channels" :key="c.id">
          <button type="button" class="channel" :class="{ active: c.id === selected }" :aria-current="c.id === selected ? 'true' : undefined" @click="selected = c.id; reload()">
            <span class="hash" aria-hidden="true">#</span>
            <span class="cname">{{ c.name }}</span>
            <span v-if="c.unread && c.id !== selected" class="badge">{{ c.unread }}</span>
          </button>
        </li>
      </ul>
      <button v-if="!space?.archived" type="button" class="btn btn-ghost add" @click="newOpen = true; newName = ''; newError = ''"><AppIcon name="plus" :size="18" />{{ t('chat.newChannel') }}</button>
    </aside>
    <div class="card card-flush pane-wrap">
      <ChatPane v-if="selected" :key="selected" :channel-id="selected" />
      <p v-else class="muted pad">{{ t('chat.notMember') }}</p>
    </div>

    <BaseModal :open="newOpen" :title="t('chat.newChannel')" :description="t('chat.newChannelHint')" :confirm-label="t('files.create')" @close="newOpen = false" @confirm="create">
      <form novalidate @submit.prevent="create">
        <FormField id="ch-name" :label="t('files.name')" :error="newError">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="newName" class="input" maxlength="60" /></template>
        </FormField>
      </form>
    </BaseModal>
  </div>
</template>

<style scoped>
.space-chat {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: var(--space-4);
  height: calc(100dvh - 330px);
  min-height: 460px;
}

.channels {
  display: flex;
  flex-direction: column;
  padding: var(--space-2);
}

.channels ul {
  display: grid;
  gap: 2px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.channel {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  min-height: 40px;
  padding: 0 var(--space-3);
  border: 0;
  border-radius: var(--radius-md);
  background: none;
  color: var(--color-text-muted);
  font: inherit;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
}

.channel:hover {
  background: var(--color-surface-muted);
}

.channel.active {
  background: var(--color-primary-soft);
  color: var(--color-text);
}

.hash {
  color: var(--color-text-subtle);
}

.cname {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
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

.add {
  justify-content: flex-start;
  margin-top: var(--space-2);
}

.pane-wrap {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.pane-wrap > :deep(.pane) {
  flex: 1;
}

.pad {
  padding: var(--space-6);
}

@media (max-width: 720px) {
  .space-chat {
    grid-template-columns: 1fr;
    grid-template-rows: auto 1fr;
    height: calc(100dvh - 280px);
  }

  .channels ul {
    display: flex;
    overflow-x: auto;
  }

  .add {
    display: none;
  }
}
</style>
