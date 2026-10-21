<script setup lang="ts">
/** Switch notifications on the computer and the sound on or off (stored in this browser). */
import { ref } from 'vue'
import AppIcon from './AppIcon.vue'
import { chime, desktopPrefs, desktopSupported, enableDesktop, saveDesktopPrefs } from '@/lib/desktop'
import { t } from '@/lib/i18n'
import { showToast } from '@/lib/toast'

defineProps<{ compact?: boolean }>()
const blocked = ref(desktopSupported && Notification.permission === 'denied')

async function toggleDesktop() {
  if (desktopPrefs.desktop) {
    desktopPrefs.desktop = false
    saveDesktopPrefs()
    return
  }
  const ok = await enableDesktop()
  blocked.value = desktopSupported && Notification.permission === 'denied'
  showToast(ok ? t('desktop.enabled') : t('desktop.blocked'), ok ? 'success' : 'info')
}

function toggleSound() {
  desktopPrefs.sound = !desktopPrefs.sound
  saveDesktopPrefs()
  if (desktopPrefs.sound) chime('message')
}
</script>

<template>
  <div v-if="compact" class="prompt card">
    <AppIcon name="bell" />
    <p>{{ t('desktop.prompt') }}</p>
    <button type="button" class="btn btn-primary" @click="toggleDesktop">{{ t('desktop.turnOn') }}</button>
  </div>
  <section v-else class="card stack" aria-labelledby="desktop-title">
    <h2 id="desktop-title" class="h3">{{ t('desktop.title') }}</h2>
    <p class="muted small">{{ t('desktop.hint') }}</p>
    <label class="checkbox">
      <input type="checkbox" :checked="desktopPrefs.desktop" :disabled="!desktopSupported" @change="toggleDesktop" />
      <span>{{ t('desktop.popups') }}</span>
    </label>
    <p v-if="blocked" class="notice notice-warning small">{{ t('desktop.blockedHint') }}</p>
    <label class="checkbox">
      <input type="checkbox" :checked="desktopPrefs.sound" @change="toggleSound" />
      <span>{{ t('desktop.sound') }}</span>
    </label>
    <p class="muted small">{{ t('desktop.dndHint') }}</p>
  </section>
</template>

<style scoped>
.prompt {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.prompt p {
  flex: 1;
  min-width: 200px;
  margin: 0;
}
</style>
