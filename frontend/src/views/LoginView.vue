<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import FormField from '@/components/FormField.vue'
import { loadConfig, publicConfig, signIn } from '@/lib/session'
import { errorText, language, setLanguage, t } from '@/lib/i18n'
import type { DemoAccount, Language } from '@/lib/types'

const route = useRoute()
const router = useRouter()

const form = reactive({ email: '', password: '' })
const errors = reactive({ email: '', password: '' })
const formError = ref('')
const busy = ref(false)

onMounted(loadConfig)

function validate(): boolean {
  errors.email = form.email.trim() ? '' : t('login.emailRequired')
  errors.password = form.password ? '' : t('login.passwordRequired')
  return !errors.email && !errors.password
}

async function submit() {
  formError.value = ''
  if (!validate()) return
  busy.value = true
  try {
    await signIn(form.email.trim(), form.password)
    const redirect = typeof route.query.redirect === 'string' && route.query.redirect.startsWith('/') ? route.query.redirect : '/'
    router.replace(redirect)
  } catch (error) {
    formError.value = errorText(error)
  } finally {
    busy.value = false
  }
}

function useDemo(account: DemoAccount) {
  form.email = account.email
  form.password = publicConfig.value?.demo_password ?? ''
  errors.email = errors.password = ''
  submit()
}

function changeLanguage(value: Language) {
  setLanguage(value)
}
</script>

<template>
  <div class="login-page">
    <main class="login-main">
      <div class="brand-row">
        <span class="logo" aria-hidden="true"><AppIcon name="home" :size="22" /></span>
        <span class="brand">OfficeHub</span>
      </div>

      <section class="card login-card" aria-labelledby="login-title">
        <h1 id="login-title">{{ t('login.title') }}</h1>
        <p class="muted">{{ t('login.subtitle') }}</p>

        <div v-if="formError" class="notice notice-danger" role="alert">
          <AppIcon name="alert" />
          <p>{{ formError }}</p>
        </div>

        <form class="stack" novalidate @submit.prevent="submit">
          <FormField id="email" :label="t('login.email')" :error="errors.email">
            <template #default="{ attrs }">
              <input v-bind="attrs" v-model="form.email" class="input" type="email" autocomplete="username" inputmode="email" required />
            </template>
          </FormField>
          <FormField id="password" :label="t('login.password')" :error="errors.password">
            <template #default="{ attrs }">
              <input v-bind="attrs" v-model="form.password" class="input" type="password" autocomplete="current-password" required />
            </template>
          </FormField>
          <button type="submit" class="btn btn-primary btn-block" :disabled="busy">
            {{ busy ? t('login.submitting') : t('login.submit') }}
          </button>
          <p class="muted small">{{ t('login.forgot') }}</p>
        </form>
      </section>

      <section v-if="publicConfig?.demo_mode && publicConfig.demo_accounts" class="card demo" aria-labelledby="demo-title">
        <h2 id="demo-title">{{ t('login.demoTitle') }}</h2>
        <p class="muted small">{{ t('login.demoHint', { password: publicConfig.demo_password ?? '' }) }}</p>
        <ul class="list demo-list">
          <li v-for="account in publicConfig.demo_accounts" :key="account.email">
            <button type="button" class="demo-account" :aria-label="t('login.demoUse', { name: account.name })" :disabled="busy" @click="useDemo(account)">
              <span class="demo-name">{{ account.name }}</span>
              <span class="muted small">{{ t(`roles.${account.role}`) }} · {{ account.department }}</span>
            </button>
          </li>
        </ul>
      </section>

      <div class="segmented lang" role="group" :aria-label="t('app.language')">
        <button type="button" :aria-pressed="language === 'de'" lang="de" @click="changeLanguage('de')">Deutsch</button>
        <button type="button" :aria-pressed="language === 'en'" lang="en" @click="changeLanguage('en')">English</button>
      </div>
    </main>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: grid;
  place-items: start center;
  padding: var(--space-7) var(--space-4);
}

.login-main {
  width: min(100%, 420px);
  display: grid;
  gap: var(--space-4);
}

.brand-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
}

.logo {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: var(--color-primary);
  color: #fff;
}

.brand {
  font-size: var(--text-xl);
  font-weight: 700;
}

.login-card {
  display: grid;
  gap: var(--space-4);
}

.demo {
  display: grid;
  gap: var(--space-2);
}

.demo-list {
  margin-top: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.demo-account {
  display: grid;
  width: 100%;
  min-height: 56px;
  padding: var(--space-2) var(--space-4);
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.demo-account:hover {
  background: var(--color-surface-muted);
}

.demo-name {
  font-weight: 600;
}

.lang {
  justify-self: center;
}
</style>
