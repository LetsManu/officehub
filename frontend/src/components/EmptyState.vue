<script setup lang="ts">
import AppIcon from './AppIcon.vue'

defineProps<{ icon?: string; message: string; actionLabel?: string; actionTo?: string }>()
defineEmits<{ action: [] }>()
</script>

<template>
  <div class="empty">
    <span class="empty-icon"><AppIcon :name="icon ?? 'inbox'" :size="24" /></span>
    <p>{{ message }}</p>
    <RouterLink v-if="actionLabel && actionTo" :to="actionTo" class="btn btn-primary">{{ actionLabel }}</RouterLink>
    <button v-else-if="actionLabel" type="button" class="btn btn-secondary" @click="$emit('action')">{{ actionLabel }}</button>
  </div>
</template>

<style scoped>
.empty {
  display: grid;
  justify-items: center;
  gap: var(--space-3);
  padding: var(--space-6) var(--space-4);
  text-align: center;
  color: var(--color-text-muted);
}

.empty p {
  max-width: 44ch;
}

.empty-icon {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: var(--color-neutral-soft);
  color: var(--color-text-muted);
}
</style>
