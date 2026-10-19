<script setup lang="ts">
/** Bell with unread count; opens a small panel with the latest notifications. */
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from './AppIcon.vue'
import { api } from '@/lib/api'
import { errorText, locale, t } from '@/lib/i18n'
import { NOTIFICATION_ICONS, notificationText, timeAgo } from '@/lib/notifications'
import { refreshSummary, summary } from '@/lib/summary'
import type { AppNotification, NotificationList } from '@/lib/types'

const router = useRouter()
const open = ref(false)
const items = ref<AppNotification[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const root = ref<HTMLElement | null>(null)
const button = ref<HTMLButtonElement | null>(null)
const panel = ref<HTMLElement | null>(null)

async function load() {
  loading.value = items.value.length === 0
  error.value = null
  try {
    const result = await api.get<NotificationList>('/api/notifications')
    items.value = result.items
    summary.value = { ...summary.value, unread: result.unread }
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

async function choose(item: AppNotification) {
  open.value = false
  if (!item.read) {
    item.read = true
    summary.value = { ...summary.value, unread: Math.max(0, summary.value.unread - 1) }
    api.post(`/api/notifications/${item.id}/read`).catch(() => undefined)
  }
  if (item.link) router.push(item.link)
}

async function readAll() {
  await api.post('/api/notifications/read-all')
  items.value = items.value.map((item) => ({ ...item, read: true }))
  refreshSummary(true)
}

function onDocumentClick(event: MouseEvent) {
  if (root.value && !root.value.contains(event.target as Node)) open.value = false
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    open.value = false
    button.value?.focus()
  }
}

watch(open, async (value) => {
  if (value) {
    document.addEventListener('mousedown', onDocumentClick)
    await load()
    await nextTick()
    panel.value?.querySelector<HTMLElement>('button, a')?.focus()
  } else {
    document.removeEventListener('mousedown', onDocumentClick)
  }
})

onBeforeUnmount(() => document.removeEventListener('mousedown', onDocumentClick))

const label = () => (summary.value.unread ? t('notifications.openUnread', { count: summary.value.unread }) : t('notifications.open'))
</script>

<template>
  <div ref="root" class="bell" @keydown="open && onKeydown($event)">
    <button
      ref="button"
      type="button"
      class="btn btn-ghost btn-icon header-btn"
      :aria-label="label()"
      :aria-expanded="open"
      aria-controls="notification-panel"
      @click="open = !open"
    >
      <AppIcon name="bell" />
      <span v-if="summary.unread" class="count-badge dot" aria-hidden="true">{{ summary.unread > 9 ? '9+' : summary.unread }}</span>
    </button>

    <Transition name="pop">
      <section v-if="open" id="notification-panel" ref="panel" class="panel" :aria-label="t('notifications.title')">
        <header class="panel-head">
          <h2>{{ t('notifications.title') }}</h2>
          <button v-if="items.some((i) => !i.read)" type="button" class="btn btn-ghost small-btn" @click="readAll">
            <AppIcon name="checkAll" :size="18" />{{ t('notifications.readAll') }}
          </button>
        </header>
        <div v-if="loading" class="panel-body stack-sm">
          <span v-for="n in 3" :key="n" class="skeleton line" />
        </div>
        <p v-else-if="error" class="panel-body muted">{{ error }}</p>
        <ul v-else-if="items.length" class="list items">
          <li v-for="item in items" :key="item.id">
            <button type="button" class="item" :class="{ unread: !item.read }" @click="choose(item)">
              <span class="item-icon"><AppIcon :name="NOTIFICATION_ICONS[item.kind] ?? 'bell'" :size="18" /></span>
              <span class="item-text">
                <span>{{ notificationText(item) }}</span>
                <span class="muted small">{{ timeAgo(item.created_at, locale) }}</span>
              </span>
              <span v-if="!item.read" class="unread-dot"><span class="visually-hidden">{{ t('notifications.unread') }}</span></span>
            </button>
          </li>
        </ul>
        <div v-else class="panel-body empty">
          <AppIcon name="bell" :size="28" />
          <p class="muted">{{ t('notifications.empty') }}</p>
        </div>
      </section>
    </Transition>
  </div>
</template>

<style scoped>
.bell {
  position: relative;
}

.header-btn {
  position: relative;
  color: var(--color-text-muted);
}

.header-btn:hover {
  color: var(--color-text);
}

.dot {
  position: absolute;
  top: 4px;
  right: 2px;
  min-width: 18px;
  height: 18px;
  padding: 0 4px;
  font-size: 0.6875rem;
  box-shadow: 0 0 0 2px var(--color-surface);
}

.panel {
  position: absolute;
  right: 0;
  top: calc(100% + 8px);
  z-index: var(--z-popover);
  width: min(400px, calc(100vw - 24px));
  max-height: min(560px, calc(100vh - 96px));
  display: flex;
  flex-direction: column;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface-raised);
  box-shadow: var(--shadow-overlay);
  overflow: hidden;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-3) var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.panel-head h2 {
  font-size: var(--text-md);
}

.small-btn {
  min-height: 36px;
  padding: 0 var(--space-3);
}

.panel-body {
  padding: var(--space-4);
}

.line {
  height: 44px;
}

.items {
  overflow-y: auto;
}

.item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  width: 100%;
  min-height: 64px;
  padding: var(--space-3) var(--space-4);
  border: 0;
  background: transparent;
  color: var(--color-text);
  font: inherit;
  font-size: var(--text-sm);
  text-align: left;
  cursor: pointer;
}

.item:hover {
  background: var(--color-surface-muted);
}

.item:focus-visible {
  outline-offset: -3px;
}

.item.unread {
  background: color-mix(in srgb, var(--color-primary-soft) 55%, transparent);
}

.item.unread:hover {
  background: var(--color-primary-soft);
}

.item-icon {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--color-neutral-soft);
  color: var(--color-text-muted);
  flex-shrink: 0;
}

.unread .item-icon {
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
}

.item-text {
  display: grid;
  gap: 2px;
  flex: 1;
}

.unread-dot {
  width: 8px;
  height: 8px;
  margin-top: 8px;
  border-radius: 50%;
  background: var(--color-primary);
  flex-shrink: 0;
}

.empty {
  display: grid;
  justify-items: center;
  gap: var(--space-2);
  padding: var(--space-6) var(--space-4);
  color: var(--color-text-subtle);
  text-align: center;
}

.pop-enter-active,
.pop-leave-active {
  transition: opacity var(--t-fast) ease, transform var(--t-fast) var(--ease);
}

.pop-enter-from,
.pop-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.98);
}
</style>
