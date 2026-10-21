<script setup lang="ts">
/** "Your meeting starts in 5 minutes – Join", like the reminder in Outlook and Teams. */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import AppIcon from './AppIcon.vue'
import { locale, t } from '@/lib/i18n'
import { summary } from '@/lib/summary'

const route = useRoute()
const dismissed = ref<Set<string>>(new Set())
const now = ref(Date.now())
let ticker: number | undefined

const key = (r: { meeting_id: number; starts_at: string }) => `${r.meeting_id}-${r.starts_at}`
const shown = computed(() =>
  (summary.value.reminders ?? []).filter((r) => !dismissed.value.has(key(r)) && !route.path.startsWith(`/meetings/${r.meeting_id}/room`)),
)

function when(starts: string) {
  const minutes = Math.round((new Date(starts).getTime() - now.value) / 60_000)
  if (minutes > 0) return t('reminder.inMinutes', { n: minutes })
  return t('reminder.now')
}

function clock(iso: string) {
  return new Date(iso).toLocaleTimeString(locale.value, { hour: '2-digit', minute: '2-digit' })
}

function dismiss(r: { meeting_id: number; starts_at: string }) {
  dismissed.value = new Set([...dismissed.value, key(r)])
}

onMounted(() => (ticker = window.setInterval(() => (now.value = Date.now()), 30_000)))
onBeforeUnmount(() => window.clearInterval(ticker))
</script>

<template>
  <TransitionGroup name="rem" tag="div" class="reminders" role="region" :aria-label="t('reminder.title')">
    <div v-for="r in shown" :key="key(r)" class="reminder" role="status">
      <span class="icon" aria-hidden="true"><AppIcon name="calendar" :size="18" /></span>
      <div class="text">
        <p class="title">{{ r.title }}</p>
        <p class="muted small">{{ clock(r.starts_at) }} – {{ clock(r.ends_at) }} · {{ when(r.starts_at) }}</p>
      </div>
      <RouterLink :to="`/meetings/${r.meeting_id}/room`" class="btn btn-primary" @click="dismiss(r)"><AppIcon name="video" :size="16" />{{ t('meetings.join') }}</RouterLink>
      <button type="button" class="btn btn-ghost btn-icon" :aria-label="t('reminder.dismiss')" @click="dismiss(r)"><AppIcon name="close" :size="16" /></button>
    </div>
  </TransitionGroup>
</template>

<style scoped>
.reminders {
  position: fixed;
  z-index: 1150;
  right: var(--space-4);
  bottom: var(--space-4);
  display: grid;
  gap: var(--space-2);
  width: min(400px, calc(100vw - 2 * var(--space-4)));
}

.reminder {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-left: 4px solid var(--color-primary);
  border-radius: var(--radius-lg);
  background: var(--color-surface-raised);
  box-shadow: var(--shadow-overlay);
}

.icon {
  display: grid;
  width: 34px;
  height: 34px;
  flex: none;
  place-items: center;
  border-radius: 50%;
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
}

.text {
  flex: 1;
  min-width: 0;
}

.text p {
  margin: 0;
}

.title {
  overflow: hidden;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rem-enter-active,
.rem-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.rem-enter-from,
.rem-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
