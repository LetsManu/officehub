<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadState from '@/components/LoadState.vue'
import RequestRow from '@/components/RequestRow.vue'
import SectionContact from '@/components/SectionContact.vue'
import StatTile from '@/components/StatTile.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import { api } from '@/lib/api'
import { portalSettings } from '@/lib/portal'
import { currentUser, isApprover } from '@/lib/session'
import { errorText, formatDate, formatDateLong, formatPeriod, locale, t } from '@/lib/i18n'
import { NOTIFICATION_ICONS, notificationText, timeAgo } from '@/lib/notifications'
import { refreshSummary, summary } from '@/lib/summary'
import { DEFAULT_TILES, tileByKey, type TileDefinition } from '@/lib/tiles'
import { hours } from '@/lib/time'
import type {
  Absence, ActivityItem, Announcement, AppNotification, Booking, Celebration, Checklist, NotificationList, OfficeRequest, RequestList, Review,
  TimeStatus,
  VacationBalance,
} from '@/lib/types'
import { todayIso } from '@/lib/workdays'

interface AttentionItem {
  key: string
  icon: string
  text: string
  action: string
  to: string
  tone: 'info' | 'warning'
}

const openRequests = ref<OfficeRequest[]>([])
const openTotal = ref(0)
const announcements = ref<Announcement[]>([])
const bookingsToday = ref<Booking[]>([])
const reviewTodo = ref<Review | null>(null)
const onboarding = ref<Checklist | null>(null)
const activity = ref<AppNotification[]>([])
const away = ref<Absence[]>([])
const celebrations = ref<Celebration[]>([])
const companyFeed = ref<ActivityItem[]>([])
const vacation = ref<VacationBalance | null>(null)
const timeStatus = ref<TimeStatus | null>(null)

const awayToday = computed(() => away.value.filter((a) => a.start_date <= todayIso() && a.end_date >= todayIso()))
const awayLater = computed(() => away.value.filter((a) => a.start_date > todayIso()))

const FEED_ICONS: Record<ActivityItem['kind'], string> = { announcement: 'megaphone', document: 'file', new_colleague: 'users', anniversary: 'star' }

function feedText(item: ActivityItem): string {
  if (item.kind === 'new_colleague') return t('dashboard.feedNewColleague', { name: item.title })
  if (item.kind === 'anniversary') return t('dashboard.feedAnniversary', { name: item.title, years: item.years ?? 0 })
  if (item.kind === 'document') return t('dashboard.feedDocument', { title: item.title })
  return item.title
}

function celebrationText(c: Celebration): string {
  if (c.kind === 'birthday') return t('dashboard.celebrateBirthday', { name: c.person.full_name })
  if (c.kind === 'anniversary') return t('dashboard.celebrateAnniversary', { name: c.person.full_name, years: c.years ?? 0 })
  return t('dashboard.celebrateNew', { name: c.person.full_name })
}

function relativeDay(day: string): string {
  if (day === todayIso()) return t('dashboard.today')
  return formatDate(day)
}
const loading = ref(true)
const error = ref<string | null>(null)

const greeting = computed(() => {
  const hour = new Date().getHours()
  const key = hour < 11 ? 'greetingMorning' : hour < 18 ? 'greetingDay' : 'greetingEvening'
  return t(`dashboard.${key}`, { name: currentUser.value?.first_name ?? '' })
})

/** HR's tile selection, with the person's pinned favourites first. */
const quickActions = computed<TileDefinition[]>(() => {
  const base = portalSettings.value.dashboard_tiles.length ? portalSettings.value.dashboard_tiles : DEFAULT_TILES
  const keys = [...new Set([...(currentUser.value?.pinned_tiles ?? []), ...base])]
  return keys.map(tileByKey).filter((tile): tile is TileDefinition => Boolean(tile))
})

const spotlight = computed(() => announcements.value.find((a) => a.pinned) ?? null)
const latestNews = computed(() => announcements.value.filter((a) => a.id !== spotlight.value?.id).slice(0, 3))
const upcomingEvents = computed(() =>
  announcements.value
    .filter((a) => a.category === 'event' && a.event_date && a.event_date >= todayIso())
    .sort((a, b) => (a.event_date! < b.event_date! ? -1 : 1))
    .slice(0, 3),
)

