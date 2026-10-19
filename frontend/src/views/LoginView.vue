<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import FormField from '@/components/FormField.vue'
import { branding, logoUrl } from '@/lib/branding'
import { loadConfig, publicConfig, signIn } from '@/lib/session'
import { errorText, language, setLanguage, t } from '@/lib/i18n'
import type { DemoAccount, Language } from '@/lib/types'

const route = useRoute()
const router = useRouter()

const form = reactive({ email: '', password: '', code: '' })
const errors = reactive({ email: '', password: '', code: '' })
const formError = ref('')
const busy = ref(false)
const step = ref<'password' | 'code'>('password')
const codeInput = ref<HTMLInputElement | null>(null)
const showPassword = ref(false)

const companyName = computed(() => branding.value.company_name || 'OfficeHub')
const HIGHLIGHTS = [
  { icon: 'inbox', key: 'login.highlightRequests' },
  { icon: 'clock', key: 'login.highlightTime' },
  { icon: 'file', key: 'login.highlightDocuments' },
  { icon: 'users', key: 'login.highlightPeople' },
]

onMounted(loadConfig)

function validate(): boolean {
  errors.email = form.email.trim() ? '' : t('login.emailRequired')
  errors.password = form.password ? '' : t('login.passwordRequired')
  errors.code = step.value === 'code' && !form.code.trim() ? t('login.codeRequired') : ''
  return !errors.email && !errors.password && !errors.code
}

async function submit() {
  formError.value = ''
  if (!validate()) return
  busy.value = true
  try {
    await signIn(form.email.trim(), form.password, step.value === 'code' ? form.code.trim() : undefined)
    const redirect = typeof route.query.redirect === 'string' && route.query.redirect.startsWith('/') ? route.query.redirect : '/'
    router.replace(redirect)
  } catch (error) {
    const code = (error as { code?: string }).code
    if (code === 'two_factor_required') {
      step.value = 'code'
      await nextTick()
      codeInput.value?.focus()
    } else if (code === 'two_factor_invalid') {
      errors.code = errorText(error)
      form.code = ''
    } else {
      formError.value = errorText(error)
    }
  } finally {
    busy.value = false
  }
}

function back() {
  step.value = 'password'
  form.code = ''
  errors.code = ''
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
    <aside class="brand-panel" aria-hidden="true">
      <div class="brand-inner">
        <div class="brand-row">
          <img v-if="branding.logo_version" :src="logoUrl()" alt="" class="logo-img" />
          <span v-else class="logo"><AppIcon name="home" :size="22" /></span>
          <span class="brand">{{ companyName }}</span>
        </div>
        <div class="pitch">
          <p class="pitch-title">{{ t('login.pitch') }}</p>
          <ul class="highlights">
            <li v-for="item in HIGHLIGHTS" :key="item.key">
              <span class="hl-icon"><AppIcon :name="item.icon" :size="18" /></span>{{ t(item.key) }}
            </li>
          </ul>
        </div>
        <p class="powered">OfficeHub</p>
      </div>
    </aside>

    <main class="login-main">
      <div class="mobile-brand">
        <img v-if="branding.logo_version" :src="logoUrl()" alt="" class="logo-img" />
        <span v-else class="logo" aria-hidden="true"><AppIcon name="home" :size="22" /></span>
        <span class="brand">{{ companyName }}</span>
      </div>

      <section class="login-card" aria-labelledby="login-title">
        <h1 id="login-title">{{ step === 'code' ? t('login.codeTitle') : t('login.title') }}</h1>
        <p class="muted">{{ step === 'code' ? t('login.codeHint') : t('login.subtitle') }}</p>

        <div v-if="formError" class="notice notice-danger" role="alert">
          <AppIcon name="alert" />
          <p>{{ formError }}</p>
        </div>

        <form class="stack" novalidate @submit.prevent="submit">
          <template v-if="step === 'password'">
            <FormField id="email" :label="t('login.email')" :error="errors.email">
              <template #default="{ attrs }">
                <input v-bind="attrs" v-model="form.email" class="input" type="email" autocomplete="username" inputmode="email" required />
              </template>
            </FormField>
            <FormField id="password" :label="t('login.password')" :error="errors.password">
              <template #default="{ attrs }">
                <div class="password-box">
                  <input v-bind="attrs" v-model="form.password" class="input" :type="showPassword ? 'text' : 'password'" autocomplete="current-password" required />
                  <button type="button" class="btn btn-ghost btn-icon reveal" :aria-label="showPassword ? t('login.hidePassword') : t('login.showPassword')" :aria-pressed="showPassword" @click="showPassword = !showPassword">
                    <AppIcon :name="showPassword ? 'eyeOff' : 'eye'" :size="20" />
                  </button>
                </div>
              </template>
            </FormField>
          </template>
          <FormField v-else id="code" :label="t('login.code')" :hint="t('login.codeRecovery')" :error="errors.code">
            <template #default="{ attrs }">
              <input
                v-bind="attrs"
                ref="codeInput"
                v-model="form.code"
                class="input code-input"
                inputmode="numeric"
                autocomplete="one-time-code"
                maxlength="20"
                required
              />
            </template>
          </FormField>
          <button type="submit" class="btn btn-primary btn-block btn-lg" :disabled="busy">
            {{ busy ? t('login.submitting') : step === 'code' ? t('login.confirm') : t('login.submit') }}
          </button>
          <button v-if="step === 'code'" type="button" class="btn btn-ghost btn-block" @click="back">{{ t('app.back') }}</button>
          <p v-else class="muted small">{{ t('login.forgot') }}</p>
        </form>
      </section>

      <section v-if="step === 'password' && publicConfig?.demo_mode && publicConfig.demo_accounts" class="demo" aria-labelledby="demo-title">
        <h2 id="demo-title">{{ t('login.demoTitle') }}</h2>
        <p class="muted small">{{ t('login.demoHint', { password: publicConfig.demo_password ?? '' }) }}</p>
        <ul class="demo-list">
          <li v-for="account in publicConfig.demo_accounts" :key="account.email">
            <button type="button" class="demo-account" :aria-label="t('login.demoUse', { name: account.name })" :disabled="busy" @click="useDemo(account)">
              <span class="demo-avatar" aria-hidden="true">{{ account.name.split(' ').map((n) => n[0]).join('') }}</span>
              <span class="demo-text">
                <span class="demo-name">{{ account.name }}</span>
                <span class="muted small">{{ t(`roles.${account.role}`) }} · {{ account.department }}</span>
              </span>
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
  grid-template-columns: minmax(0, 5fr) minmax(0, 6fr);
  background: var(--color-surface);
}

