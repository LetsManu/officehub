<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import MeetingRoom from '@/components/MeetingRoom.vue'
import { api } from '@/lib/api'
import { errorText, t } from '@/lib/i18n'
import { currentUser } from '@/lib/session'
import type { MeetingDetail } from '@/lib/types'

const props = defineProps<{ id: string }>()
const route = useRoute()
const router = useRouter()
const meeting = ref<MeetingDetail | null>(null)
const error = ref<string | null>(null)
const round = ref(0) // a new key joins again after leaving

const callMode = computed(() => route.query.call === '1')
/** A call is named after the caller; the caller sees who they are talking to. */
const title = computed(() => {
  const m = meeting.value
  if (m?.kind === 'call' && m.is_organizer && m.invitees.length) return m.invitees.map((i) => i.person.full_name).join(', ')
  return m?.title ?? ''
})
const backTo = computed(() => {
  const m = meeting.value
  if (m?.kind === 'space' && m.space_id) return `/spaces/${m.space_id}`
  if (m?.kind === 'call') return typeof route.query.from === 'string' && route.query.from.startsWith('/') ? route.query.from : '/chat'
  return `/meetings/${props.id}`
})

onMounted(async () => {
  try {
    meeting.value = await api.get<MeetingDetail>(`/api/meetings/${props.id}`)
    if (meeting.value.cancelled) error.value = t('errors.meeting_cancelled')
  } catch (e) {
    error.value = errorText(e)
  }
})
</script>

<template>
  <div class="room-page">
    <div v-if="error" class="problem">
      <AppIcon name="alert" :size="32" />
      <p>{{ error }}</p>
      <RouterLink to="/meetings" class="btn btn-secondary">{{ t('meetings.title') }}</RouterLink>
    </div>
    <MeetingRoom
      v-else-if="meeting"
      :key="round"
      :meeting-id="meeting.id"
      :title="title"
      :display-name="currentUser?.full_name ?? ''"
      :call-mode="callMode && round === 0"
      :guest-link="meeting.guest_link"
      :space-id="meeting.space_id"
    >
      <template #ended>
        <div class="ended-actions">
          <button type="button" class="btn btn-primary" @click="round++"><AppIcon name="video" :size="18" />{{ t('meeting.rejoin') }}</button>
          <button type="button" class="btn btn-secondary" @click="router.push(backTo)">{{ t('meeting.back') }}</button>
        </div>
      </template>
    </MeetingRoom>
  </div>
</template>

<style scoped>
.room-page {
  display: grid;
  height: calc(100dvh - var(--header-height, 52px) - var(--bottom-bar, 0px));
  min-height: 420px;
}

.problem {
  display: grid;
  place-content: center;
  justify-items: center;
  gap: var(--space-3);
  padding: var(--space-6);
  text-align: center;
}

.ended-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--space-3);
}
</style>