/** First sentences of a Markdown text as plain text. */
function excerpt(markdown: string, length = 180): string {
  const plain = markdown
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/^\s*(#+|[-*>]|\d+\.)\s+/gm, '')
    .replace(/[*_`]+/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  return plain.length > length ? `${plain.slice(0, length).replace(/\s+\S*$/, '')} …` : plain
}

const attention = computed<AttentionItem[]>(() => {
  const items: AttentionItem[] = []
  const pending = summary.value.approvals_pending
  if (isApprover.value && pending > 0) {
    items.push({
      key: 'approvals', icon: 'checkCircle', tone: 'warning', to: '/approvals', action: t('dashboard.reviewNow'),
      text: pending === 1 ? t('dashboard.pendingApprovalsOne') : t('dashboard.pendingApprovals', { count: pending }),
    })
  }
  if (reviewTodo.value) {
    items.push({
      key: 'review', icon: 'message', tone: 'info', to: `/reviews/${reviewTodo.value.id}`, action: t('dashboard.reviewOpen'),
      text: t('dashboard.reviewTodo', { year: reviewTodo.value.year }),
    })
  }
  if (onboarding.value) {
    items.push({
      key: 'onboarding', icon: 'clipboard', tone: 'info', to: `/onboarding/${onboarding.value.person.id}`, action: t('dashboard.onboardingOpen'),
      text: `${t('dashboard.onboardingTitle')}: ${t('dashboard.onboardingProgress', { done: onboarding.value.done, total: onboarding.value.total })}`,
    })
  }
  if (summary.value.must_read_open > 0) {
    const count = summary.value.must_read_open
    items.push({
      key: 'must-read', icon: 'megaphone', tone: 'warning', to: '/announcements', action: t('dashboard.mustReadOpen'),
      text: count === 1 ? t('dashboard.mustReadOne') : t('dashboard.mustRead', { count }),
    })
  }
  if (summary.value.personal_documents_new > 0) {
    const count = summary.value.personal_documents_new
    items.push({
      key: 'personal', icon: 'file', tone: 'info', to: '/documents?tab=mine', action: t('dashboard.personalOpen'),
      text: count === 1 ? t('dashboard.personalOne') : t('dashboard.personal', { count }),
    })
  }
  if (summary.value.trainings_due > 0) {
    const count = summary.value.trainings_due
    items.push({
      key: 'trainings', icon: 'graduation', tone: 'warning', to: '/trainings', action: t('dashboard.trainingsOpen'),
      text: count === 1 ? t('dashboard.trainingsOne') : t('dashboard.trainings', { count }),
    })
  }
  if (summary.value.time_months_pending > 0) {
    const count = summary.value.time_months_pending
    items.push({
      key: 'time-months', icon: 'clock', tone: 'warning', to: '/time?tab=team', action: t('dashboard.timeMonthsOpen'),
      text: count === 1 ? t('dashboard.timeMonthsOne') : t('dashboard.timeMonths', { count }),
    })
  }
  if (summary.value.surveys_open > 0) {
    const count = summary.value.surveys_open
    items.push({
      key: 'surveys', icon: 'chart', tone: 'info', to: '/surveys', action: t('dashboard.surveysOpen'),
      text: count === 1 ? t('dashboard.surveysOne') : t('dashboard.surveys', { count }),
    })
  }
  const visitors = summary.value.visitors_today
  if (visitors > 0) {
    items.push({
      key: 'visitors', icon: 'badge', tone: 'info', to: '/visitors', action: t('dashboard.visitorsOpen'),
      text: visitors === 1 ? t('dashboard.visitorsTodayOne') : t('dashboard.visitorsToday', { count: visitors }),
    })
  }
  return items
})

async function load() {
  loading.value = true
  error.value = null
  try {
    const [requests, news] = await Promise.all([
      api.get<RequestList>('/api/requests?status=submitted,in_review,draft&limit=5'),
      api.get<Announcement[]>('/api/announcements?limit=10'),
    ])
    openRequests.value = requests.items
    openTotal.value = requests.total
    announcements.value = news
    // Optional extras: the dashboard still works if one of them fails.
    const [bookings, reviews, checklist, notes, absences, parties, feed, balance, time] = await Promise.allSettled([
      api.get<Booking[]>('/api/rooms/bookings/mine'),
      api.get<Review[]>('/api/reviews'),
      api.get<Checklist>(`/api/onboarding/${currentUser.value?.id}`),
      api.get<NotificationList>('/api/notifications?limit=4'),
      api.get<Absence[]>('/api/team/away?days=7'),
      api.get<Celebration[]>('/api/team/celebrations?days=14'),
      api.get<ActivityItem[]>('/api/activity?limit=5'),
      api.get<VacationBalance>('/api/me/vacation'),
      api.get<TimeStatus>('/api/time/status'),
      refreshSummary(true),
    ])
    if (time.status === 'fulfilled') timeStatus.value = time.value
    if (absences.status === 'fulfilled') away.value = absences.value
    if (parties.status === 'fulfilled') celebrations.value = parties.value.slice(0, 5)
    if (feed.status === 'fulfilled') companyFeed.value = feed.value
    if (balance.status === 'fulfilled') vacation.value = balance.value
    if (bookings.status === 'fulfilled') bookingsToday.value = bookings.value.filter((b) => b.day === todayIso())
    if (reviews.status === 'fulfilled') {
      reviewTodo.value =
        reviews.value.find(
          (r) => r.status === 'preparation' && ((r.my_side === 'employee' && !r.employee_prep_done) || (r.my_side === 'reviewer' && !r.reviewer_prep_done)),
        ) ?? null
    }
    if (checklist.status === 'fulfilled' && checklist.value.total > 0 && checklist.value.done < checklist.value.total) onboarding.value = checklist.value
    if (notes.status === 'fulfilled') activity.value = notes.value.items
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <header class="hero">
      <div class="stack-sm">
        <p class="today muted small">{{ formatDateLong(todayIso()) }}</p>
        <h1>{{ greeting }}</h1>
        <p class="muted">{{ t('dashboard.intro') }}</p>
      </div>
    </header>

    <RouterLink v-if="spotlight" :to="`/announcements#a-${spotlight.id}`" class="spotlight">
      <span class="spotlight-tag"><AppIcon name="pin" :size="14" />{{ t('dashboard.spotlight') }}</span>
      <span class="spotlight-title">{{ spotlight.title }}</span>
      <span class="spotlight-text">{{ excerpt(spotlight.body) }}</span>
      <span class="spotlight-more">{{ t('dashboard.readMore') }}<AppIcon name="chevronRight" :size="16" /></span>
    </RouterLink>

    <section aria-labelledby="stats-title">
      <h2 id="stats-title" class="visually-hidden">{{ t('dashboard.atAGlance') }}</h2>
      <div class="stats">
        <StatTile v-if="isApprover" to="/approvals" icon="checkCircle" :tone="summary.approvals_pending ? 'warning' : 'neutral'" :value="summary.approvals_pending" :label="t('dashboard.statApprovals')" />
        <StatTile
          v-if="timeStatus"
          to="/time"
          icon="clock"
          :tone="timeStatus.running ? 'success' : 'neutral'"
          :value="hours(timeStatus.today_worked)"
          :label="timeStatus.running ? t('dashboard.statTimeRunning') : t('dashboard.statTime')"
        />
        <StatTile to="/requests" icon="inbox" :value="openTotal" :label="t('dashboard.statOpenRequests')" />
        <StatTile v-if="vacation" to="/requests/new/vacation" icon="sun" tone="success" :value="vacation.remaining" :label="t('dashboard.statVacation', { total: vacation.entitlement })" />
        <StatTile v-if="!timeStatus" to="/rooms" icon="door" tone="neutral" :value="bookingsToday.length" :label="t('dashboard.statBookings')" />
      </div>
    </section>

    <section aria-labelledby="quick-title">
      <h2 id="quick-title" class="section-title">{{ t('dashboard.quickActions') }}</h2>
      <ul class="quick">
        <li v-for="action in quickActions" :key="action.key">
          <RouterLink :to="action.to" class="quick-action">
            <span class="quick-icon"><AppIcon :name="action.icon" :size="22" /></span>
            <span>{{ t(action.label) }}</span>
          </RouterLink>
        </li>
      </ul>
    </section>

    <LoadState :loading="loading" :error="error" @retry="load">
      <div class="bento">
        <section class="card card-flush attention" aria-labelledby="attention-title">
          <div class="section-head">
            <h2 id="attention-title">{{ t('dashboard.attentionTitle') }}</h2>
            <span v-if="attention.length" class="count-badge">{{ attention.length }}</span>
          </div>
          <ul v-if="attention.length" class="list">
            <li v-for="item in attention" :key="item.key" class="attention-item">
              <span class="attention-icon" :class="`tone-${item.tone}`"><AppIcon :name="item.icon" :size="20" /></span>
              <p class="attention-text">{{ item.text }}</p>
              <RouterLink :to="item.to" class="btn btn-secondary">{{ item.action }}</RouterLink>
            </li>
          </ul>
          <div v-else class="all-done">
            <AppIcon name="checkCircle" :size="28" />
            <p>{{ t('dashboard.attentionEmpty') }}</p>
          </div>
        </section>

        <section class="card card-flush activity" aria-labelledby="activity-title">
          <div class="section-head"><h2 id="activity-title">{{ t('dashboard.recentActivity') }}</h2></div>
          <ul v-if="activity.length" class="list">
            <li v-for="item in activity" :key="item.id">
              <RouterLink :to="item.link || '/'" class="list-link activity-item">
                <span class="activity-icon" :class="{ unread: !item.read }"><AppIcon :name="NOTIFICATION_ICONS[item.kind] ?? 'bell'" :size="18" /></span>
                <span class="stack-sm">
                  <span>{{ notificationText(item) }}</span>
                  <span class="muted small">{{ timeAgo(item.created_at, locale) }}</span>
                </span>
              </RouterLink>
            </li>
          </ul>
          <EmptyState v-else icon="bell" :message="t('notifications.empty')" />
        </section>

        <div class="side-column">
          <section class="card card-flush requests" aria-labelledby="open-title">
            <div class="section-head">
              <h2 id="open-title">{{ t('dashboard.openRequests') }}</h2>
              <RouterLink to="/requests" class="btn btn-ghost">{{ t('dashboard.allRequests') }}</RouterLink>
            </div>
            <ul v-if="openRequests.length" class="list">
              <li v-for="request in openRequests" :key="request.id"><RequestRow :request="request" /></li>
            </ul>
            <EmptyState v-else icon="inbox" :message="t('dashboard.noOpenRequests')" :action-label="t('requests.new')" action-to="/requests/new" />
          </section>

          <section v-if="companyFeed.length" class="card card-flush feed" aria-labelledby="feed-title">
            <div class="section-head"><h2 id="feed-title">{{ t('dashboard.feedTitle') }}</h2></div>
            <ul class="list">
              <li v-for="item in companyFeed" :key="`${item.kind}-${item.link}-${item.date}`">
                <RouterLink :to="item.link" class="list-link activity-item">
                  <span class="activity-icon"><AppIcon :name="FEED_ICONS[item.kind]" :size="18" /></span>
                  <span class="stack-sm">
                    <span>{{ feedText(item) }}</span>
                    <span class="muted small">{{ relativeDay(item.date) }}</span>
                  </span>
                </RouterLink>
              </li>
            </ul>
          </section>
        </div>

        <div class="side-column">
          <section class="card card-flush" aria-labelledby="away-title">
            <div class="section-head">
              <h2 id="away-title">{{ t('dashboard.awayTitle') }}</h2>
              <RouterLink to="/calendar" class="btn btn-ghost">{{ t('nav.calendar') }}</RouterLink>
            </div>
            <div class="away-body">
              <p v-if="!away.length" class="muted small">{{ t('dashboard.awayNobody') }}</p>
              <template v-else>
                <p class="away-label small">{{ t('dashboard.today') }}</p>
                <ul v-if="awayToday.length" class="people-chips">
                  <li v-for="a in awayToday" :key="`${a.person.id}-${a.start_date}`" class="chip" :class="`chip-${a.type}`">
                    <UserAvatar :id="a.person.id" :name="a.person.full_name" :photo-version="a.person.photo_version" :size="32" />
                    <span>
                      {{ a.person.full_name }}
                      <span class="chip-sub">{{ t(`calendar.kinds.${a.type}`) }}<template v-if="a.end_date !== todayIso()"> · {{ t('dashboard.until', { date: formatDate(a.end_date) }) }}</template></span>
                    </span>
                  </li>
                </ul>
                <p v-else class="muted small">{{ t('dashboard.awayNobodyToday') }}</p>
                <template v-if="awayLater.length">
                  <p class="away-label small">{{ t('dashboard.awayNextDays') }}</p>
                  <ul class="later">
                    <li v-for="a in awayLater" :key="`${a.person.id}-${a.start_date}`" class="small">
                      <strong>{{ a.person.full_name }}</strong> · {{ t(`calendar.kinds.${a.type}`) }} · {{ formatPeriod(a.start_date, a.end_date) }}
                    </li>
                  </ul>
                </template>
              </template>
            </div>
          </section>

          <section v-if="celebrations.length" class="card card-flush" aria-labelledby="celebrate-title">
            <div class="section-head"><h2 id="celebrate-title">{{ t('dashboard.celebrateTitle') }}</h2></div>
            <ul class="list">
              <li v-for="c in celebrations" :key="`${c.kind}-${c.person.id}`" class="event">
                <span class="celebrate-icon" :class="`c-${c.kind}`"><AppIcon :name="c.kind === 'new' ? 'users' : 'star'" :size="18" /></span>
                <span class="stack-sm">
                  <span class="news-title">{{ celebrationText(c) }}</span>
                  <span class="muted small">{{ relativeDay(c.date) }}</span>
                </span>
              </li>
            </ul>
          </section>

          <section class="card card-flush" aria-labelledby="news-title">
            <div class="section-head">
              <h2 id="news-title">{{ t('dashboard.latestNews') }}</h2>
              <RouterLink to="/announcements" class="btn btn-ghost">{{ t('dashboard.allNews') }}</RouterLink>
            </div>
            <ul v-if="latestNews.length" class="list">
              <li v-for="item in latestNews" :key="item.id">
                <RouterLink :to="`/announcements#a-${item.id}`" class="list-link news">
                  <span class="news-title">
                    <AppIcon v-if="item.pinned" name="pin" :size="16" :label="t('announcements.pinned')" />
                    {{ item.title }}
                  </span>
                  <span class="muted small">{{ formatDate(item.publish_date) }}</span>
                </RouterLink>
              </li>
            </ul>
            <EmptyState v-else icon="megaphone" :message="t('dashboard.noNews')" />
          </section>

          <section v-if="bookingsToday.length" class="card card-flush" aria-labelledby="bookings-title">
            <div class="section-head">
              <h2 id="bookings-title">{{ t('dashboard.myBookings') }}</h2>
              <RouterLink to="/rooms" class="btn btn-ghost">{{ t('nav.rooms') }}</RouterLink>
            </div>
            <ul class="list">
              <li v-for="booking in bookingsToday" :key="booking.id" class="event">
                <span class="time-chip">{{ booking.start_time }}</span>
                <span class="stack-sm">
                  <span class="news-title">{{ booking.title }}</span>
                  <span class="muted small">{{ t('rooms.timeRange', { start: booking.start_time, end: booking.end_time }) }} · {{ booking.room_name }}</span>
                </span>
              </li>
            </ul>
          </section>

          <section v-if="upcomingEvents.length" class="card card-flush" aria-labelledby="events-title">
            <div class="section-head"><h2 id="events-title">{{ t('dashboard.events') }}</h2></div>
            <ul class="list">
              <li v-for="item in upcomingEvents" :key="item.id" class="event">
                <span class="date-chip" aria-hidden="true">
                  <span class="date-day">{{ new Date(`${item.event_date}T00:00`).getDate() }}</span>
                  <span class="date-month">{{ new Date(`${item.event_date}T00:00`).toLocaleDateString(locale, { month: 'short' }) }}</span>
                </span>
                <span class="stack-sm">
                  <span class="news-title">
                    {{ item.title }}
                    <span v-if="item.event_date === todayIso()" class="today-badge">{{ t('dashboard.today') }}</span>
                  </span>
                  <span class="muted small">{{ formatDateLong(item.event_date) }}</span>
                </span>
              </li>
            </ul>
          </section>
        </div>
      </div>
    </LoadState>

    <SectionContact section="dashboard" />
  </div>
</template>

<style scoped>
.hero h1 {
  font-size: clamp(1.5rem, 1.2rem + 1.2vw, 2rem);
}

.today {
  text-transform: capitalize;
  font-weight: 600;
}

/* ---------- Spotlight (pinned announcement) ---------- */

.spotlight {
  position: relative;
  display: grid;
  gap: var(--space-2);
  padding: var(--space-5) var(--space-6);
  border-radius: var(--radius-lg);
  background: var(--color-highlight);
  color: #ffffff;
  text-decoration: none;
  overflow: hidden;
  box-shadow: 0 8px 24px rgb(29 78 216 / 0.25);
}

.spotlight::after {
  content: '';
  position: absolute;
  right: -60px;
  top: -60px;
  width: 220px;
  height: 220px;
  border-radius: 50%;
  background: rgb(255 255 255 / 0.08);
  pointer-events: none;
}

.spotlight-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  justify-self: start;
  padding: 2px 10px;
  border-radius: var(--radius-full);
  background: rgb(255 255 255 / 0.18);
  font-size: var(--text-xs);
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.spotlight-title {
  font-family: var(--font-heading);
  font-size: var(--text-xl);
  font-weight: 600;
  line-height: 1.25;
}

.spotlight-text {
  max-width: 70ch;
  color: rgb(255 255 255 / 0.9);
}

.spotlight-more {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-weight: 600;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.spotlight:focus-visible {
  outline-color: var(--color-focus);
}

/* ---------- Stats and quick actions ---------- */

.stats {
  display: grid;
  gap: var(--space-3);
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr));
}

.section-title {
  margin-bottom: var(--space-3);
  font-size: var(--text-md);
}

.quick {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-3);
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 200px), 1fr));
}

