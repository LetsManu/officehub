<script setup lang="ts">
import { reactive, ref, watchEffect } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import FormField from '@/components/FormField.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api } from '@/lib/api'
import { currentUser, setUser } from '@/lib/session'
import { errorText, t } from '@/lib/i18n'
import { applyTheme, theme } from '@/lib/theme'
import { showToast } from '@/lib/toast'
import type { Language, User } from '@/lib/types'

const form = reactive({ first_name: '', last_name: '', department: '', job_title: '', office_location: '', language: 'de' as Language })
const errors = reactive({ first_name: '', last_name: '' })
const saving = ref(false)
const formError = ref('')

const pw = reactive({ current: '', next: '', confirm: '' })
const pwErrors = reactive({ current: '', next: '', confirm: '' })
const pwSaving = ref(false)

watchEffect(() => {
  const u = currentUser.value
  if (u) Object.assign(form, { first_name: u.first_name, last_name: u.last_name, department: u.department, job_title: u.job_title, office_location: u.office_location, language: u.language })
})

async function save() {
  errors.first_name = form.first_name.trim() ? '' : t('validation.first_name_required')
  errors.last_name = form.last_name.trim() ? '' : t('validation.last_name_required')
  if (errors.first_name || errors.last_name) return
  saving.value = true
  formError.value = ''
  try {
    setUser(await api.patch<User>('/api/profile', { ...form }))
    showToast(t('profile.saved'))
  } catch (e) {
    formError.value = errorText(e)
  } finally {
    saving.value = false
  }
}

async function changePassword() {
  pwErrors.current = pw.current ? '' : t('login.passwordRequired')
  pwErrors.next = pw.next.length >= 8 ? '' : t('validation.password_short')
  pwErrors.confirm = pw.next === pw.confirm ? '' : t('validation.password_mismatch')
  if (pwErrors.current || pwErrors.next || pwErrors.confirm) return
  pwSaving.value = true
  try {
    await api.post('/api/profile/password', { current_password: pw.current, new_password: pw.next })
    Object.assign(pw, { current: '', next: '', confirm: '' })
    showToast(t('profile.passwordChanged'))
  } catch (e) {
    pwErrors.current = errorText(e)
  } finally {
    pwSaving.value = false
  }
}
</script>

<template>
  <div class="page profile-page">
    <PageHeader :title="t('profile.title')" :subtitle="t('profile.subtitle')" />

    <form class="card stack" novalidate @submit.prevent="save">
      <h2>{{ t('profile.personal') }}</h2>
      <div v-if="formError" class="notice notice-danger" role="alert"><AppIcon name="alert" /><p>{{ formError }}</p></div>
      <div class="grid-2">
        <FormField id="p-first" :label="t('profile.firstName')" :error="errors.first_name">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.first_name" class="input" maxlength="60" autocomplete="given-name" /></template>
        </FormField>
        <FormField id="p-last" :label="t('profile.lastName')" :error="errors.last_name">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.last_name" class="input" maxlength="60" autocomplete="family-name" /></template>
        </FormField>
        <FormField id="p-department" :label="t('profile.department')" optional>
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.department" class="input" maxlength="80" /></template>
        </FormField>
        <FormField id="p-job" :label="t('profile.jobTitle')" optional>
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.job_title" class="input" maxlength="80" autocomplete="organization-title" /></template>
        </FormField>
        <FormField id="p-office" :label="t('profile.office')" optional>
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.office_location" class="input" maxlength="80" /></template>
        </FormField>
        <FormField id="p-language" :label="t('profile.language')">
          <template #default="{ attrs }">
            <select v-bind="attrs" v-model="form.language" class="select">
              <option value="de" lang="de">Deutsch</option>
              <option value="en" lang="en">English</option>
            </select>
          </template>
        </FormField>
      </div>

      <dl class="facts readonly">
        <div><dt>{{ t('profile.email') }}</dt><dd>{{ currentUser?.email }}</dd></div>
        <div><dt>{{ t('profile.role') }}</dt><dd>{{ currentUser ? t(`roles.${currentUser.role}`) : '' }}</dd></div>
      </dl>
      <p class="muted small">{{ t('profile.readonlyHint') }}</p>

      <div class="form-actions">
        <button type="submit" class="btn btn-primary" :disabled="saving">{{ saving ? t('app.saving') : t('app.save') }}</button>
      </div>
    </form>

    <details class="disclosure">
      <summary>{{ t('profile.appearance') }}</summary>
      <div class="disclosure-body">
        <div class="segmented" role="group" :aria-label="t('profile.theme')">
          <button type="button" :aria-pressed="theme === 'light'" @click="applyTheme('light')"><AppIcon name="sun" :size="16" /> {{ t('app.lightMode') }}</button>
          <button type="button" :aria-pressed="theme === 'dark'" @click="applyTheme('dark')"><AppIcon name="moon" :size="16" /> {{ t('app.darkMode') }}</button>
        </div>
      </div>
    </details>

    <details class="disclosure">
      <summary>{{ t('profile.password') }}</summary>
      <form class="disclosure-body stack" novalidate @submit.prevent="changePassword">
        <FormField id="pw-current" :label="t('profile.currentPassword')" :error="pwErrors.current">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="pw.current" class="input" type="password" autocomplete="current-password" /></template>
        </FormField>
        <div class="grid-2">
          <FormField id="pw-new" :label="t('profile.newPassword')" :hint="t('profile.newPasswordHint')" :error="pwErrors.next">
            <template #default="{ attrs }"><input v-bind="attrs" v-model="pw.next" class="input" type="password" autocomplete="new-password" /></template>
          </FormField>
          <FormField id="pw-confirm" :label="t('profile.confirmPassword')" :error="pwErrors.confirm">
            <template #default="{ attrs }"><input v-bind="attrs" v-model="pw.confirm" class="input" type="password" autocomplete="new-password" /></template>
          </FormField>
        </div>
        <div class="form-actions">
          <button type="submit" class="btn btn-secondary" :disabled="pwSaving">{{ t('profile.changePassword') }}</button>
        </div>
      </form>
    </details>
  </div>
</template>

<style scoped>
.profile-page {
  max-width: 760px;
}

.readonly {
  padding: var(--space-4);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
}

.segmented button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 44px;
}
</style>
