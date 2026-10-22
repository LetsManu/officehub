<script setup lang="ts">
/**
 * Company login: sign in with the company's own login server (Authentik, Keycloak … via OpenID Connect).
 * Shows the address to register there, and the few values to copy back.
 */
import { onMounted, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import FormField from '@/components/FormField.vue'
import { api } from '@/lib/api'
import { errorText, t } from '@/lib/i18n'
import { loadConfig, publicConfig } from '@/lib/session'
import { showToast } from '@/lib/toast'

interface SsoSettings {
  enabled: boolean
  issuer: string
  client_id: string
  client_secret: string
  label: string
  create_users: boolean
  trust_email: boolean
  admin_group: string
  manager_group: string
  hr_group: string
  servicedesk_group: string
  teamlead_group: string
  has_secret?: boolean
}

const form = ref<SsoSettings | null>(null)
const hasSecret = ref(false)
const saving = ref(false)
const error = ref('')
const callback = `${window.location.origin}/api/auth/sso/callback`

async function load() {
  const data = await api.get<SsoSettings>('/api/admin/sso')
  hasSecret.value = Boolean(data.has_secret)
  form.value = data
}

async function save() {
  if (!form.value) return
  saving.value = true
  error.value = ''
  try {
    const data = await api.put<SsoSettings>('/api/admin/sso', form.value)
    hasSecret.value = Boolean(data.has_secret)
    form.value = data
    publicConfig.value = null
    await loadConfig()
    showToast(t('sso.saved'))
  } catch (e) {
    error.value = errorText(e)
  } finally {
    saving.value = false
  }
}

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    showToast(t('files.copied'))
  } catch {
    window.prompt(t('files.copyThis'), text)
  }
}

onMounted(() => load().catch((e) => showToast(errorText(e), 'error')))
</script>

<template>
  <form v-if="form" class="stack" novalidate @submit.prevent="save">
    <p class="muted">{{ t('sso.intro') }}</p>
    <ol class="steps small">
      <li>{{ t('sso.step1') }}</li>
      <li>
        {{ t('sso.step2') }}
        <span class="address"><code>{{ callback }}</code><button type="button" class="btn btn-ghost btn-icon" :aria-label="t('files.copy')" @click="copy(callback)"><AppIcon name="clipboard" :size="16" /></button></span>
      </li>
      <li>{{ t('sso.step3') }}</li>
    </ol>

    <div v-if="error" class="notice notice-danger small" role="alert">{{ error }}</div>
    <label class="checkbox">
      <input v-model="form.enabled" type="checkbox" />
      <span><strong>{{ t('sso.enabled') }}</strong></span>
    </label>
    <div class="fields">
      <FormField id="sso-issuer" :label="t('sso.issuer')" :hint="t('sso.issuerHint')">
        <template #default="{ attrs }"><input v-bind="attrs" v-model="form.issuer" class="input" type="url" placeholder="https://auth.example.com/application/o/officehub/" autocomplete="off" /></template>
      </FormField>
      <FormField id="sso-label" :label="t('sso.label')" :hint="t('sso.labelHint')">
        <template #default="{ attrs }"><input v-bind="attrs" v-model="form.label" class="input" maxlength="60" placeholder="Authentik" autocomplete="off" /></template>
      </FormField>
      <FormField id="sso-client" :label="t('sso.clientId')">
        <template #default="{ attrs }"><input v-bind="attrs" v-model="form.client_id" class="input" autocomplete="off" /></template>
      </FormField>
      <FormField id="sso-secret" :label="t('sso.clientSecret')" :hint="hasSecret ? t('sso.secretKept') : ''">
        <template #default="{ attrs }"><input v-bind="attrs" v-model="form.client_secret" class="input" type="password" autocomplete="new-password" /></template>
      </FormField>
    </div>

    <fieldset class="stack-sm options">
      <legend class="label">{{ t('sso.people') }}</legend>
      <label class="checkbox">
        <input v-model="form.create_users" type="checkbox" />
        <span>{{ t('sso.createUsers') }}</span>
      </label>
      <label class="checkbox">
        <input v-model="form.trust_email" type="checkbox" />
        <span>{{ t('sso.trustEmail') }}<span class="muted small block">{{ t('sso.trustEmailHint') }}</span></span>
      </label>
    </fieldset>
    <div class="fields">
      <FormField id="sso-admins" :label="t('sso.adminGroup')" :hint="t('sso.groupHint')">
        <template #default="{ attrs }"><input v-bind="attrs" v-model="form.admin_group" class="input" autocomplete="off" /></template>
      </FormField>
      <FormField id="sso-hr" :label="t('sso.hrGroup')">
        <template #default="{ attrs }"><input v-bind="attrs" v-model="form.hr_group" class="input" autocomplete="off" /></template>
      </FormField>
      <FormField id="sso-managers" :label="t('sso.managerGroup')">
        <template #default="{ attrs }"><input v-bind="attrs" v-model="form.manager_group" class="input" autocomplete="off" /></template>
      </FormField>
      <FormField id="sso-servicedesk" :label="t('sso.servicedeskGroup')">
        <template #default="{ attrs }"><input v-bind="attrs" v-model="form.servicedesk_group" class="input" autocomplete="off" /></template>
      </FormField>
      <FormField id="sso-teamleads" :label="t('sso.teamleadGroup')">
        <template #default="{ attrs }"><input v-bind="attrs" v-model="form.teamlead_group" class="input" autocomplete="off" /></template>
      </FormField>
    </div>
    <div><button type="submit" class="btn btn-primary" :disabled="saving">{{ saving ? t('sso.checking') : t('app.save') }}</button></div>
  </form>
</template>

<style scoped>
.fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  align-items: end;
  gap: var(--space-4);
}

.steps {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding-left: var(--space-5);
}

.address {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: 4px;
}

code {
  overflow-wrap: anywhere;
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  background: var(--color-surface-muted);
  font-size: 0.85rem;
}

.options {
  margin: 0;
  padding: 0;
  border: 0;
}

.label {
  margin-bottom: var(--space-2);
  font-weight: 600;
}

.block {
  display: block;
}
</style>