.quick-action {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-height: 64px;
  height: 100%;
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: var(--shadow-card);
  color: var(--color-text);
  font-weight: 600;
  text-decoration: none;
  transition: border-color var(--t-fast) ease, box-shadow var(--t-fast) ease, transform var(--t-fast) ease;
}

.quick-action:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-hover);
  transform: translateY(-1px);
}

.quick-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
  flex-shrink: 0;
}

.grow {
  flex: 1;
}

/* ---------- Bento grid ---------- */

.bento {
  display: grid;
  gap: var(--space-5);
  grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
  align-items: start;
}

.side-column {
  display: grid;
  gap: var(--space-5);
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  min-height: 56px;
  padding: var(--space-2) var(--space-3) var(--space-2) var(--space-5);
  border-bottom: 1px solid var(--color-border);
}

.attention-item {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3) var(--space-4);
  padding: var(--space-3) var(--space-5);
}

.attention-text {
  flex: 1 1 220px;
}

.attention-icon,
.activity-icon {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  flex-shrink: 0;
}

.attention-icon.tone-info,
.activity-icon.unread {
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
}

.attention-icon.tone-warning {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}

.activity-icon {
  background: var(--color-neutral-soft);
  color: var(--color-text-muted);
}

.activity-item {
  align-items: flex-start;
  font-size: var(--text-sm);
}

