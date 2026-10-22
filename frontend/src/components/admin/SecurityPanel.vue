<script setup lang="ts">
// Two-factor rules, who may take part in end-to-end encrypted meetings, and the e-mail test.
import { onMounted, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import { api } from '@/lib/api'
import { errorText, t } from '@/lib/i18n'
import { portalSettings } from '@/lib/portal'
import { publicConfig } from '@/lib/session'
import { showToast } from '@/lib/toast'
import type { PortalSettings, Role } from '@/lib/types'

const ROLES: Role[] = ['admin', 'manager', 'employee']
const required = ref<Role[]>([...(portalSettings.value.require_2fa_roles ?? [])] as Role[])
const saving = ref(false)
const testing = ref(false)
const identityPolicy = ref<'warn' | 'strict'>('warn')

onMounted(async () => {
  identityPolicy.value = (await api.get<{ policy: 'warn' | 'strict' }>('/api/keys/policy').catch(() => ({ policy: 'warn' as const }))).policy
})

async function savePolicy() {
  try {
    await api.put('/api/keys/policy', { policy: identityPolicy.value })
    showToast(t('admin.securitySaved'))
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

watch(portalSettings, (value) => (required.value = [...(value.require_2fa_roles ?? [])] as Role[]))

function toggle(role: Role) {
  required.value = required.value.includes(role) ? required.value.filter((r) => r !== role) : [...required.value, role]
}

async function save() {
  saving.value = true
  try {
    portalSettings.value = await api.put<PortalSettings>('/api/portal/settings', { require_2fa_roles: required.value })
    showToast(t('admin.securitySaved'))
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    saving.value = false
  }
}

async function testMail() {
  testing.value = true
  try {
    const result = await api.post<{ sent_to: string }>('/api/admin/mail-test')
    showToast(t('admin.mailSent', { email: result.sent_to }))
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <div class="security">
    <section class="stack-sm">
      <h3><AppIcon name="lock" :size="18" />{{ t('admin.twoFactorTitle') }}</h3>
      <p class="muted small">{{ t('admin.twoFactorHint') }}</p>
      <div class="stack-sm" role="group" :aria-label="t('admin.twoFactorTitle')">
        <label v-for="role in ROLES" :key="role" class="checkbox">
          <input type="checkbox" :checked="required.includes(role)" @change="toggle(role)" />
          <span>{{ t(`roles.${role}`) }}</span>
        </label>
      </div>
      <div><button type="button" class="btn btn-primary" :disabled="saving" @click="save">{{ t('app.save') }}</button></div>
    </section>

    <section class="stack-sm">
      <h3><AppIcon name="shield" :size="18" />{{ t('admin.identityTitle') }}</h3>
      <p class="muted small">{{ t('admin.identityHint') }}</p>
      <div class="stack-sm" role="radiogroup" :aria-label="t('admin.identityTitle')">
        <label class="checkbox">
          <input v-model="identityPolicy" type="radio" value="warn" @change="savePolicy" />
          <span>{{ t('admin.identityWarn') }}</span>
        </label>
        <label class="checkbox">
          <input v-model="identityPolicy" type="radio" value="strict" @change="savePolicy" />
          <span>{{ t('admin.identityStrict') }}</span>
        </label>
      </div>
    </section>

    <section class="stack-sm">
      <h3><AppIcon name="mail" :size="18" />{{ t('admin.mailTitle') }}</h3>
      <p v-if="publicConfig?.mail_enabled" class="muted small">{{ t('admin.mailOn') }}</p>
      <p v-else class="muted small">{{ t('admin.mailOff') }}</p>
      <div>
        <button type="button" class="btn btn-secondary" :disabled="testing || !publicConfig?.mail_enabled" @click="testMail">
          {{ t('admin.mailTest') }}
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.security {
  display: grid;
  gap: var(--space-6);
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr));
}

h3 {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
</style>
