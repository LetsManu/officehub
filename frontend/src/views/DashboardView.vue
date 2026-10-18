<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadState from '@/components/LoadState.vue'
import RequestRow from '@/components/RequestRow.vue'
import { api } from '@/lib/api'
import { currentUser, isApprover } from '@/lib/session'
import { errorText, formatDate, formatDateLong, t } from '@/lib/i18n'
import type { Announcement, OfficeRequest, RequestList, Stats } from '@/lib/types'
import { todayIso } from '@/lib/workdays'

const openRequests = ref<OfficeRequest[]>([])
const announcements = ref<Announcement[]>([])
const pendingApprovals = ref(0)
const loading = ref(true)
const error = ref<string | null>(null)

const greeting = computed(() => {
  const hour = new Date().getHours()
  const key = hour < 11 ? 'greetingMorning' : hour < 18 ? 'greetingDay' : 'greetingEvening'
  return t(`dashboard.${key}`, { name: currentUser.value?.first_name ?? '' })
})

const quickActions = computed(() => [
  { to: '/requests/new/vacation', label: t('dashboard.requestVacation'), icon: 'sun' },
  { to: '/requests/new/expense', label: t('dashboard.submitExpense'), icon: 'receipt' },
  { to: '/requests/new/equipment', label: t('dashboard.requestEquipment'), icon: 'laptop' },
  { to: '/documents', label: t('dashboard.findDocuments'), icon: 'search' },
])

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
    if (isApprover.value) {
      pendingApprovals.value = (await api.get<Stats>('/api/admin/stats')).pending
    }
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
        <li v-for="action in quickActions" :key="action.to">
          <RouterLink :to="action.to" class="quick-action">
            <span class="quick-icon"><AppIcon :name="action.icon" :size="22" /></span>
            <span>{{ action.label }}</span>
          </RouterLink>
        </li>
      </ul>
    </section>

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
  </div>
</template>

<style scoped>
.quick {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-3);
  grid-template-columns: repeat(4, minmax(0, 1fr));
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

@media (max-width: 1100px) {
  .quick {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .columns {
    grid-template-columns: 1fr;
  }
}
</style>