.all-done {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-5);
  color: var(--color-success);
}

.all-done p {
  color: var(--color-text-muted);
}

.news {
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 2px;
}

.news-title {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  font-weight: 600;
}

.event {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-5);
  color: var(--color-text);
}

.time-chip {
  display: grid;
  place-items: center;
  min-width: 52px;
  height: 36px;
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--color-success-soft);
  color: var(--color-success);
  font-weight: 700;
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
}

.date-chip {
  display: grid;
  place-items: center;
  width: 48px;
  padding: 4px 0;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
  line-height: 1.1;
  flex-shrink: 0;
}

.date-day {
  font-family: var(--font-heading);
  font-size: var(--text-lg);
  font-weight: 600;
}

.date-month {
  color: var(--color-primary-text);
  font-size: var(--text-xs);
  font-weight: 700;
  text-transform: uppercase;
}

.away-body {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-4) var(--space-5);
}

.away-label {
  font-weight: 700;
  color: var(--color-text-subtle);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-size: var(--text-xs);
}

.people-chips {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-2);
}

.chip {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-weight: 600;
  font-size: var(--text-sm);
}

.chip-sub {
  display: block;
  color: var(--color-text-muted);
  font-weight: 400;
  font-size: var(--text-xs);
}

.mini-avatar {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  font-size: var(--text-xs);
  font-weight: 700;
  flex-shrink: 0;
}

.chip-vacation .mini-avatar {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}

.chip-home_office .mini-avatar {
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
}

.later {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-1);
}

.celebrate-icon {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--color-warning-soft);
  color: var(--color-warning);
}

.celebrate-icon.c-new {
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
}

.today-badge {
  padding: 2px 10px;
  border-radius: var(--radius-full);
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
  font-size: var(--text-xs);
  font-weight: 600;
  white-space: nowrap;
}

@media (max-width: 560px) {
  .quick {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .spotlight {
    padding: var(--space-4);
  }
}

@media (max-width: 1100px) {
  .bento {
    grid-template-columns: 1fr;
  }
}
</style>
