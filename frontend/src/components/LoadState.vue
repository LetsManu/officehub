<script setup lang="ts">
// Shows a loading placeholder or an error with a retry button, otherwise the default slot.
import AppIcon from './AppIcon.vue'
import { t } from '@/lib/i18n'

defineProps<{ loading: boolean; error?: string | null }>()
defineEmits<{ retry: [] }>()
</script>

<template>
  <div v-if="loading" class="card skeleton-card" role="status">
    <span class="visually-hidden">{{ t('app.loading') }}</span>
    <div v-for="n in 4" :key="n" class="skeleton-row" aria-hidden="true">
      <span class="skeleton circle" />
      <span class="lines">
        <span class="skeleton line" :class="{ short: n % 2 === 0 }" />
        <span class="skeleton line tiny" />
      </span>
    </div>
  </div>
  <div v-else-if="error" class="notice notice-danger" role="alert">
    <AppIcon name="alert" />
    <div class="stack-sm">
      <p>{{ error }}</p>
      <div><button type="button" class="btn btn-secondary" @click="$emit('retry')">{{ t('app.retry') }}</button></div>
    </div>
  </div>
  <slot v-else />
</template>

<style scoped>
.skeleton-card {
  display: grid;
  gap: var(--space-4);
}

.skeleton-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.circle {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  flex-shrink: 0;
}

.lines {
  display: grid;
  gap: 8px;
  flex: 1;
}

.line {
  height: 14px;
  width: 70%;
}

.line.short {
  width: 45%;
}

.line.tiny {
  height: 10px;
  width: 30%;
}
</style>
