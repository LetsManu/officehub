<script setup lang="ts">
/** Round profile picture, or the initials when there is no photo. */
import { computed, ref, watch } from 'vue'
import { photoUrl } from '@/lib/branding'

const props = withDefaults(
  defineProps<{ id: number; name: string; photoVersion?: string | null; size?: number }>(),
  { photoVersion: null, size: 36 },
)

const failed = ref(false)
watch(() => props.photoVersion, () => (failed.value = false))

const src = computed(() => (failed.value ? null : photoUrl(props.id, props.photoVersion)))
const initials = computed(() =>
  props.name
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase(),
)
const sizeStyle = computed(() => ({ width: `${props.size}px`, height: `${props.size}px`, fontSize: `${Math.max(11, props.size * 0.36)}px` }))
</script>

<template>
  <span class="user-avatar" :style="sizeStyle" aria-hidden="true">
    <img v-if="src" :src="src" alt="" loading="lazy" @error="failed = true" />
    <template v-else>{{ initials }}</template>
  </span>
</template>

<style scoped>
.user-avatar {
  display: inline-grid;
  place-items: center;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
  font-weight: 700;
  line-height: 1;
  overflow: hidden;
}

.user-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
</style>
