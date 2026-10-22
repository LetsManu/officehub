<script setup lang="ts">
import { computed, reactive, ref, watchEffect } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import FormField from '@/components/FormField.vue'
import PhotoPicker from '@/components/PhotoPicker.vue'
import DeputySettings from '@/components/DeputySettings.vue'
import AppPasswords from '@/components/AppPasswords.vue'
import MeetingKeys from '@/components/MeetingKeys.vue'
import DesktopSettings from '@/components/DesktopSettings.vue'
import MyEquipment from '@/components/MyEquipment.vue'
import TwoFactorSettings from '@/components/TwoFactorSettings.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api } from '@/lib/api'
import { currentUser, isApprover, publicConfig, setUser } from '@/lib/session'
import { errorText, formatDate, locale, t } from '@/lib/i18n'
import { applyTheme, theme } from '@/lib/theme'
import { showToast } from '@/lib/toast'
import { TILES } from '@/lib/tiles'
import type { Language, User } from '@/lib/types'

const form = reactive({
  first_name: '',
  last_name: '',
  department: '',
  job_title: '',
  office_location: '',
  language: 'de' as Language,
  phone: '',
  mobile: '',
  show_phone: true,
  show_mobile: false,
  birthday_day: null as number | null,
  birthday_month: null as number | null,
  show_birthday: false,
})
const DAYS = Array.from({ length: 31 }, (_, i) => i + 1)
const MONTHS = computed(() =>
  Array.from({ length: 12 }, (_, i) => ({ value: i + 1, label: new Date(2000, i, 1).toLocaleDateString(locale.value, { month: 'long' }) })),
)
const pinned = ref<string[]>([])
const pinnedError = ref('')
const errors = reactive({ first_name: '', last_name: '', phone: '', mobile: '', birthday: '' })
const PHONE = /^[0-9+()/\-. ]*$/
const saving = ref(false)
const formError = ref('')

const pw = reactive({ current: '', next: '', confirm: '' })
const pwErrors = reactive({ current: '', next: '', confirm: '' })
const pwSaving = ref(false)

watchEffect(() => {
  const u = currentUser.value
  if (u) {
    Object.assign(form, {
      first_name: u.first_name,
      last_name: u.last_name,
      department: u.department,
      job_title: u.job_title,
      office_location: u.office_location,
      language: u.language,
      phone: u.phone,
      mobile: u.mobile,
      show_phone: u.show_phone,
      show_mobile: u.show_mobile,
      birthday_day: u.birthday_day,
      birthday_month: u.birthday_month,
      show_birthday: u.show_birthday,
    })
    pinned.value = [...u.pinned_tiles]
  }
})