/* ---------- Brand panel ---------- */

.brand-panel {
  position: relative;
  display: flex;
  padding: var(--space-6);
  background: var(--color-highlight);
  color: #ffffff;
  overflow: hidden;
}

.brand-panel::before,
.brand-panel::after {
  content: '';
  position: absolute;
  border-radius: 50%;
  background: rgb(255 255 255 / 0.07);
}

.brand-panel::before {
  width: 420px;
  height: 420px;
  right: -140px;
  top: -120px;
}

.brand-panel::after {
  width: 300px;
  height: 300px;
  left: -100px;
  bottom: -110px;
}

.brand-inner {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  width: 100%;
  max-width: 460px;
  margin: 0 auto;
}

.brand-row,
.mobile-brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.logo {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: rgb(255 255 255 / 0.18);
  color: #fff;
}

.mobile-brand .logo {
  background: var(--color-highlight);
}

.logo-img {
  width: 44px;
  height: 44px;
  object-fit: contain;
  border-radius: 10px;
  background: #ffffff;
  padding: 4px;
}

.brand {
  font-family: var(--font-heading);
  font-size: var(--text-xl);
  font-weight: 600;
  letter-spacing: -0.01em;
}

.pitch {
  display: grid;
  gap: var(--space-5);
  padding: var(--space-7) 0;
}

.pitch-title {
  font-family: var(--font-heading);
  font-size: clamp(1.75rem, 1.2rem + 1.6vw, 2.5rem);
  font-weight: 600;
  line-height: 1.2;
  letter-spacing: -0.02em;
}

.highlights {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-3);
  font-size: var(--text-md);
}

.highlights li {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.hl-icon {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: rgb(255 255 255 / 0.16);
}

.powered {
  font-size: var(--text-xs);
  opacity: 0.75;
}

/* ---------- Form side ---------- */

.login-main {
  width: min(100%, 440px);
  margin: 0 auto;
  padding: var(--space-7) var(--space-4);
  display: grid;
  gap: var(--space-5);
  align-content: center;
}

.mobile-brand {
  display: none;
}

.login-card {
  display: grid;
  gap: var(--space-4);
}

.login-card h1 {
  font-size: var(--text-2xl);
}

.password-box {
  position: relative;
}

.password-box .input {
  padding-right: 52px;
}

.reveal {
  position: absolute;
  right: 2px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-text-muted);
}

.code-input {
  font-size: var(--text-xl);
  letter-spacing: 0.3em;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

.btn-lg {
  min-height: 48px;
  font-size: var(--text-md);
}

.demo {
  display: grid;
  gap: var(--space-2);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
}

.demo h2 {
  font-size: var(--text-md);
}

.demo-list {
  list-style: none;
  margin: var(--space-2) 0 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-2);
}

.demo-account {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  min-height: 52px;
  padding: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color var(--t-fast) ease, background-color var(--t-fast) ease;
}

.demo-account:hover:not(:disabled) {
  border-color: var(--color-primary);
  background: var(--color-primary-soft);
}

.demo-avatar {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
  font-size: var(--text-xs);
  font-weight: 700;
  flex-shrink: 0;
}

.demo-text {
  display: grid;
  min-width: 0;
}

.demo-name {
  font-weight: 600;
  font-size: var(--text-sm);
}

.demo-text .small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--text-xs);
}

.lang {
  justify-self: center;
}

@media (max-width: 899px) {
  .login-page {
    grid-template-columns: 1fr;
  }

  .brand-panel {
    display: none;
  }

  .mobile-brand {
    display: flex;
    justify-content: center;
  }

  .login-main {
    align-content: start;
    padding-top: var(--space-6);
  }
}

@media (max-width: 420px) {
  .demo-list {
    grid-template-columns: 1fr;
  }
}
</style>
