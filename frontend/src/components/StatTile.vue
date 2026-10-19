<script setup lang="ts">
/** A number with a label, e.g. "3 open requests". Links to the page with the details. */
import AppIcon from './AppIcon.vue'

withDefaults(defineProps<{ to: string; icon: string; value: number | string; label: string; tone?: 'primary' | 'warning' | 'success' | 'neutral' }>(), {
  tone: 'primary',
})
</script>

<template>
  <RouterLink :to="to" class="stat" :class="`tone-${tone}`">
    <span class="stat-icon"><AppIcon :name="icon" :size="20" /></span>
    <span class="stat-value">{{ value }}</span>
    <span class="stat-label">{{ label }}</span>
  </RouterLink>
</template>

<style scoped>
.stat {
  display: grid;
  grid-template-columns: auto 1fr;
  grid-template-areas:
    'icon value'
    'icon label';
  align-items: center;
  column-gap: var(--space-3);
  min-width: 0;
  min-height: 84px;
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: var(--shadow-card);
  color: var(--color-text);
  text-decoration: none;
  transition: border-color var(--t-fast) ease, box-shadow var(--t-fast) ease, transform var(--t-fast) ease;
}

.stat:hover {
  border-color: var(--color-border-strong);
  box-shadow: var(--shadow-hover);
  transform: translateY(-1px);
}

.stat-icon {
  grid-area: icon;
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: var(--radius-md);
}

.stat-value {
  grid-area: value;
  font-family: var(--font-heading);
  font-size: var(--text-xl);
  font-weight: 600;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}

.stat-label {
  grid-area: label;
  min-width: 0;
  hyphens: auto;
  overflow-wrap: break-word;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.tone-primary .stat-icon {
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
}

.tone-warning .stat-icon {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}

.tone-success .stat-icon {
  background: var(--color-success-soft);
  color: var(--color-success);
}

.tone-neutral .stat-icon {
  background: var(--color-neutral-soft);
  color: var(--color-text-muted);
}

@media (max-width: 420px) {
  .stat {
    grid-template-columns: 1fr;
    grid-template-areas:
      'icon'
      'value'
      'label';
    row-gap: var(--space-1);
    padding: var(--space-3);
  }

  .stat-icon {
    width: 36px;
    height: 36px;
  }
}
</style>
