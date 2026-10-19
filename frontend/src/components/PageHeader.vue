<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import { t } from '@/lib/i18n'

defineProps<{ title: string; subtitle?: string; backTo?: string; backLabel?: string; crumbs?: { label: string; to: string }[] }>()
</script>

<template>
  <header class="page-header">
    <nav v-if="crumbs?.length" class="crumbs" :aria-label="t('app.breadcrumbs')">
      <ol>
        <li v-for="crumb in crumbs" :key="crumb.to">
          <RouterLink :to="crumb.to">{{ crumb.label }}</RouterLink>
          <AppIcon name="chevronRight" :size="14" />
        </li>
        <li aria-current="page">{{ title }}</li>
      </ol>
    </nav>
    <RouterLink v-else-if="backTo" :to="backTo" class="back">
      <AppIcon name="chevronLeft" :size="18" />
      {{ backLabel || t('app.back') }}
    </RouterLink>
    <div class="row-between">
      <div class="titles">
        <h1>{{ title }}</h1>
        <p v-if="subtitle" class="muted">{{ subtitle }}</p>
      </div>
      <div v-if="$slots.actions" class="row"><slot name="actions" /></div>
    </div>
  </header>
</template>

<style scoped>
.page-header {
  display: grid;
  gap: var(--space-2);
}

.titles {
  display: grid;
  gap: var(--space-1);
}

.crumbs ol {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.crumbs li {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.crumbs a {
  color: var(--color-text-muted);
  text-decoration: none;
}

.crumbs a:hover {
  color: var(--color-primary-text);
  text-decoration: underline;
}

.back {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  justify-self: start;
  min-height: var(--touch);
  margin-left: -4px;
  font-size: var(--text-sm);
  font-weight: 600;
  text-decoration: none;
}

.back:hover {
  text-decoration: underline;
}
</style>
