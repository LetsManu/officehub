<script setup lang="ts">
/** The calendar like in Outlook: my own calendar (meetings, bookings, time off) and the team calendar. */
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import MeetingForm from '@/components/MeetingForm.vue'
import MyCalendar from '@/components/MyCalendar.vue'
import PageHeader from '@/components/PageHeader.vue'
import TeamCalendar from '@/components/TeamCalendar.vue'
import { api } from '@/lib/api'
import { errorText, t } from '@/lib/i18n'
import { showToast } from '@/lib/toast'
import type { MeetingDetail } from '@/lib/types'

const route = useRoute()
const router = useRouter()
const tab = ref<'mine' | 'team'>(route.query.view === 'team' ? 'team' : 'mine')
const formOpen = ref(false)
const slot = ref<{ start: Date | null; end: Date | null }>({ start: null, end: null })
const mine = ref<InstanceType<typeof MyCalendar> | null>(null)
const starting = ref(false)

function plan(start: Date | null = null, end: Date | null = null) {
  slot.value = { start, end }
  formOpen.value = true
}

function saved(m: MeetingDetail) {
  formOpen.value = false
  showToast(t('meetings.created'))
  mine.value?.reload()
  void m
}

async function startNow() {
  starting.value = true
  try {
    const start = new Date()
    const m = await api.post<MeetingDetail>('/api/meetings', { title: t('meetings.instantTitle'), starts_at: start.toISOString(), ends_at: new Date(start.getTime() + 3600_000).toISOString(), allow_guests: true })
    router.push(`/meetings/${m.id}/room`)
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    starting.value = false
  }
}

watch(tab, (v) => router.replace({ query: v === 'team' ? { view: 'team' } : {} }))
</script>

<template>
  <div class="page">
    <PageHeader :title="t('calendarPage.title')" :subtitle="t('calendarPage.subtitle')">
      <template #actions>
        <RouterLink to="/meetings" class="btn btn-ghost"><AppIcon name="video" :size="18" />{{ t('calendarPage.meetingList') }}</RouterLink>
        <button type="button" class="btn btn-secondary" :disabled="starting" @click="startNow"><AppIcon name="video" />{{ t('meetings.startNow') }}</button>
        <button type="button" class="btn btn-primary" @click="plan()"><AppIcon name="plus" />{{ t('meetings.new') }}</button>
      </template>
    </PageHeader>

    <div class="segmented tabs" role="group" :aria-label="t('calendarPage.title')">
      <button type="button" :aria-pressed="tab === 'mine'" @click="tab = 'mine'"><AppIcon name="calendar" :size="16" />{{ t('calendarPage.mine') }}</button>
      <button type="button" :aria-pressed="tab === 'team'" @click="tab = 'team'"><AppIcon name="users" :size="16" />{{ t('calendarPage.team') }}</button>
    </div>

    <MyCalendar v-if="tab === 'mine'" ref="mine" @plan="plan" />
    <TeamCalendar v-else />

    <MeetingForm :open="formOpen" :start="slot.start" :end="slot.end" @close="formOpen = false" @saved="saved" />
  </div>
</template>

<style scoped>
.tabs {
  margin-bottom: var(--space-4);
}

.tabs button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
</style>
