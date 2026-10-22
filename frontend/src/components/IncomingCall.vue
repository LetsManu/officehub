<script setup lang="ts">
/**
 * Rings when someone calls from the chat. The open portal asks every few seconds; the tone is made in
 * the browser (no sound file, nothing from outside).
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from './AppIcon.vue'
import UserAvatar from './UserAvatar.vue'
import { api } from '@/lib/api'
import { notifyDesktop, quiet } from '@/lib/desktop'
import { appRing, onAppEvent } from '@/lib/native'
import { t } from '@/lib/i18n'
import type { IncomingCall } from '@/lib/types'

const POLL_MS = 3000
const route = useRoute()
const router = useRouter()
const call = ref<IncomingCall | null>(null)
let timer: number | undefined
let audio: AudioContext | null = null
let ringTimer: number | undefined

async function check() {
  if (route.path.endsWith('/room')) {
    call.value = null // already in a meeting
  } else {
    try {
      const calls = await api.get<IncomingCall[]>('/api/calls/incoming')
      call.value = calls[0] ?? null
    } catch {
      /* try again */
    }
  }
  timer = window.setTimeout(check, document.visibilityState === 'visible' ? POLL_MS : POLL_MS * 2)
}

function tone() {
  try {
    audio ??= new AudioContext()
    const now = audio.currentTime
    for (const [start, freq] of [[0, 880], [0.25, 660], [0.9, 880], [1.15, 660]] as const) {
      const osc = audio.createOscillator()
      const gain = audio.createGain()
      osc.frequency.value = freq
      gain.gain.setValueAtTime(0, now + start)
      gain.gain.linearRampToValueAtTime(0.12, now + start + 0.02)
      gain.gain.linearRampToValueAtTime(0, now + start + 0.22)
      osc.connect(gain).connect(audio.destination)
      osc.start(now + start)
      osc.stop(now + start + 0.25)
    }
  } catch {
    /* the browser blocks sound until the page was clicked once */
  }
}

watch(call, (now, before) => {
  // The Windows app rings with its own window while the portal is hidden in the tray
  if (now && now.meeting_id !== before?.meeting_id) appRing({ meeting_id: now.meeting_id, name: now.caller?.full_name ?? now.title, text: t('call.incoming') })
  if (!now && before) appRing(null)
  if (now && !before) {
    notifyDesktop({ title: now.caller?.full_name ?? now.title, body: t('call.incoming'), link: `/meetings/${now.meeting_id}/room`, tag: `call${now.meeting_id}`, sticky: true })
    // "Do not disturb": the call still shows, but without ringing
    if (!quiet()) {
      tone()
      ringTimer = window.setInterval(tone, 3000)
    }
  }
  if (!now) window.clearInterval(ringTimer)
})

function accept() {
  const c = call.value
  if (!c) return
  call.value = null
  router.push(`/meetings/${c.meeting_id}/room`)
}

async function decline() {
  const c = call.value
  if (!c) return
  call.value = null
  await api.post(`/api/calls/${c.meeting_id}/decline`).catch(() => undefined)
}

// Accepted or declined in the app's own ringing window
const stopAppEvents = onAppEvent((e) => {
  if (!e.call || e.call !== call.value?.meeting_id) return
  if (e.action === 'accept') accept()
  else if (e.action === 'decline') void decline()
})

onMounted(check)
onBeforeUnmount(() => {
  stopAppEvents()
  window.clearTimeout(timer)
  window.clearInterval(ringTimer)
  audio?.close().catch(() => undefined)
})
</script>

<template>
  <Transition name="ring">
    <div v-if="call" class="incoming" role="alertdialog" aria-labelledby="call-title" aria-describedby="call-text">
      <div class="who">
        <span class="ring-avatar">
          <UserAvatar v-if="call.caller" :id="call.caller.id" :name="call.caller.full_name" :photo-version="call.caller.photo_version" :size="48" />
        </span>
        <div>
          <p id="call-title" class="name">{{ call.caller?.full_name ?? call.title }}</p>
          <p id="call-text" class="muted small">{{ t('call.incoming') }}</p>
        </div>
      </div>
      <div class="buttons">
        <button type="button" class="btn decline" @click="decline"><AppIcon name="phoneOff" :size="18" />{{ t('call.decline') }}</button>
        <button type="button" class="btn accept" @click="accept"><AppIcon name="video" :size="18" />{{ t('call.accept') }}</button>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.incoming {
  position: fixed;
  z-index: 1200;
  top: calc(var(--header-height, 64px) + var(--space-3));
  right: var(--space-4);
  display: grid;
  width: min(360px, calc(100vw - 2 * var(--space-4)));
  gap: var(--space-4);
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg, 14px);
  background: var(--color-surface-raised);
  box-shadow: 0 18px 48px rgb(0 0 0 / 24%);
}

.who {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.ring-avatar {
  display: grid;
  border-radius: 50%;
  animation: ring 1.4s ease-out infinite;
}

@keyframes ring {
  0% {
    box-shadow: 0 0 0 0 color-mix(in srgb, var(--color-success) 55%, transparent);
  }

  100% {
    box-shadow: 0 0 0 14px transparent;
  }
}

.name {
  margin: 0;
  font-weight: 700;
}

.who p {
  margin: 0;
}

.buttons {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-2);
}

.accept {
  /* Same green and red in light and dark mode, so the white text stays readable */
  background: #15803d;
  color: #fff;
}

.decline {
  background: #b91c1c;
  color: #fff;
}

.accept:hover,
.decline:hover {
  filter: brightness(1.08);
}

.ring-enter-active,
.ring-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.ring-enter-from,
.ring-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

@media (prefers-reduced-motion: reduce) {
  .ring-avatar {
    animation: none;
  }
}
</style>
