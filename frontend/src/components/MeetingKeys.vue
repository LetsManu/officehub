<script setup lang="ts">
/**
 * "Encrypted meetings" in the profile: my security number (with QR code) for colleagues to check, and my devices.
 * A new device waits until one of my confirmed devices confirms it (both show the same code); without any
 * confirmed device left I can start anew, and colleagues then see that my key changed.
 */
import { computed, onMounted, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import BaseModal from './BaseModal.vue'
import QrCode from './QrCode.vue'
import { api } from '@/lib/api'
import {
  approve,
  checkChain,
  deviceCode,
  identitySupported,
  myDevice,
  qrText,
  securityNumber,
  startAnew,
  type Device,
  type DeviceRecord,
  type MyKeys,
} from '@/lib/e2ee/identity'
import { errorText, formatDate, t } from '@/lib/i18n'
import { currentUser } from '@/lib/session'
import { refreshSummary } from '@/lib/summary'
import { showToast } from '@/lib/toast'

const supported = identitySupported()
const me = computed(() => String(currentUser.value?.id ?? ''))
const device = ref<Device | null>(null)
const devices = ref<DeviceRecord[]>([])
const root = ref('')
const ownCode = ref('')
const approving = ref<{ device: DeviceRecord; code: string } | null>(null)
const removing = ref<DeviceRecord | null>(null)
const restarting = ref(false)
const busy = ref(false)

async function load() {
  if (!supported || !me.value) return
  try {
    device.value = await myDevice(me.value, true)
    const mine = await api.get<MyKeys>('/api/keys/me')
    devices.value = mine.devices
    root.value = (await checkChain(me.value, mine.devices))?.root ?? ''
    ownCode.value = device.value?.pending ? await deviceCode(device.value.publicKey) : ''
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

function status(d: DeviceRecord): string {
  if (d.root) return t('keys.deviceFirst')
  return d.pending ? t('keys.deviceWaiting') : t('keys.deviceConfirmed')
}

async function askApprove(d: DeviceRecord) {
  approving.value = { device: d, code: await deviceCode(d.public_key) }
}

async function doApprove() {
  if (!approving.value || !device.value) return
  busy.value = true
  try {
    await approve(device.value, approving.value.device)
    showToast(t('keys.approved'))
    approving.value = null
    await load()
    void refreshSummary()
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    busy.value = false
  }
}

async function doRemove() {
  if (!removing.value) return
  busy.value = true
  try {
    await api.delete(`/api/keys/devices/${removing.value.id}`)
    removing.value = null
    await load()
    void refreshSummary()
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    busy.value = false
  }
}

async function doRestart() {
  busy.value = true
  try {
    await startAnew(me.value)
    restarting.value = false
    showToast(t('keys.restarted'))
    await load()
    void refreshSummary()
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <section v-if="supported" id="keys" class="card stack" aria-labelledby="keys-title">
    <h2 id="keys-title">{{ t('keys.title') }}</h2>
    <p class="muted">{{ t('keys.intro') }}</p>

    <div v-if="device?.pending" class="pending-box stack-sm" role="status">
      <p><strong>{{ t('keys.thisPending') }}</strong></p>
      <p class="small">{{ t('keys.thisPendingHint') }}</p>
      <p class="code">{{ ownCode }}</p>
      <div><button type="button" class="btn btn-ghost" @click="restarting = true">{{ t('keys.restart') }}</button></div>
    </div>

    <div v-if="root" class="number-box">
      <QrCode :text="qrText(me, root)" :label="t('keys.qrLabel')" />
      <div class="stack-sm">
        <h3 class="small">{{ t('keys.myNumber') }}</h3>
        <p class="number">{{ securityNumber(root) }}</p>
        <p class="muted small">{{ t('keys.myNumberHint') }}</p>
      </div>
    </div>

    <h3 class="small">{{ t('keys.devices') }}</h3>
    <ul class="devices">
      <li v-for="d in devices" :key="d.id">
        <AppIcon :name="d.pending ? 'alert' : 'shield'" :size="18" />
        <div class="grow">
          <p>
            <strong>{{ d.name || t('keys.unnamed') }}</strong>
            <span v-if="d.id === device?.id" class="muted small"> · {{ t('keys.thisDevice') }}</span>
          </p>
          <p class="muted small">{{ status(d) }} · {{ formatDate(d.created_at ?? null) }}</p>
        </div>
        <button v-if="d.pending && device && !device.pending" type="button" class="btn btn-primary" @click="askApprove(d)">{{ t('keys.approve') }}</button>
        <button v-if="!d.root && d.id !== device?.id" type="button" class="btn btn-ghost" :aria-label="t('keys.remove')" @click="removing = d">
          <AppIcon name="trash" :size="16" />
        </button>
      </li>
    </ul>

    <BaseModal
      :open="!!approving"
      :title="t('keys.approveTitle')"
      :description="t('keys.approveHint')"
      :confirm-label="t('keys.approveConfirm')"
      :busy="busy"
      @close="approving = null"
      @confirm="doApprove"
    >
      <p class="code">{{ approving?.code }}</p>
    </BaseModal>
    <BaseModal
      :open="!!removing"
      :title="t('keys.removeTitle')"
      :description="t('keys.removeHint', { name: removing?.name ?? '' })"
      :confirm-label="t('keys.remove')"
      tone="danger"
      :busy="busy"
      @close="removing = null"
      @confirm="doRemove"
    />
    <BaseModal
      :open="restarting"
      :title="t('keys.restartTitle')"
      :description="t('keys.restartHint')"
      :confirm-label="t('keys.restartConfirm')"
      tone="danger"
      :busy="busy"
      @close="restarting = false"
      @confirm="doRestart"
    />
  </section>
</template>

<style scoped>
.pending-box {
  padding: var(--space-4);
  border-radius: var(--radius-md);
  background: var(--color-warning-soft);
}
.code {
  font-family: ui-monospace, monospace;
  font-size: 1.75rem;
  letter-spacing: 0.08em;
}
.number-box {
  display: grid;
  grid-template-columns: minmax(0, 180px) minmax(0, 1fr);
  gap: var(--space-5);
  align-items: center;
}
.number {
  font-family: ui-monospace, monospace;
  font-size: 1.2rem;
  word-spacing: 0.4em;
  line-height: 1.6;
}
.devices {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-2);
}
.devices li {
  display: flex;
  gap: var(--space-3);
  align-items: center;
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--color-border);
}
.grow {
  flex: 1;
  min-width: 0;
}
@media (max-width: 560px) {
  .number-box {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
