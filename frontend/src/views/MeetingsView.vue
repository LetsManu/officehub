<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadState from '@/components/LoadState.vue'
import MeetingForm from '@/components/MeetingForm.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api, query } from '@/lib/api'
import { errorText, formatDateLong, locale, t } from '@/lib/i18n'
import { showToast } from '@/lib/toast'
import type { Meeting, MeetingDetail } from '@/lib/types'

const route = useRoute()
const router = useRouter()
const meetings = ref<Meeting[]>([])
const past = ref(false)
const loading = ref(true)
const error = ref<string | null>(null)
const formOpen = ref(route.query.new === '1') // "/meeting" in the chat opens the form right away
const starting = ref(false)

async function load() {
  loading.value = meetings.value.length === 0
  error.value = null
  try {
    meetings.value = await api.get<Meeting[]>(`/api/meetings${query({ past: past.value ? 'true' : '' })}`)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

/** Meetings grouped by day, so the list reads like a calendar. */
const days = computed(() => {
  const out: { day: string; items: Meeting[] }[] = []
  for (const m of meetings.value) {
    const day = new Date(m.next_start ?? m.starts_at ?? '').toDateString()
    const group = out.at(-1)
    if (group && group.day === day) group.items.push(m)
    else out.push({ day, items: [m] })
  }
  return out
})

function clock(iso: string | null) {
  return iso ? new Date(iso).toLocaleTimeString(locale.value, { hour: '2-digit', minute: '2-digit' }) : ''
}

function isNow(m: Meeting) {
  const now = Date.now()
  const start = m.next_start ?? m.starts_at
  const end = m.next_end ?? m.ends_at
  return !m.cancelled && !!start && !!end && new Date(start).getTime() - 10 * 60_000 <= now && new Date(end).getTime() >= now
}

async function respond(m: Meeting, response: 'accepted' | 'declined') {
  try {
    const d = await api.post<MeetingDetail>(`/api/meetings/${m.id}/respond`, { response })
    Object.assign(m, d)
    showToast(response === 'accepted' ? t('meetings.acceptedToast') : t('meetings.declinedToast'))
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

/** A meeting that starts right now, for when something has to be talked through quickly. */
async function startNow() {
  starting.value = true
  try {
    const start = new Date()
    const end = new Date(start.getTime() + 60 * 60_000)
    const m = await api.post<MeetingDetail>('/api/meetings', { title: t('meetings.instantTitle'), starts_at: start.toISOString(), ends_at: end.toISOString(), allow_guests: true })
    router.push(`/meetings/${m.id}/room`)
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    starting.value = false
  }
}

function created(m: MeetingDetail) {
  formOpen.value = false
  showToast(t('meetings.created'))
  router.push(`/meetings/${m.id}`)
}

watch(past, load)
onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader :title="t('meetings.title')" :subtitle="t('meetings.subtitle')">
      <template #actions>
        <button type="button" class="btn btn-secondary" :disabled="starting" @click="startNow"><AppIcon name="video" />{{ t('meetings.startNow') }}</button>
        <button type="button" class="btn btn-primary" @click="formOpen = true"><AppIcon name="plus" />{{ t('meetings.new') }}</button>
      </template>
    </PageHeader>

    <div class="segmented switch" role="group" :aria-label="t('meetings.title')">
      <button type="button" :aria-pressed="!past" @click="past = false">{{ t('meetings.upcoming') }}</button>
      <button type="button" :aria-pressed="past" @click="past = true">{{ t('meetings.past') }}</button>
    </div>

    <LoadState :loading="loading" :error="error" @retry="load">
      <div v-if="days.length" class="days">
        <section v-for="d in days" :key="d.day" class="card card-flush">
          <h2 class="h3 day">{{ formatDateLong(d.items[0].next_start ?? d.items[0].starts_at) }}</h2>
          <ul class="list">
            <li v-for="m in d.items" :key="m.id" class="row" :class="{ cancelled: m.cancelled }">
              <span class="when">
                <strong>{{ clock(m.next_start ?? m.starts_at) }}</strong>
                <span class="muted small">{{ clock(m.next_end ?? m.ends_at) }}</span>
              </span>
              <RouterLink :to="`/meetings/${m.id}`" class="what">
                <span class="name">{{ m.title }}<AppIcon v-if="m.recurrence" name="history" :size="14" class="series" :label="t(`meetings.repeat.${m.recurrence}`)" /></span>
                <span class="muted small">
                  <template v-if="m.cancelled">{{ t('meetings.cancelled') }}</template>
                  <template v-else>
                    {{ m.organizer?.full_name }}<template v-if="m.space_name"> · {{ m.space_name }}</template> · {{ t('meetings.people', { n: m.invitees.length + 1 }) }}
                  </template>
                </span>
              </RouterLink>
              <span v-if="m.live.length" class="live"><span class="pulse" aria-hidden="true" />{{ t('meetings.liveNow', { n: m.live.length }) }}</span>
              <span class="actions">
                <template v-if="!past && !m.cancelled && m.my_response === 'pending'">
                  <button type="button" class="btn btn-ghost" @click="respond(m, 'accepted')"><AppIcon name="check" :size="18" />{{ t('meetings.accept') }}</button>
                  <button type="button" class="btn btn-ghost" @click="respond(m, 'declined')">{{ t('meetings.decline') }}</button>
                </template>
                <span v-else-if="m.my_response === 'declined'" class="muted small">{{ t('meetings.youDeclined') }}</span>
                <RouterLink v-if="isNow(m)" :to="`/meetings/${m.id}/room`" class="btn btn-primary"><AppIcon name="video" :size="18" />{{ t('meetings.join') }}</RouterLink>
              </span>
            </li>
          </ul>
        </section>
      </div>
      <section v-else class="card">
        <EmptyState icon="video" :message="past ? t('meetings.emptyPast') : t('meetings.empty')" :action-label="past ? undefined : t('meetings.new')" @action="formOpen = true" />
      </section>
    </LoadState>

    <MeetingForm :open="formOpen" @close="formOpen = false" @saved="created" />
  </div>
</template>

<style scoped>
.switch {
  margin-bottom: var(--space-4);
}

.days {
  display: grid;
  gap: var(--space-4);
}

.day {
  padding: var(--space-4) var(--space-5) var(--space-2);
}

.row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3) var(--space-4);
  padding: var(--space-3) var(--space-5);
}

.row.cancelled .series {
  margin-left: 6px;
  color: var(--color-text-muted);
  vertical-align: -2px;
}

.name {
  text-decoration: line-through;
}

.when {
  display: grid;
  width: 56px;
  font-variant-numeric: tabular-nums;
}

.what {
  display: grid;
  flex: 1;
  min-width: 180px;
  color: inherit;
  text-decoration: none;
}

.what:hover .name {
  color: var(--color-primary);
  text-decoration: underline;
}

.name {
  font-weight: 600;
}

.live {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-success);
  font-size: 0.85rem;
  font-weight: 600;
}

.pulse {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--color-success);
  animation: pulse 1.6s ease-out infinite;
}

@keyframes pulse {
  0% {
    box-shadow: 0 0 0 0 color-mix(in srgb, var(--color-success) 60%, transparent);
  }

  100% {
    box-shadow: 0 0 0 8px transparent;
  }
}

@media (prefers-reduced-motion: reduce) {
  .pulse {
    animation: none;
  }
}

.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}
</style>
