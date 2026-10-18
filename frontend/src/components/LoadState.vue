<script setup lang="ts">
// Shows a loading line or an error with a retry button, otherwise the default slot.
import AppIcon from './AppIcon.vue'
import { t } from '@/lib/i18n'

defineProps<{ loading: boolean; error?: string | null }>()
defineEmits<{ retry: [] }>()
</script>

<template>
  <div v-if="loading" class="state muted" role="status">
    <span class="spinner" aria-hidden="true" />
    {{ t('app.loading') }}
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
.state {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-5);
}

.spinner {
  width: 18px;
  height: 18px;
  border: 2px solid var(--color-border-strong);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
