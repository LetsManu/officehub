<script setup lang="ts">
/** "Is it running?" badge: green, amber, red or grey, always with the word (never colour alone). */
defineProps<{ tone: 'ok' | 'warn' | 'bad' | 'off'; label: string }>()
</script>

<template>
  <span class="badge" :class="`tone-${tone}`">
    <span class="dot" aria-hidden="true" />
    {{ label }}
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

.tone-ok {
  background: var(--color-success-soft);
  color: var(--color-success);
}

.tone-warn {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}

.tone-bad {
  background: var(--color-danger-soft);
  color: var(--color-danger);
}

.tone-off {
  background: var(--color-neutral-soft);
  color: var(--color-text-muted);
}
</style>
