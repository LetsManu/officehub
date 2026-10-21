<script setup lang="ts">
/** Round profile picture, or the initials when there is no photo; optionally with the presence dot. */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { photoUrl } from '@/lib/branding'
import { t } from '@/lib/i18n'
import { activityText, presence, watchPresence } from '@/lib/presence'

const props = withDefaults(
  defineProps<{ id: number; name: string; photoVersion?: string | null; size?: number; status?: boolean }>(),
  { photoVersion: null, size: 36, status: false },
)

let stop: (() => void) | null = null
watch(
  () => (props.status ? props.id : null),
  (id) => {
    stop?.()
    stop = id ? watchPresence(id) : null
  },
  { immediate: true },
)
onBeforeUnmount(() => stop?.())
const state = computed(() => (props.status ? presence.get(props.id) : undefined))
const stateLabel = computed(() => {
  if (!state.value) return ''
  const activity = activityText(state.value)
  return `${t(`presence.states.${state.value.state}`)}${state.value.text ? ` – ${state.value.text}` : ''}${activity ? ` · ${activity}` : ''}`
})

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
  <span v-if="status" class="avatar-wrap">
    <span class="user-avatar" :style="sizeStyle" aria-hidden="true">
      <img v-if="src" :src="src" alt="" loading="lazy" @error="failed = true" />
      <template v-else>{{ initials }}</template>
    </span>
    <span v-if="state" class="presence-dot" :class="`p-${state.state}`" role="img" :aria-label="stateLabel" :title="stateLabel" />
  </span>
  <span v-else class="user-avatar" :style="sizeStyle" aria-hidden="true">
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

.avatar-wrap {
  position: relative;
  display: inline-grid;
  flex-shrink: 0;
}

.user-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.presence-dot {
  position: absolute;
  right: -1px;
  bottom: -1px;
  width: 34%;
  min-width: 10px;
  max-width: 14px;
  aspect-ratio: 1;
  border: 2px solid var(--color-surface);
  border-radius: 50%;
  background: #9ca3af;
}

/* Colours like in Teams, plus a shape so it does not rely on colour alone */
.p-available {
  background: #16a34a;
}

.p-busy,
.p-in_meeting {
  background: #dc2626;
}

.p-dnd {
  background: linear-gradient(#fff, #fff) center / 56% 20% no-repeat, #dc2626;
}

.p-away {
  background: #f59e0b;
}

.p-ooo {
  background: #9333ea;
}

.p-offline {
  background: var(--color-surface);
  box-shadow: inset 0 0 0 2px #9ca3af;
}
</style>
