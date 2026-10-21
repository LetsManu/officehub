<script setup lang="ts">
/** Everything that happened for me, like the activity feed in Teams: mentions, invitations, approvals … */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import DesktopSettings from '@/components/DesktopSettings.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api } from '@/lib/api'
import { desktopPrefs, desktopSupported } from '@/lib/desktop'
import { errorText, formatDateLong, locale, t } from '@/lib/i18n'
import { NOTIFICATION_ICONS, notificationText, timeAgo } from '@/lib/notifications'
import { refreshSummary, summary } from '@/lib/summary'
import type { AppNotification, NotificationList } from '@/lib/types'

const router = useRouter()
const items = ref<AppNotification[]>([])
const onlyUnread = ref(false)
const loading = ref(true)
const error = ref<string | null>(null)

const shown = computed(() => (onlyUnread.value ? items.value.filter((i) => !i.read) : items.value))
const days = computed(() => {
  const out: { day: string; items: AppNotification[] }[] = []
  for (const item of shown.value) {
    const day = new Date(item.created_at).toDateString()
    const last = out.at(-1)
    if (last?.day === day) last.items.push(item)
    else out.push({ day, items: [item] })
  }
  return out
})

async function load() {
  error.value = null
  try {
    const result = await api.get<NotificationList>('/api/notifications?limit=100')
    items.value = result.items
    summary.value = { ...summary.value, unread: result.unread }
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

function open(item: AppNotification) {
  if (!item.read) {
    item.read = true
    summary.value = { ...summary.value, unread: Math.max(0, summary.value.unread - 1) }
    api.post(`/api/notifications/${item.id}/read`).catch(() => undefined)
  }
  if (item.link) router.push(item.link)
}

async function readAll() {
  await api.post('/api/notifications/read-all')
  items.value = items.value.map((i) => ({ ...i, read: true }))
  refreshSummary(true)
}

onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader :title="t('activity.title')" :subtitle="t('activity.subtitle')">
      <template #actions>
        <button v-if="items.some((i) => !i.read)" type="button" class="btn btn-secondary" @click="readAll"><AppIcon name="checkAll" :size="18" />{{ t('notifications.readAll') }}</button>
      </template>
    </PageHeader>

    <DesktopSettings v-if="desktopSupported && !desktopPrefs.desktop" compact />

    <div class="segmented switch" role="group" :aria-label="t('activity.title')">
      <button type="button" :aria-pressed="!onlyUnread" @click="onlyUnread = false">{{ t('activity.all') }}</button>
      <button type="button" :aria-pressed="onlyUnread" @click="onlyUnread = true">{{ t('notifications.unread') }}<template v-if="summary.unread"> ({{ summary.unread }})</template></button>
    </div>

    <LoadState :loading="loading" :error="error" @retry="load">
      <div v-if="days.length" class="days">
        <section v-for="d in days" :key="d.day" class="card card-flush">
          <h2 class="h3 day">{{ formatDateLong(d.items[0].created_at) }}</h2>
          <ul class="list">
            <li v-for="item in d.items" :key="item.id">
              <button type="button" class="row" :class="{ unread: !item.read }" @click="open(item)">
                <span class="icon" aria-hidden="true"><AppIcon :name="NOTIFICATION_ICONS[item.kind] ?? 'bell'" :size="18" /></span>
                <span class="text">
                  <span>{{ notificationText(item) }}</span>
                  <span class="muted small">{{ timeAgo(item.created_at, locale) }}</span>
                </span>
                <span v-if="!item.read" class="dot"><span class="visually-hidden">{{ t('notifications.unread') }}</span></span>
              </button>
            </li>
          </ul>
        </section>
      </div>
      <section v-else class="card">
        <EmptyState icon="bell" :message="onlyUnread ? t('activity.noneUnread') : t('notifications.empty')" />
      </section>
    </LoadState>
  </div>
</template>

<style scoped>
.switch {
  margin-bottom: var(--space-4);
}

.days {
  display: grid;
  gap: var(--space-4);
  max-width: 820px;
}

.day {
  padding: var(--space-4) var(--space-5) var(--space-2);
}

.row {
  display: flex;
  width: 100%;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-5);
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.row:hover {
  background: var(--color-surface-muted);
}

.row.unread .text > span:first-child {
  font-weight: 600;
}

.icon {
  display: grid;
  flex: none;
  width: 36px;
  height: 36px;
  place-items: center;
  border-radius: 50%;
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
}

.text {
  display: grid;
  flex: 1;
  min-width: 0;
}

.dot {
  width: 10px;
  height: 10px;
  flex: none;
  border-radius: 50%;
  background: var(--color-primary);
}
</style>
