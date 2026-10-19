<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadState from '@/components/LoadState.vue'
import RequestRow from '@/components/RequestRow.vue'
import SectionContact from '@/components/SectionContact.vue'
import { api } from '@/lib/api'
import { portalSettings } from '@/lib/portal'
import { currentUser, isApprover } from '@/lib/session'
import { errorText, formatDate, formatDateLong, t } from '@/lib/i18n'
import { DEFAULT_TILES, tileByKey, type TileDefinition } from '@/lib/tiles'
import type { Announcement, Booking, Checklist, OfficeRequest, RequestList, Review, Stats, Visitor } from '@/lib/types'
import { todayIso } from '@/lib/workdays'

const openRequests = ref<OfficeRequest[]>([])
const announcements = ref<Announcement[]>([])
const pendingApprovals = ref(0)
const bookingsToday = ref<Booking[]>([])
const reviewTodo = ref<Review | null>(null)
const onboarding = ref<Checklist | null>(null)
const visitorsToday = ref(0)
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

const latestNews = computed(() => announcements.value.slice(0, 3))
const upcomingEvents = computed(() =>
  announcements.value
    .filter((a) => a.category === 'event' && a.event_date && a.event_date >= todayIso())
    .sort((a, b) => (a.event_date! < b.event_date! ? -1 : 1))
    .slice(0, 3),
)

async function load() {
  loading.value = true
  error.value = null
  try {
    const [requests, news] = await Promise.all([
      api.get<RequestList>('/api/requests?status=submitted,in_review,draft&limit=5'),
      api.get<Announcement[]>('/api/announcements?limit=10'),
    ])
    openRequests.value = requests.items
    announcements.value = news
    // Optional extras: the dashboard still works if one of them fails.
    const [stats, bookings, reviews, checklist, visitors] = await Promise.allSettled([
      isApprover.value ? api.get<Stats>('/api/admin/stats') : Promise.reject(),
      api.get<Booking[]>('/api/rooms/bookings/mine'),
      api.get<Review[]>('/api/reviews'),
      api.get<Checklist>(`/api/onboarding/${currentUser.value?.id}`),
      isApprover.value ? api.get<Visitor[]>('/api/visitors?scope=day') : Promise.reject(),
    ])
    if (stats.status === 'fulfilled') pendingApprovals.value = stats.value.pending
    if (bookings.status === 'fulfilled') bookingsToday.value = bookings.value.filter((b) => b.day === todayIso())
    if (reviews.status === 'fulfilled') {
      reviewTodo.value =
        reviews.value.find(
          (r) => r.status === 'preparation' && ((r.my_side === 'employee' && !r.employee_prep_done) || (r.my_side === 'reviewer' && !r.reviewer_prep_done)),
        ) ?? null
    }
    if (checklist.status === 'fulfilled' && checklist.value.total > 0 && checklist.value.done < checklist.value.total) onboarding.value = checklist.value
    if (visitors.status === 'fulfilled') visitorsToday.value = visitors.value.filter((v) => v.status === 'expected').length
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
    <header class="stack-sm">
      <h1>{{ greeting }}</h1>
      <p class="muted">{{ t('dashboard.intro') }}</p>
    </header>

    <section aria-labelledby="quick-title">
      <h2 id="quick-title" class="visually-hidden">{{ t('dashboard.quickActions') }}</h2>
      <ul class="quick">
        <li v-for="action in quickActions" :key="action.key">
          <RouterLink :to="action.to" class="quick-action">
            <span class="quick-icon"><AppIcon :name="action.icon" :size="22" /></span>
            <span>{{ t(action.label) }}</span>
          </RouterLink>
        </li>
      </ul>
    </section>

    <div v-if="reviewTodo" class="notice notice-info">
      <AppIcon name="message" />
      <div class="row-between grow">
        <p>{{ t('dashboard.reviewTodo', { year: reviewTodo.year }) }}</p>
        <RouterLink :to="`/reviews/${reviewTodo.id}`" class="btn btn-secondary">{{ t('dashboard.reviewOpen') }}</RouterLink>
      </div>
    </div>

    <div v-if="onboarding" class="notice notice-info">
      <AppIcon name="clipboard" />
      <div class="row-between grow">
        <div class="stack-sm">
          <p><strong>{{ t('dashboard.onboardingTitle') }}</strong> · {{ t('dashboard.onboardingProgress', { done: onboarding.done, total: onboarding.total }) }}</p>
          <progress :value="onboarding.done" :max="onboarding.total" :aria-label="t('dashboard.onboardingProgress', { done: onboarding.done, total: onboarding.total })" />
        </div>
        <RouterLink :to="`/onboarding/${onboarding.person.id}`" class="btn btn-secondary">{{ t('dashboard.onboardingOpen') }}</RouterLink>
      </div>
    </div>

    <div v-if="isApprover && visitorsToday > 0" class="notice">
      <AppIcon name="badge" />
      <div class="row-between grow">
        <p>{{ visitorsToday === 1 ? t('dashboard.visitorsTodayOne') : t('dashboard.visitorsToday', { count: visitorsToday }) }}</p>
        <RouterLink to="/visitors" class="btn btn-secondary">{{ t('dashboard.visitorsOpen') }}</RouterLink>
      </div>
    </div>

    <div v-if="isApprover && pendingApprovals > 0" class="notice notice-info">
      <AppIcon name="checkCircle" />
      <div class="row-between grow">
        <p>{{ pendingApprovals === 1 ? t('dashboard.pendingApprovalsOne') : t('dashboard.pendingApprovals', { count: pendingApprovals }) }}</p>
        <RouterLink to="/approvals" class="btn btn-primary">{{ t('dashboard.reviewNow') }}</RouterLink>
      </div>
    </div>

    <LoadState :loading="loading" :error="error" @retry="load">
      <div class="columns">
        <section class="card card-flush" aria-labelledby="open-title">
          <div class="section-head">
            <h2 id="open-title">{{ t('dashboard.openRequests') }}</h2>
            <RouterLink to="/requests" class="btn btn-ghost">{{ t('dashboard.allRequests') }}</RouterLink>
          </div>
          <ul v-if="openRequests.length" class="list">
            <li v-for="request in openRequests" :key="request.id"><RequestRow :request="request" /></li>
          </ul>
          <EmptyState v-else icon="inbox" :message="t('dashboard.noOpenRequests')" :action-label="t('requests.new')" action-to="/requests/new" />
        </section>

        <div class="side-column">
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
                <AppIcon name="door" />
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
                <AppIcon name="calendar" />
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
.quick {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-3);
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 220px), 1fr));
}

.quick-action {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-height: 72px;
  height: 100%;
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  color: var(--color-text);
  font-weight: 600;
  text-decoration: none;
  transition: border-color 0.15s ease;
}

.quick-action:hover {
  border-color: var(--color-primary);
}

.quick-icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: var(--radius-md);
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
  flex-shrink: 0;
}

.grow {
  flex: 1;
}

.notice progress {
  width: 220px;
  max-width: 100%;
  height: 8px;
  accent-color: var(--color-success);
}

.columns {
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
  padding: var(--space-3) var(--space-3) var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--color-border);
}

.news {
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 2px;
}

.news-title {
  display: inline-flex;
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

.today-badge {
  padding: 2px 10px;
  border-radius: 999px;
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
  font-size: var(--text-xs);
  font-weight: 600;
  white-space: nowrap;
}

.event > .icon {
  color: var(--color-primary-text);
}

@media (max-width: 560px) {
  .quick {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 1100px) {
  .columns {
    grid-template-columns: 1fr;
  }
}
</style>