async function save() {
  errors.first_name = form.first_name.trim() ? '' : t('validation.first_name_required')
  errors.last_name = form.last_name.trim() ? '' : t('validation.last_name_required')
  errors.phone = PHONE.test(form.phone) ? '' : t('validation.phone_invalid')
  errors.mobile = PHONE.test(form.mobile) ? '' : t('validation.phone_invalid')
  errors.birthday = (form.birthday_day === null) !== (form.birthday_month === null) ? t('validation.birthday_invalid') : ''
  if (errors.first_name || errors.last_name || errors.phone || errors.mobile || errors.birthday) return
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

function togglePinned(key: string) {
  pinnedError.value = ''
  if (pinned.value.includes(key)) pinned.value = pinned.value.filter((k) => k !== key)
  else if (pinned.value.length >= 2) pinnedError.value = t('profile.favouritesLimit')
  else pinned.value = [...pinned.value, key]
}

async function saveEmail(value: boolean) {
  try {
    setUser(await api.patch<User>('/api/profile', { email_notifications: value }))
    showToast(t('profile.saved'))
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

async function saveFavourites() {
  try {
    setUser(await api.patch<User>('/api/profile', { pinned_tiles: pinned.value }))
    showToast(t('profile.saved'))
  } catch (e) {
    pinnedError.value = errorText(e)
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

    <section class="card">
      <PhotoPicker />
    </section>

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

      <h3 class="subhead">{{ t('profile.contact') }}</h3>
      <div class="grid-2">
        <FormField id="p-phone" :label="t('profile.phone')" :error="errors.phone" optional>
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.phone" class="input" type="tel" maxlength="40" autocomplete="tel" /></template>
        </FormField>
        <FormField id="p-mobile" :label="t('profile.mobile')" :error="errors.mobile" optional>
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.mobile" class="input" type="tel" maxlength="40" /></template>
        </FormField>
      </div>
      <label class="checkbox"><input v-model="form.show_phone" type="checkbox" /><span>{{ t('profile.showPhone') }}</span></label>
      <label class="checkbox"><input v-model="form.show_mobile" type="checkbox" /><span>{{ t('profile.showMobile') }}</span></label>

      <h3 class="subhead">{{ t('profile.birthday') }}</h3>
      <p class="muted small">{{ t('profile.birthdayHint') }}</p>
      <div class="grid-2">
        <FormField id="p-bday" :label="t('profile.birthdayDay')" :error="errors.birthday" optional>
          <template #default="{ attrs }">
            <select v-bind="attrs" v-model="form.birthday_day" class="select">
              <option :value="null">–</option>
              <option v-for="d in DAYS" :key="d" :value="d">{{ d }}</option>
            </select>
          </template>
        </FormField>
        <FormField id="p-bmonth" :label="t('profile.birthdayMonth')" optional>
          <template #default="{ attrs }">
            <select v-bind="attrs" v-model="form.birthday_month" class="select">
              <option :value="null">–</option>
              <option v-for="m in MONTHS" :key="m.value" :value="m.value">{{ m.label }}</option>
            </select>
          </template>
        </FormField>
      </div>
      <label class="checkbox">
        <input v-model="form.show_birthday" type="checkbox" :disabled="form.birthday_day === null" />
        <span>{{ t('profile.showBirthday') }}</span>
      </label>

      <dl class="facts readonly">
        <div><dt>{{ t('profile.email') }}</dt><dd>{{ currentUser?.email }}</dd></div>
        <div><dt>{{ t('profile.role') }}</dt><dd>{{ currentUser ? t(`roles.${currentUser.role}`) : '' }}</dd></div>
        <div v-if="currentUser?.start_date"><dt>{{ t('profile.startDate') }}</dt><dd>{{ formatDate(currentUser.start_date) }}</dd></div>
        <div><dt>{{ t('profile.vacationDays') }}</dt><dd>{{ t('profile.vacationDaysValue', { count: currentUser?.vacation_days ?? 0 }) }}</dd></div>
      </dl>
      <p class="muted small">{{ t('profile.readonlyHint') }}</p>

      <div class="form-actions">
        <button type="submit" class="btn btn-primary" :disabled="saving">{{ saving ? t('app.saving') : t('app.save') }}</button>
      </div>
    </form>

    <section class="card stack" aria-labelledby="sec-title">
      <h2 id="sec-title">{{ t('security.title') }}</h2>
      <TwoFactorSettings />
    </section>

    <AppPasswords />

    <MeetingKeys />

    <DesktopSettings />

    <section class="card stack" aria-labelledby="notify-title">
      <h2 id="notify-title">{{ t('profile.notificationsTitle') }}</h2>
      <label class="checkbox">
        <input :checked="currentUser?.email_notifications" type="checkbox" @change="saveEmail(($event.target as HTMLInputElement).checked)" />
        <span>
          <span class="label-strong">{{ t('profile.emailNotifications') }}</span><br />
          <span class="muted small">{{ publicConfig?.mail_enabled ? t('profile.emailNotificationsHint') : t('profile.emailNotificationsOff') }}</span>
        </span>
      </label>
    </section>

    <section v-if="isApprover" class="card stack" aria-labelledby="deputy-title">
      <h2 id="deputy-title">{{ t('deputy.title') }}</h2>
      <DeputySettings />
    </section>

    <section class="card stack" aria-labelledby="equipment-title">
      <h2 id="equipment-title">{{ t('assets.mineTitle') }}</h2>
      <MyEquipment />
    </section>

    <details class="disclosure">
      <summary>{{ t('profile.favourites') }}</summary>
      <div class="disclosure-body stack">
        <p class="muted small">{{ t('profile.favouritesHint') }}</p>
        <div class="tile-grid" role="group" :aria-label="t('profile.favourites')">
          <label v-for="tile in TILES" :key="tile.key" class="checkbox tile-option">
            <input type="checkbox" :checked="pinned.includes(tile.key)" @change="togglePinned(tile.key)" />
            <span>{{ t(tile.label) }}</span>
          </label>
        </div>
        <p v-if="pinnedError" class="error-text" role="alert">{{ pinnedError }}</p>
        <div><button type="button" class="btn btn-secondary" @click="saveFavourites">{{ t('app.save') }}</button></div>
      </div>
    </details>

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
.label-strong {
  font-weight: 600;
}

.profile-page {
  max-width: 760px;
}

.subhead {
  margin-top: var(--space-2);
  font-size: var(--text-md);
}

.tile-grid {
  display: grid;
  gap: 0 var(--space-4);
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 220px), 1fr));
}

.error-text {
  color: var(--color-danger);
  font-size: var(--text-sm);
  font-weight: 500;
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
