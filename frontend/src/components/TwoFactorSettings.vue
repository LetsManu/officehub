<script setup lang="ts">
/** Switch two-factor sign-in on or off: scan the QR code, confirm with a code, keep the recovery codes. */
import { computed, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import BaseModal from './BaseModal.vue'
import FormField from './FormField.vue'
import { api } from '@/lib/api'
import { errorText, t } from '@/lib/i18n'
import { portalSettings } from '@/lib/portal'
import { currentUser, setUser } from '@/lib/session'
import { showToast } from '@/lib/toast'
import type { User } from '@/lib/types'

interface Setup {
  secret: string
  otpauth_url: string
  qr_svg: string
}

const setup = ref<Setup | null>(null)
const code = ref('')
const codeError = ref('')
const recovery = ref<string[]>([])
const busy = ref(false)
const disableOpen = ref(false)
const password = ref('')
const passwordError = ref('')

const required = computed(() => (portalSettings.value.require_2fa_roles ?? []).includes(currentUser.value?.role ?? 'employee'))
const qrSrc = computed(() => (setup.value ? `data:image/svg+xml;utf8,${encodeURIComponent(setup.value.qr_svg)}` : ''))
const secretGroups = computed(() => setup.value?.secret.match(/.{1,4}/g)?.join(' ') ?? '')

async function start() {
  busy.value = true
  try {
    setup.value = await api.post<Setup>('/api/profile/2fa/setup')
    code.value = codeError.value = ''
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    busy.value = false
  }
}

async function confirm() {
  codeError.value = code.value.trim() ? '' : t('login.codeRequired')
  if (codeError.value) return
  busy.value = true
  try {
    const result = await api.post<{ recovery_codes: string[] }>('/api/profile/2fa/enable', { code: code.value.trim() })
    recovery.value = result.recovery_codes
    setup.value = null
    setUser(await api.get<User>('/api/profile'))
  } catch (e) {
    codeError.value = errorText(e)
  } finally {
    busy.value = false
  }
}

async function disable() {
  passwordError.value = password.value ? '' : t('validation.password_required')
  if (passwordError.value) return
  busy.value = true
  try {
    setUser(await api.post<User>('/api/profile/2fa/disable', { password: password.value }))
    disableOpen.value = false
    password.value = ''
    showToast(t('security.disabled'))
  } catch (e) {
    passwordError.value = errorText(e)
  } finally {
    busy.value = false
  }
}

function downloadCodes() {
  const blob = new Blob([`OfficeHub – ${t('security.recoveryTitle')}\n\n${recovery.value.join('\n')}\n`], { type: 'text/plain' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = 'officehub-recovery-codes.txt'
  link.click()
  URL.revokeObjectURL(link.href)
}
</script>

<template>
  <div v-if="currentUser" class="stack">
    <div class="status-row">
      <span class="status" :class="currentUser.totp_enabled ? 'on' : 'off'">
        <AppIcon :name="currentUser.totp_enabled ? 'checkCircle' : 'lock'" :size="18" />
        {{ currentUser.totp_enabled ? t('security.on') : t('security.off') }}
      </span>
      <button v-if="!currentUser.totp_enabled && !setup" type="button" class="btn btn-primary" :disabled="busy" @click="start">{{ t('security.enable') }}</button>
      <button v-if="currentUser.totp_enabled" type="button" class="btn btn-ghost" @click="disableOpen = true">{{ t('security.disable') }}</button>
    </div>
    <p class="muted small">{{ t('security.explain') }}</p>
    <div v-if="required && !currentUser.totp_enabled" class="notice notice-warning small" role="status">
      <AppIcon name="alert" :size="18" /><p>{{ t('security.requiredHint') }}</p>
    </div>

    <div v-if="setup" class="setup">
      <ol class="steps">
        <li>{{ t('security.step1') }}</li>
        <li>
          {{ t('security.step2') }}
          <img :src="qrSrc" :alt="t('security.qrAlt')" class="qr" width="200" height="200" />
          <details class="manual">
            <summary class="small">{{ t('security.manual') }}</summary>
            <code class="secret">{{ secretGroups }}</code>
          </details>
        </li>
        <li>
          <form class="row confirm" novalidate @submit.prevent="confirm">
            <FormField id="tfa-code" :label="t('security.step3')" :error="codeError">
              <template #default="{ attrs }"><input v-bind="attrs" v-model="code" class="input code" inputmode="numeric" autocomplete="one-time-code" maxlength="8" /></template>
            </FormField>
            <button type="submit" class="btn btn-primary" :disabled="busy">{{ t('security.confirm') }}</button>
            <button type="button" class="btn btn-ghost" @click="setup = null">{{ t('app.cancel') }}</button>
          </form>
        </li>
      </ol>
    </div>

    <BaseModal :open="recovery.length > 0" :title="t('security.recoveryTitle')" :description="t('security.recoveryText')" hide-actions @close="recovery = []">
      <ul class="codes">
        <li v-for="c in recovery" :key="c"><code>{{ c }}</code></li>
      </ul>
      <div class="form-actions">
        <button type="button" class="btn btn-secondary" @click="downloadCodes"><AppIcon name="download" :size="18" />{{ t('security.downloadCodes') }}</button>
        <button type="button" class="btn btn-primary" @click="recovery = []">{{ t('security.savedCodes') }}</button>
      </div>
    </BaseModal>

    <BaseModal
      :open="disableOpen"
      :title="t('security.disableTitle')"
      :description="t('security.disableText')"
      :confirm-label="t('security.disable')"
      tone="danger"
      :busy="busy"
      @close="disableOpen = false"
      @confirm="disable"
    >
      <FormField id="tfa-password" :label="t('profile.currentPassword')" :error="passwordError">
        <template #default="{ attrs }"><input v-bind="attrs" v-model="password" type="password" class="input" autocomplete="current-password" /></template>
      </FormField>
    </BaseModal>
  </div>
</template>

<style scoped>
.status-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.status {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-weight: 600;
}

.status.on {
  color: var(--color-success);
}

.status.off {
  color: var(--color-text-muted);
}

.steps {
  display: grid;
  gap: var(--space-4);
  margin: 0;
  padding-left: var(--space-5);
}

.qr {
  display: block;
  margin-top: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: #ffffff;
}

.secret {
  display: inline-block;
  margin-top: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--color-neutral-soft);
  font-size: var(--text-md);
  letter-spacing: 0.08em;
  word-break: break-all;
}

.confirm {
  align-items: flex-end;
}

.code {
  width: 160px;
  letter-spacing: 0.25em;
  font-variant-numeric: tabular-nums;
}

.codes {
  list-style: none;
  margin: 0 0 var(--space-4);
  padding: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-2);
}

.codes code {
  display: block;
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--color-neutral-soft);
  text-align: center;
  font-size: var(--text-md);
  letter-spacing: 0.05em;
}
</style>
