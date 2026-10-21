<script setup lang="ts">
/** One person in the meeting: their video (or initials), name, muted microphone, raised hand and reactions. */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { t } from '@/lib/i18n'
import { speakerId, type Tile } from '@/lib/meeting'

const props = defineProps<{ tile: Tile; large?: boolean; pinned?: boolean; spotlight?: boolean }>()
const emit = defineEmits<{ pin: [] }>()
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

// The loudspeaker chosen in the meeting (browsers that support choosing one)
watch(() => [speakerId.value, audio.value] as const, ([id, el]) => {
  const target = el as (HTMLAudioElement & { setSinkId?: (id: string) => Promise<void> }) | null
  target?.setSinkId?.(id).catch(() => undefined)
}, { immediate: true })

onBeforeUnmount(() => {
  bind(null, video.value, props.tile.video)
  bind(null, audio.value, props.tile.audio)
})
</script>

<template>
  <figure class="tile" :class="{ speaking: tile.speaking, large, screen: tile.screen }" :data-tile="tile.id">
    <video v-show="showVideo" ref="video" autoplay playsinline muted :class="{ mirror: tile.local && !tile.screen }" />
    <audio v-if="!tile.local" ref="audio" autoplay />
    <div v-if="!showVideo" class="placeholder" aria-hidden="true"><span class="initials">{{ initials }}</span></div>
    <figcaption class="name">
      <AppIcon v-if="tile.audioMuted" name="micOff" :size="14" :label="t('meeting.micMuted')" />
      <span>{{ tile.name || '…' }}<template v-if="tile.local"> ({{ t('meeting.you') }})</template></span>
    </figcaption>
    <span v-if="tile.hand" class="hand" :title="t('meeting.handRaised')"><AppIcon name="hand" :size="18" :label="t('meeting.handRaised')" /></span>
    <span v-if="tile.reaction" :key="tile.reaction" class="reaction" role="img" :aria-label="t('meeting.reacted', { name: tile.name, emoji: tile.reaction })">{{ tile.reaction }}</span>
    <span v-if="spotlight || tile.mod" class="badges">
      <span v-if="spotlight" class="badge">{{ t('meeting.spotlightBadge') }}</span>
      <span v-if="tile.mod" class="badge muted-badge">{{ t('meeting.leadBadge') }}</span>
    </span>
    <button type="button" class="pin" :class="{ on: pinned }" :aria-pressed="!!pinned" :aria-label="pinned ? t('meeting.unpinTile', { name: tile.name }) : t('meeting.pinTile', { name: tile.name })" :title="pinned ? t('meeting.unpinTile', { name: tile.name }) : t('meeting.pinTile', { name: tile.name })" @click="emit('pin')"><AppIcon name="pin" :size="16" /></button>
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

.reaction {
  position: absolute;
  bottom: 44px;
  left: 50%;
  font-size: clamp(2rem, 5vw, 3.4rem);
  line-height: 1;
  transform: translateX(-50%);
  animation: rise 4s ease-out forwards;
  pointer-events: none;
}

@keyframes rise {
  0% {
    opacity: 0;
    transform: translate(-50%, 20px) scale(0.6);
  }

  12% {
    opacity: 1;
    transform: translate(-50%, 0) scale(1);
  }

  80% {
    opacity: 1;
  }

  100% {
    opacity: 0;
    transform: translate(-50%, -60px);
  }
}

.badges {
  position: absolute;
  top: 10px;
  left: 10px;
  display: flex;
  gap: 6px;
}

.badge {
  padding: 3px 9px;
  border-radius: 99px;
  background: #2563eb;
  color: #fff;
  font-size: 0.72rem;
  font-weight: 700;
}

.muted-badge {
  background: rgb(0 0 0 / 0.55);
}

.pin {
  position: absolute;
  top: 8px;
  right: 50px;
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border: 0;
  border-radius: 50%;
  background: rgb(0 0 0 / 0.55);
  color: #fff;
  cursor: pointer;
  opacity: 0;
  transition: opacity 150ms ease-out;
}

.tile:not(:has(.hand)) .pin {
  right: 10px;
}

.tile:hover .pin,
.pin:focus-visible,
.pin.on {
  opacity: 1;
}

.pin.on {
  background: #2563eb;
}

@media (hover: none) {
  .pin {
    opacity: 0.8;
  }
}

@media (prefers-reduced-motion: reduce) {
  .tile {
    transition: none;
  }

  .reaction {
    animation: none;
  }
}
</style>
