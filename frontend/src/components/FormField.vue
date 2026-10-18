<script setup lang="ts">
/**
 * Label + control + hint + inline error. The slot receives the ids and aria attributes
 * to bind on the input so screen readers announce hints and errors.
 */
import { computed } from 'vue'
import { t } from '@/lib/i18n'

const props = defineProps<{ id: string; label: string; hint?: string; error?: string; optional?: boolean }>()

const describedBy = computed(() => [props.hint ? `${props.id}-hint` : '', props.error ? `${props.id}-error` : ''].filter(Boolean).join(' ') || undefined)
const attrs = computed(() => ({ id: props.id, 'aria-describedby': describedBy.value, 'aria-invalid': props.error ? (true as const) : undefined }))
</script>

<template>
  <div class="field">
    <label :for="id" class="label">
      {{ label }}
      <span v-if="optional" class="optional">({{ t('app.optional') }})</span>
    </label>
    <p v-if="hint" :id="`${id}-hint`" class="hint">{{ hint }}</p>
    <slot :attrs="attrs" />
    <p v-if="error" :id="`${id}-error`" class="error">
      <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zm0 5v5m0 3h.01" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" /></svg>
      {{ error }}
    </p>
  </div>
</template>

<style scoped>
.field {
  display: grid;
  gap: 6px;
  align-content: start;
}

.label {
  font-weight: 600;
  font-size: var(--text-sm);
}

.optional {
  font-weight: 400;
  color: var(--color-text-muted);
}

.hint {
  margin-top: -2px;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.error {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-danger);
}
</style>
