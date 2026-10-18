<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import { t } from '@/lib/i18n'

defineProps<{ title: string; subtitle?: string; backTo?: string; backLabel?: string }>()
</script>

<template>
  <header class="page-header">
    <RouterLink v-if="backTo" :to="backTo" class="back">
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
