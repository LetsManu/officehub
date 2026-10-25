<script setup lang="ts">
/** Green: synced within 24 hours without problems; amber: problems or longer ago; grey: never synced. */
import { t } from '@/lib/i18n'
import type { SyncState } from '@/lib/types'

defineProps<{ status: SyncState }>()
</script>

<template>
  <span class="badge" :class="`badge-${status}`">
    <span class="dot" aria-hidden="true" />
    {{ t(`syncDevices.status.${status}`) }}
  </span>
</template>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: var(--text-xs);
  font-weight: 600;
  white-space: nowrap;
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

.badge-ok {
  background: var(--color-success-soft);
  color: var(--color-success);
}

.badge-problem {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}

.badge-never {
  background: var(--color-neutral-soft);
  color: var(--color-text-muted);
}
</style>
