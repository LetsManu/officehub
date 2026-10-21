<script setup lang="ts">
/** One person in the meeting: their video (or initials), name, muted microphone and raised hand. */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { t } from '@/lib/i18n'
import type { Tile } from '@/lib/meeting'

const props = defineProps<{ tile: Tile; large?: boolean }>()
const video = ref<HTMLVideoElement | null>(null)
const audio = ref<HTMLAudioElement | null>(null)

const initials = computed(() => props.tile.name.split(/\s+/).map((p) => p[0] ?? '').join('').slice(0, 2).toUpperCase() || '?')
const showVideo = computed(() => props.tile.video && !props.tile.videoMuted)

function bind(track: unknown, el: HTMLMediaElement | null, previous: unknown) {
  const p = previous as { detach?: (el: HTMLElement) => void } | null
  if (p && el) p.detach?.(el)
  const tr = track as { attach?: (el: HTMLElement) => void } | null
  if (tr && el) tr.attach?.(el)
}

watch(() => [props.tile.video, video.value] as const, ([track, el], old) => bind(track, el, old?.[0] ?? null), { immediate: true })
// Never play your own microphone back to yourself
watch(() => [props.tile.local ? null : props.tile.audio, audio.value] as const, ([track, el], old) => bind(track, el, old?.[0] ?? null), { immediate: true })

onBeforeUnmount(() => {
  bind(null, video.value, props.tile.video)
  bind(null, audio.value, props.tile.audio)
})
</script>

<template>
  <figure class="tile" :class="{ speaking: tile.speaking, large, screen: tile.screen }">
    <video v-show="showVideo" ref="video" autoplay playsinline muted :class="{ mirror: tile.local && !tile.screen }" />
    <audio v-if="!tile.local" ref="audio" autoplay />
    <div v-if="!showVideo" class="placeholder" aria-hidden="true"><span class="initials">{{ initials }}</span></div>
    <figcaption class="name">
      <AppIcon v-if="tile.audioMuted" name="micOff" :size="14" :label="t('meeting.micMuted')" />
      <span>{{ tile.name || '…' }}<template v-if="tile.local"> ({{ t('meeting.you') }})</template></span>
    </figcaption>
    <span v-if="tile.hand" class="hand" :title="t('meeting.handRaised')"><AppIcon name="hand" :size="18" :label="t('meeting.handRaised')" /></span>
  </figure>
</template>

<style scoped>
.tile {
  position: relative;
  display: grid;
  place-items: center;
  margin: 0;
  overflow: hidden;
  aspect-ratio: 16 / 9;
  border-radius: 14px;
  background: #1f2633;
  box-shadow: inset 0 0 0 2px transparent;
  transition: box-shadow 150ms ease-out;
}

.tile.speaking {
  box-shadow: inset 0 0 0 3px #4ade80;
}

video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  background: #000;
}

.screen video {
  object-fit: contain;
}

.mirror {
  transform: scaleX(-1);
}

.placeholder {
  display: grid;
  place-items: center;
  width: 100%;
  height: 100%;
}

.initials {
  display: grid;
  place-items: center;
  width: 30%;
  max-width: 120px;
  aspect-ratio: 1;
  border-radius: 50%;
  background: #33405a;
  color: #fff;
  font-family: var(--font-heading);
  font-size: clamp(1rem, 3vw, 2.4rem);
  font-weight: 600;
}

.name {
  position: absolute;
  left: 10px;
  bottom: 10px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: calc(100% - 20px);
  padding: 4px 10px;
  border-radius: 99px;
  background: rgb(0 0 0 / 0.55);
  color: #fff;
  font-size: 0.82rem;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.hand {
  position: absolute;
  top: 10px;
  right: 10px;
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: #f59e0b;
  color: #1a1203;
}

@media (prefers-reduced-motion: reduce) {
  .tile {
    transition: none;
  }
}
</style>
