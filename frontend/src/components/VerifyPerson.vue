<script setup lang="ts">
/**
 * Check in person that a colleague's key is really theirs: they show the security number (or QR code) from their
 * profile, and it must match the one this browser worked out from their keys. A match is saved as a signed note
 * (identity.ts), so encrypted meetings show them as confirmed on all my devices.
 */
import { onBeforeUnmount, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import BaseModal from './BaseModal.vue'
import { api } from '@/lib/api'
import { checkChain, myDevice, parseQr, securityNumber, Trustbook, type Device, type DeviceRecord } from '@/lib/e2ee/identity'
import { errorText, t } from '@/lib/i18n'
import { currentUser } from '@/lib/session'
import { showToast } from '@/lib/toast'

const props = defineProps<{ open: boolean; userId: string; name: string }>()
const emit = defineEmits<{ close: []; changed: [] }>()

interface BarcodeDetectorLike {
  detect(source: CanvasImageSource): Promise<{ rawValue: string }[]>
}
type DetectorClass = new (options: { formats: string[] }) => BarcodeDetectorLike

const state = ref<'loading' | 'nokey' | 'ready'>('loading')
const root = ref('')
const verified = ref(false)
const device = ref<Device | null>(null)
const scanning = ref(false)
const mismatch = ref(false)
const busy = ref(false)
const video = ref<HTMLVideoElement | null>(null)
let book: Trustbook | null = null
let stream: MediaStream | null = null
let timer = 0
const Detector = (globalThis as unknown as { BarcodeDetector?: DetectorClass }).BarcodeDetector
const canScan = !!Detector && !!navigator.mediaDevices?.getUserMedia

async function load() {
  state.value = 'loading'
  mismatch.value = false
  const me = String(currentUser.value?.id ?? '')
  try {
    const [person, mine, trust] = await Promise.all([
      api.get<{ devices: DeviceRecord[] }>(`/api/keys/users/${props.userId}`),
      myDevice(me),
      Trustbook.load(me),
    ])
    device.value = mine
    book = trust
    const chain = await checkChain(props.userId, person.devices)
    if (!chain) {
      state.value = 'nokey'
      return
    }
    root.value = chain.root
    verified.value = trust.isVerified(props.userId, chain.root)
    state.value = 'ready'
  } catch (e) {
    showToast(errorText(e), 'error')
    emit('close')
  }
}

async function confirm() {
  if (!device.value || !book) return
  busy.value = true
  try {
    await book.confirm(device.value, props.userId, root.value)
    verified.value = true
    showToast(t('keys.verifiedToast', { name: props.name }))
    emit('changed')
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    busy.value = false
  }
}

async function unconfirm() {
  if (!book) return
  await book.unconfirm(props.userId).catch((e) => showToast(errorText(e), 'error'))
  verified.value = false
  emit('changed')
}

async function scan() {
  if (!Detector) return
  mismatch.value = false
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
  } catch {
    showToast(t('keys.cameraFailed'), 'error')
    return
  }
  scanning.value = true
  await new Promise((r) => requestAnimationFrame(r))
  if (!video.value) return stopScan()
  video.value.srcObject = stream
  await video.value.play().catch(() => undefined)
  const detector = new Detector({ formats: ['qr_code'] })
  const look = async () => {
    if (!scanning.value || !video.value) return
    const found = await detector.detect(video.value).catch(() => [])
    for (const code of found) {
      const read = parseQr(code.rawValue)
      if (!read) continue
      stopScan()
      if (read.userId === props.userId && read.fp === root.value) await confirm()
      else mismatch.value = true
      return
    }
    timer = window.setTimeout(look, 250)
  }
  void look()
}

function stopScan() {
  scanning.value = false
  window.clearTimeout(timer)
  stream?.getTracks().forEach((track) => track.stop())
  stream = null
}

function close() {
  stopScan()
  emit('close')
}

watch(
  () => props.open,
  (open) => (open ? void load() : stopScan()),
  { immediate: true },
)
onBeforeUnmount(stopScan)
</script>

<template>
  <BaseModal :open="open" :title="t('keys.verifyTitle', { name })" hide-actions @close="close">
    <p v-if="state === 'loading'" class="muted">{{ t('app.loading') }}</p>
    <p v-else-if="state === 'nokey'" class="muted">{{ t('keys.noKey', { name }) }}</p>
    <div v-else class="stack">
      <p v-if="verified" class="verified"><AppIcon name="checkCircle" :size="18" />{{ t('keys.isVerified', { name }) }}</p>
      <p class="small">{{ t('keys.verifyHowTo', { name }) }}</p>
      <p class="number" aria-live="polite">{{ securityNumber(root) }}</p>
      <p v-if="mismatch" class="mismatch" role="alert"><AppIcon name="alert" :size="18" />{{ t('keys.mismatch', { name }) }}</p>
      <p v-if="device?.pending" class="muted small">{{ t('keys.confirmThisDeviceFirst') }}</p>
      <video v-if="scanning" ref="video" class="scan" muted playsinline :aria-label="t('keys.scanning')"></video>
      <div v-if="!verified" class="actions">
        <button v-if="canScan && !scanning" type="button" class="btn btn-secondary" :disabled="device?.pending" @click="scan">
          <AppIcon name="camera" :size="16" />{{ t('keys.scan') }}
        </button>
        <button v-if="scanning" type="button" class="btn btn-secondary" @click="stopScan">{{ t('app.cancel') }}</button>
        <button type="button" class="btn btn-primary" :disabled="busy || device?.pending" @click="confirm">{{ t('keys.matches') }}</button>
      </div>
      <div v-else class="actions">
        <button type="button" class="btn btn-ghost" @click="unconfirm">{{ t('keys.unverify') }}</button>
        <button type="button" class="btn btn-primary" @click="close">{{ t('app.close') }}</button>
      </div>
    </div>
  </BaseModal>
</template>

<style scoped>
.number {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 1.25rem;
  letter-spacing: 0.06em;
  word-spacing: 0.4em;
  line-height: 1.6;
}
.verified,
.mismatch {
  display: flex;
  gap: var(--space-2);
  align-items: center;
  font-weight: 600;
}
.verified {
  color: var(--color-success, #157347);
}
.mismatch {
  color: var(--color-danger, #b42318);
}
.scan {
  width: 100%;
  max-height: 260px;
  border-radius: var(--radius-md);
  background: #000;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  justify-content: flex-end;
}
</style>
