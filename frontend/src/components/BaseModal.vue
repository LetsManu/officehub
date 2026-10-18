<script setup lang="ts">
/**
 * Dialog for important or irreversible actions.
 * Has a title, short explanation, primary + cancel actions, a close button,
 * Escape support, a focus trap and returns focus to the element that opened it.
 */
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { trapTab, focusableElements } from '@/lib/focus'
import { t } from '@/lib/i18n'

const props = withDefaults(
  defineProps<{
    open: boolean
    title: string
    description?: string
    confirmLabel?: string
    cancelLabel?: string
    tone?: 'primary' | 'danger'
    busy?: boolean
    hideActions?: boolean
    wide?: boolean
  }>(),
  { description: '', confirmLabel: '', cancelLabel: '', tone: 'primary', busy: false, hideActions: false, wide: false },
)

const emit = defineEmits<{ close: []; confirm: [] }>()

const dialog = ref<HTMLElement | null>(null)
let returnFocusTo: HTMLElement | null = null
const titleId = `modal-title-${Math.random().toString(36).slice(2, 9)}`
const descriptionId = `${titleId}-desc`

function onKeydown(event: KeyboardEvent) {
  if (!dialog.value) return
  if (event.key === 'Escape') {
    event.stopPropagation()
    if (!props.busy) emit('close')
    return
  }
  trapTab(event, dialog.value)
}

watch(
  () => props.open,
  async (open) => {
    if (open) {
      returnFocusTo = document.activeElement as HTMLElement | null
      document.body.style.overflow = 'hidden'
      await nextTick()
      if (!dialog.value) return
      // Focus the first form field; otherwise the safe default button (Cancel for destructive dialogs).
      const field = dialog.value.querySelector<HTMLElement>('input, select, textarea')
      ;(field ?? focusableElements(dialog.value).find((el) => el.dataset.autofocus !== undefined) ?? dialog.value).focus()
    } else {
      document.body.style.overflow = ''
      returnFocusTo?.focus?.()
      returnFocusTo = null
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  if (props.open) {
    document.body.style.overflow = ''
    returnFocusTo?.focus?.()
  }
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="backdrop" @mousedown.self="!busy && emit('close')">
      <div
        ref="dialog"
        class="dialog"
        :class="{ wide }"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        :aria-describedby="description ? descriptionId : undefined"
        tabindex="-1"
        @keydown="onKeydown"
      >
        <div class="dialog-header">
          <h2 :id="titleId">{{ title }}</h2>
          <button type="button" class="btn btn-ghost btn-icon close" :aria-label="t('app.close')" :disabled="busy" @click="emit('close')">
            <AppIcon name="close" />
          </button>
        </div>
        <p v-if="description" :id="descriptionId" class="muted description">{{ description }}</p>
        <div class="dialog-body">
          <slot />
        </div>
        <div v-if="!hideActions" class="dialog-actions">
          <button type="button" class="btn btn-secondary" :disabled="busy" :data-autofocus="tone === 'danger' ? '' : undefined" @click="emit('close')">
            {{ cancelLabel || t('app.cancel') }}
          </button>
          <button
            type="button"
            class="btn"
            :class="tone === 'danger' ? 'btn-danger' : 'btn-primary'"
            :disabled="busy"
            :data-autofocus="tone === 'danger' ? undefined : ''"
            @click="emit('confirm')"
          >
            {{ busy ? t('app.saving') : confirmLabel }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: grid;
  place-items: center;
  padding: var(--space-4);
  background: var(--backdrop);
}

.dialog {
  width: min(100%, 480px);
  max-height: calc(100vh - 2rem);
  overflow-y: auto;
  padding: var(--space-5);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  box-shadow: var(--shadow-overlay);
}

.dialog.wide {
  width: min(100%, 640px);
}

.dialog:focus-visible {
  outline: none;
}

.dialog-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
}

.dialog-header h2 {
  padding-top: 10px;
  font-size: var(--text-xl);
}

.close {
  margin: -4px -8px 0 0;
  color: var(--color-text-muted);
}

.description {
  margin-top: var(--space-2);
}

.dialog-body:not(:empty) {
  margin-top: var(--space-4);
}

.dialog-actions {
  display: flex;
  flex-wrap: wrap-reverse;
  justify-content: flex-end;
  gap: var(--space-3);
  margin-top: var(--space-5);
}

@media (max-width: 480px) {
  .dialog-actions .btn {
    flex: 1 1 100%;
  }
}
</style>
