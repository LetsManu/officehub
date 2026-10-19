<script setup lang="ts">
/** Choose a profile photo. The browser crops it to a square and scales it down before uploading. */
import { ref } from 'vue'
import AppIcon from './AppIcon.vue'
import UserAvatar from './UserAvatar.vue'
import { api } from '@/lib/api'
import { errorText, t } from '@/lib/i18n'
import { currentUser, setUser } from '@/lib/session'
import { showToast } from '@/lib/toast'
import type { User } from '@/lib/types'

const SIZE = 320
const busy = ref(false)
const input = ref<HTMLInputElement | null>(null)

function squareJpeg(file: File): Promise<Blob> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      const side = Math.min(img.naturalWidth, img.naturalHeight)
      const canvas = document.createElement('canvas')
      canvas.width = canvas.height = SIZE
      const ctx = canvas.getContext('2d')
      if (!ctx) return reject(new Error('canvas'))
      ctx.drawImage(img, (img.naturalWidth - side) / 2, (img.naturalHeight - side) / 2, side, side, 0, 0, SIZE, SIZE)
      URL.revokeObjectURL(url)
      canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('blob'))), 'image/jpeg', 0.88)
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('image'))
    }
    img.src = url
  })
}

async function onFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  busy.value = true
  try {
    const blob = await squareJpeg(file)
    const data = new FormData()
    data.append('file', blob, 'photo.jpg')
    setUser(await api.post<User>('/api/profile/photo', data))
    showToast(t('profile.photoSaved'))
  } catch (e) {
    showToast(e instanceof Error && ['image', 'canvas', 'blob'].includes(e.message) ? t('profile.photoInvalid') : errorText(e), 'error')
  } finally {
    busy.value = false
    if (input.value) input.value.value = ''
  }
}

async function remove() {
  busy.value = true
  try {
    setUser(await api.delete<User>('/api/profile/photo'))
    showToast(t('profile.photoRemoved'))
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div v-if="currentUser" class="photo-picker">
    <UserAvatar :id="currentUser.id" :name="currentUser.full_name" :photo-version="currentUser.photo_version" :size="88" />
    <div class="stack-sm">
      <p class="label-text">{{ t('profile.photo') }}</p>
      <p class="muted small">{{ t('profile.photoHint') }}</p>
      <div class="row actions">
        <label class="btn btn-secondary" :class="{ disabled: busy }">
          <AppIcon name="camera" :size="18" />{{ currentUser.photo_version ? t('profile.photoChange') : t('profile.photoUpload') }}
          <input ref="input" type="file" accept="image/png,image/jpeg" class="visually-hidden" :disabled="busy" @change="onFile" />
        </label>
        <button v-if="currentUser.photo_version" type="button" class="btn btn-ghost" :disabled="busy" @click="remove">{{ t('profile.photoRemove') }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.photo-picker {
  display: flex;
  align-items: center;
  gap: var(--space-5);
}

.label-text {
  font-weight: 600;
}

.actions {
  gap: var(--space-2);
}

.btn.disabled {
  opacity: 0.6;
  pointer-events: none;
}

.btn:focus-within {
  outline: 3px solid var(--color-focus);
  outline-offset: 2px;
}
</style>
