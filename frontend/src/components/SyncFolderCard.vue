<script setup lang="ts">
/** Windows app: where the OfficeHub folder is on this PC, how the sync is doing and what did not reach OfficeHub. */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import { formatDateTime, t } from '@/lib/i18n'
import { appKind, appSync, onAppEvent, type SyncStatus } from '@/lib/native'

const sync = ref<SyncStatus | null>(null)
const shown = appKind() === 'windows'
let timer: number | undefined

const stop = onAppEvent((e) => {
  if (e.syncStatus) sync.value = e.syncStatus
})

const tone = computed(() => {
  const s = sync.value?.status
  if (s === 'upToDate') return 'ok'
  if (s === 'offline' || s === 'signIn' || s === 'off') return 'warn'
  return 'busy'
})

onMounted(() => {
  if (!shown) return
  appSync('status')
  // Older app versions do not answer: the card then stays hidden
  timer = window.setInterval(() => appSync('status'), 15000)
})

onBeforeUnmount(() => {
  stop()
  window.clearInterval(timer)
})
</script>

<template>
  <section v-if="shown && sync" class="card sync" :aria-label="t('syncFolder.title')">
    <div class="head">
      <span class="folder-icon" :class="tone"><AppIcon name="folder" /></span>
      <div class="grow">
        <h2 class="title">{{ t('syncFolder.title') }}</h2>
        <p class="status" role="status">{{ t(`syncFolder.status.${sync.status}`) }}</p>
      </div>
      <div class="actions">
        <template v-if="sync.setUp">
          <button type="button" class="btn btn-primary" @click="appSync('open')"><AppIcon name="folder" :size="18" />{{ t('syncFolder.open') }}</button>
          <button type="button" class="btn btn-secondary" :disabled="sync.paused" @click="appSync('now')">{{ t('syncFolder.now') }}</button>
          <button type="button" class="btn btn-ghost" @click="appSync('pause')">{{ sync.paused ? t('syncFolder.resume') : t('syncFolder.pause') }}</button>
        </template>
        <button v-else type="button" class="btn btn-primary" @click="appSync('setup')">{{ t('syncFolder.setUp') }}</button>
      </div>
    </div>

    <details v-if="sync.error && sync.status !== 'upToDate'" class="error">
      <summary class="small">{{ t('syncFolder.errorDetails') }}</summary>
      <code class="path">{{ sync.error }}</code>
    </details>

    <p class="where">
      <span class="muted small">{{ t('syncFolder.where') }}</span>
      <code class="path">{{ sync.folder }}</code>
    </p>
    <p class="muted small how">{{ t('syncFolder.how') }}</p>

    <div v-if="sync.problems.length" class="problems">
      <h3 class="problems-title">{{ t('syncFolder.problemsTitle') }}</h3>
      <ul>
        <li v-for="p in sync.problems.slice(0, 5)" :key="`${p.kind}:${p.name}`">
          <AppIcon name="alert" :size="16" />
          <span class="grow"><strong>{{ p.name }}</strong> – {{ t(`syncFolder.problems.${p.kind}`) }}</span>
          <span class="muted small">{{ formatDateTime(new Date(p.at * 1000).toISOString()) }}</span>
        </li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.sync {
  display: grid;
  gap: var(--space-3);
  margin-bottom: var(--space-5);
  padding: var(--space-4) var(--space-5);
}

.head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
}

.folder-icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: var(--radius-md);
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
}

.folder-icon.ok {
  background: var(--color-success-soft);
  color: var(--color-success);
}

.folder-icon.warn {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}

.grow {
  flex: 1;
  min-width: 0;
}

.title {
  margin: 0;
  font-size: var(--text-md, 1.05rem);
}

.status {
  margin: 2px 0 0;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.where {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--space-2);
  margin: 0;
}

.path {
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  background: var(--color-surface-muted);
  font-size: var(--text-sm);
  overflow-wrap: anywhere;
}

.how {
  margin: 0;
}

.error summary {
  cursor: pointer;
  color: var(--color-text-muted);
}

.error code {
  display: block;
  margin-top: var(--space-2);
}

.problems-title {
  margin: 0 0 var(--space-2);
  font-size: var(--text-sm);
  font-weight: 600;
}

.problems ul {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.problems li {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--color-text);
}
</style>
