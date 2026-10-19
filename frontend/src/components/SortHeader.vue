<script setup lang="ts">
/** Table column header that sorts the table when clicked. Put it inside a <th :aria-sort="…">. */
import AppIcon from './AppIcon.vue'

defineProps<{ label: string; active: boolean; dir: 'asc' | 'desc' }>()
defineEmits<{ sort: [] }>()
</script>

<template>
  <button type="button" class="sort" :class="{ active }" @click="$emit('sort')">
    {{ label }}
    <AppIcon :name="active && dir === 'desc' ? 'arrowDown' : 'arrowUp'" :size="14" class="sort-icon" />
  </button>
</template>

<style scoped>
.sort {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 32px;
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}

.sort-icon {
  opacity: 0;
  transition: opacity var(--t-fast) ease;
}

.sort:hover .sort-icon,
.sort.active .sort-icon {
  opacity: 1;
}

.sort.active {
  color: var(--color-text);
}
</style>
