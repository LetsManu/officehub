<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import LoadState from '@/components/LoadState.vue'
import MeetingForm from '@/components/MeetingForm.vue'
import PageHeader from '@/components/PageHeader.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import { api } from '@/lib/api'
import { errorText, formatDateLong, locale, t } from '@/lib/i18n'
import { renderMarkdown } from '@/lib/markdown'
import { showToast } from '@/lib/toast'
import type { MeetingDetail } from '@/lib/types'

const props = defineProps<{ id: string }>()
const router = useRouter()
const route = useRoute()
const cancelScope = ref<'one' | 'all'>('one')
const meeting = ref<MeetingDetail | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const editOpen = ref(false)
const cancelOpen = ref(false)
const busy = ref(false)
let timer: number | undefined

function localIso(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** For a series: the meeting opened from the calendar (?occurrence=day), otherwise the next one. */
const shown = computed(() => {
  const m = meeting.value
  if (!m?.starts_at || !m.ends_at) return null
  if (!m.recurrence) return { start: new Date(m.starts_at), end: new Date(m.ends_at) }
  const length = new Date(m.ends_at).getTime() - new Date(m.starts_at).getTime()
  const asked = typeof route.query.occurrence === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(route.query.occurrence) ? route.query.occurrence : null
  if (asked) {
    const first = new Date(m.starts_at)
    const start = new Date(`${asked}T00:00`)
    start.setHours(first.getHours(), first.getMinutes())
    return { start, end: new Date(start.getTime() + length) }
  }
  return m.next_start && m.next_end ? { start: new Date(m.next_start), end: new Date(m.next_end) } : { start: new Date(m.starts_at), end: new Date(m.ends_at) }
})

const when = computed(() => {
  const s = shown.value
  if (!s) return ''
  const clock = (d: Date) => d.toLocaleTimeString(locale.value, { hour: '2-digit', minute: '2-digit' })
  return `${formatDateLong(s.start.toISOString())}, ${clock(s.start)} – ${clock(s.end)}`
})
const seriesText = computed(() => {
  const m = meeting.value
  if (!m?.recurrence) return ''
  const rule = t(`meetings.repeat.${m.recurrence}`)
  return m.recurrence_until ? t('meetings.seriesUntil', { rule, date: formatDateLong(m.recurrence_until) }) : rule
})
const isPast = computed(() => {
  const m = meeting.value
  if (!m?.ends_at) return false
  if (m.recurrence) return !m.next_start
  return new Date(m.ends_at).getTime() < Date.now()
})

async function load() {
  error.value = null
  try {
    meeting.value = await api.get<MeetingDetail>(`/api/meetings/${props.id}`)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

async function respond(response: 'accepted' | 'declined') {
  try {
    meeting.value = await api.post<MeetingDetail>(`/api/meetings/${props.id}/respond`, { response })
    showToast(response === 'accepted' ? t('meetings.acceptedToast') : t('meetings.declinedToast'))
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

async function cancelMeeting() {
  busy.value = true
  try {
    const one = meeting.value?.recurrence && cancelScope.value === 'one' && shown.value
    await api.delete(`/api/meetings/${props.id}${one ? `?occurrence=${localIso(shown.value!.start)}` : ''}`)
    cancelOpen.value = false
    if (one) router.replace({ query: {} })
    showToast(t('meetings.cancelledToast'))
    await load()
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    busy.value = false
  }
}

async function copyLink() {
  if (!meeting.value?.guest_link) return
  const url = `${window.location.origin}${meeting.value.guest_link}`
  try {
    await navigator.clipboard.writeText(url)
    showToast(t('meeting.linkCopied'))
  } catch {
    window.prompt(t('meeting.guestLink'), url)
  }
}

async function notesToWiki() {
  const m = meeting.value
  if (!m?.space_id) return
  try {
    const page = await api.post<{ space_id: number; page_id: number }>(`/api/meetings/${m.id}/notes-to-wiki?space_id=${m.space_id}`)
    showToast(t('meetings.notesToWikiDone'))
    router.push(`/spaces/${page.space_id}/wiki/${page.page_id}`)
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

function saved(m: MeetingDetail) {
  meeting.value = m
  editOpen.value = false
  showToast(t('meetings.saved'))
}

onMounted(() => {
  load()
  // Who is in the meeting right now
  timer = window.setInterval(() => document.visibilityState === 'visible' && load(), 15_000)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <div class="page">
    <LoadState :loading="loading" :error="error" @retry="load">
      <template v-if="meeting">
        <PageHeader :title="meeting.title" :subtitle="when" back-to="/meetings" :back-label="t('meetings.title')">
          <template #actions>
            <template v-if="meeting.is_organizer && !meeting.cancelled && meeting.kind === 'scheduled'">
              <button type="button" class="btn btn-ghost" @click="editOpen = true"><AppIcon name="edit" :size="18" />{{ t('meetings.edit') }}</button>
              <button v-if="!isPast" type="button" class="btn btn-ghost danger-text" @click="cancelOpen = true"><AppIcon name="close" :size="18" />{{ t('meetings.cancel') }}</button>
            </template>
            <RouterLink v-if="!meeting.cancelled" :to="`/meetings/${meeting.id}/room`" class="btn btn-primary"><AppIcon name="video" />{{ meeting.live.length ? t('meetings.joinLive', { n: meeting.live.length }) : t('meetings.join') }}</RouterLink>
          </template>
        </PageHeader>
        <p v-if="seriesText" class="series-note"><AppIcon name="history" :size="16" />{{ t('meetings.repeats', { rule: seriesText }) }}</p>
        <p v-if="meeting.town_hall" class="series-note"><AppIcon name="megaphone" :size="16" />{{ t('meetings.townHallNote') }}</p>
        <p v-if="meeting.e2ee" class="series-note"><AppIcon name="lock" :size="16" />{{ t('meetings.e2eeNote') }}</p>

        <p v-if="meeting.cancelled" class="notice notice-danger">{{ t('meetings.cancelledNotice') }}</p>

        <div class="layout">
          <div class="stack">
            <section v-if="meeting.my_response && !meeting.cancelled && !isPast" class="card answer">
              <p>{{ meeting.my_response === 'pending' ? t('meetings.question') : meeting.my_response === 'accepted' ? t('meetings.youAccepted') : t('meetings.youDeclined') }}</p>
              <div class="row">
                <button type="button" class="btn" :class="meeting.my_response === 'accepted' ? 'btn-primary' : 'btn-secondary'" :aria-pressed="meeting.my_response === 'accepted'" @click="respond('accepted')"><AppIcon name="check" :size="18" />{{ t('meetings.accept') }}</button>
                <button type="button" class="btn" :class="meeting.my_response === 'declined' ? 'btn-primary' : 'btn-secondary'" :aria-pressed="meeting.my_response === 'declined'" @click="respond('declined')">{{ t('meetings.decline') }}</button>
              </div>
            </section>

            <section v-if="meeting.description" class="card">
              <h2 class="h3">{{ t('meetings.fields.agenda') }}</h2>
              <!-- eslint-disable-next-line vue/no-v-html -- renderMarkdown escapes HTML first -->
              <div class="markdown" v-html="renderMarkdown(meeting.description)" />
            </section>

            <section class="card">
              <div class="head-row">
                <h2 class="h3">{{ t('meeting.panels.notes') }}</h2>
                <button v-if="meeting.space_id && meeting.notes.trim()" type="button" class="btn btn-ghost" @click="notesToWiki"><AppIcon name="book" :size="18" />{{ t('meetings.notesToWiki') }}</button>
              </div>
              <!-- eslint-disable-next-line vue/no-v-html -- renderMarkdown escapes HTML first -->
              <div v-if="meeting.notes.trim()" class="markdown" v-html="renderMarkdown(meeting.notes)" />
              <p v-else class="muted">{{ t('meetings.noNotes') }}</p>
            </section>
          </div>

          <aside class="stack">
            <section class="card card-flush">
              <h2 class="h3 side-head">{{ t('meetings.people', { n: meeting.invitees.length + 1 }) }}</h2>
              <ul class="list">
                <li v-if="meeting.organizer" class="person">
                  <UserAvatar :id="meeting.organizer.id" :name="meeting.organizer.full_name" :photo-version="meeting.organizer.photo_version" :size="32" />
                  <span class="who"><strong>{{ meeting.organizer.full_name }}</strong><span class="muted small">{{ t('meetings.organizer') }}</span></span>
                  <span v-if="meeting.live.some((p) => p.id === meeting!.organizer!.id)" class="live-dot" :title="t('meetings.inMeeting')" />
                </li>
                <li v-for="p in meeting.invitees" :key="p.person.id" class="person">
                  <UserAvatar :id="p.person.id" :name="p.person.full_name" :photo-version="p.person.photo_version" :size="32" status />
                  <span class="who"><strong>{{ p.person.full_name }}</strong><span class="muted small">{{ p.person.department }}</span></span>
                  <span v-if="meeting.live.some((l) => l.id === p.person.id)" class="live-dot" :title="t('meetings.inMeeting')" />
                  <span class="answer-tag" :class="p.response">{{ t(`meetings.responses.${p.response}`) }}</span>
                </li>
                <li v-for="g in meeting.live.filter((l) => l.guest)" :key="`g-${g.name}`" class="person">
                  <span class="guest-avatar" aria-hidden="true"><AppIcon name="user" :size="16" /></span>
                  <span class="who"><strong>{{ g.name }}</strong><span class="muted small">{{ t('meetings.guest') }}</span></span>
                  <span class="live-dot" :title="t('meetings.inMeeting')" />
                </li>
              </ul>
            </section>

            <section class="card stack small-gap">
              <a :href="`/api/meetings/${meeting.id}/ics`" class="btn btn-secondary" download><AppIcon name="calendar" :size="18" />{{ t('meetings.addToCalendar') }}</a>
              <button v-if="meeting.guest_link" type="button" class="btn btn-secondary" @click="copyLink"><AppIcon name="link" :size="18" />{{ t('meeting.copyGuestLink') }}</button>
              <p v-if="meeting.guest_link" class="muted small">{{ t('meetings.guestLinkHint') }}</p>
              <RouterLink v-if="meeting.space_id" :to="`/spaces/${meeting.space_id}`" class="btn btn-ghost"><AppIcon name="spaces" :size="18" />{{ meeting.space_name }}</RouterLink>
            </section>
          </aside>
        </div>

        <MeetingForm :open="editOpen" :meeting="meeting" @close="editOpen = false" @saved="saved" />
        <BaseModal :open="cancelOpen" :title="t('meetings.cancelTitle', { title: meeting.title })" :description="t('meetings.cancelText')" :confirm-label="t('meetings.cancel')" tone="danger" :busy="busy" @close="cancelOpen = false" @confirm="cancelMeeting">
          <fieldset v-if="meeting.recurrence && shown" class="scope">
            <legend class="visually-hidden">{{ t('meetings.cancelWhich') }}</legend>
            <label class="radio"><input v-model="cancelScope" type="radio" value="one" /> {{ t('meetings.cancelOne', { date: formatDateLong(shown.start.toISOString()) }) }}</label>
            <label class="radio"><input v-model="cancelScope" type="radio" value="all" /> {{ t('meetings.cancelSeries') }}</label>
          </fieldset>
        </BaseModal>
      </template>
    </LoadState>
  </div>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: var(--space-4);
  align-items: start;
}

@media (max-width: 900px) {
  .layout {
    grid-template-columns: 1fr;
  }
}

.answer {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.answer p {
  margin: 0;
  font-weight: 600;
}

.row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
}

.side-head {
  padding: var(--space-4) var(--space-5) var(--space-2);
}

.person {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-5);
}

.who {
  display: grid;
  flex: 1;
  min-width: 0;
}

.live-dot {
  width: 10px;
  height: 10px;
  flex: none;
  border-radius: 50%;
  background: var(--color-success);
}

.guest-avatar {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  border-radius: 50%;
  background: var(--color-neutral-soft);
}

.series-note {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: calc(-1 * var(--space-3)) 0 var(--space-4);
  color: var(--color-text-muted);
}

.scope {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  border: 0;
}

.answer-tag {
  padding: 2px 10px;
  border-radius: 99px;
  background: var(--color-neutral-soft);
  font-size: var(--text-xs);
  font-weight: 600;
  white-space: nowrap;
}

.answer-tag.accepted {
  background: var(--color-success-soft);
  color: var(--color-success);
}

.answer-tag.declined {
  background: var(--color-danger-soft);
  color: var(--color-danger);
}

.small-gap {
  gap: var(--space-2);
}

.danger-text {
  color: var(--color-danger);
}
</style>
