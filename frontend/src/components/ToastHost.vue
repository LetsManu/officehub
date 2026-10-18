<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import { dismissToast, toasts } from '@/lib/toast'
import { t } from '@/lib/i18n'

const ICONS = { success: 'checkCircle', info: 'info', error: 'alert' }
</script>

<template>
  <div class="toasts" role="status" aria-live="polite" aria-atomic="false">
    <div v-for="toast in toasts" :key="toast.id" class="toast" :class="`toast-${toast.kind}`">
      <AppIcon :name="ICONS[toast.kind]" />
      <p>{{ toast.message }}</p>
      <button type="button" class="btn btn-ghost btn-icon" :aria-label="t('app.close')" @click="dismissToast(toast.id)">
        <AppIcon name="close" :size="18" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.toasts {
  position: fixed;
  right: var(--space-4);
  bottom: var(--space-4);
  z-index: 200;
  display: grid;
  gap: var(--space-2);
  width: min(calc(100% - 2rem), 400px);
}

.toast {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-2) var(--space-2) var(--space-4);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  box-shadow: var(--shadow-overlay);
  font-size: var(--text-sm);
}

.toast p {
  flex: 1;
}

.toast-success > .icon {
  color: var(--color-success);
}

.toast-info > .icon {
  color: var(--color-primary-text);
}

.toast-error {
  border-color: var(--color-danger);
}

.toast-error > .icon {
  color: var(--color-danger);
}

.toast .btn {
  color: var(--color-text-muted);
}

@media (max-width: 899px) {
  .toasts {
    left: 50%;
    right: auto;
    transform: translateX(-50%);
  }
}
</style>
