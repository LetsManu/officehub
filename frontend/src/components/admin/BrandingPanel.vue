<script setup lang="ts">
// HR sets the company name, accent colour and logo. The preview updates live.
import { computed, reactive, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import FormField from '@/components/FormField.vue'
import { api } from '@/lib/api'
import { branding, contrast, DEFAULT_ACCENT, logoUrl, setBranding, type Branding } from '@/lib/branding'
import { errorText, t } from '@/lib/i18n'
import { showToast } from '@/lib/toast'

const PRESETS = ['#1D4ED8', '#0F766E', '#7C3AED', '#BE123C', '#B45309', '#334155']

const form = reactive({ company_name: branding.value.company_name, accent_color: branding.value.accent_color })
const error = ref('')
const saving = ref(false)
const logoInput = ref<HTMLInputElement | null>(null)

watch(branding, (value) => Object.assign(form, { company_name: value.company_name, accent_color: value.accent_color }))

const validHex = computed(() => /^#[0-9a-fA-F]{6}$/.test(form.accent_color))
const readable = computed(() => validHex.value && contrast(form.accent_color, '#ffffff') >= 4.5)

async function save() {
  error.value = !validHex.value ? t('validation.color_invalid') : !readable.value ? t('validation.accent_contrast') : ''
  if (error.value) return
  saving.value = true
  try {
    setBranding(await api.put<Branding>('/api/branding', { company_name: form.company_name.trim(), accent_color: form.accent_color }))
    showToast(t('admin.brandingSaved'))
  } catch (e) {
    error.value = errorText(e)
  } finally {
    saving.value = false
  }
}

async function uploadLogo(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  const data = new FormData()
  data.append('file', file)
  try {
    setBranding(await api.post<Branding>('/api/branding/logo', data))
    showToast(t('admin.logoSaved'))
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    if (logoInput.value) logoInput.value.value = ''
  }
}

async function removeLogo() {
  try {
    setBranding(await api.delete<Branding>('/api/branding/logo'))
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}
</script>

<template>
  <div class="branding">
    <form class="stack" novalidate @submit.prevent="save">
      <FormField id="br-name" :label="t('admin.companyName')" :hint="t('admin.companyNameHint')" optional>
        <template #default="{ attrs }"><input v-bind="attrs" v-model="form.company_name" class="input" maxlength="60" /></template>
      </FormField>
      <FormField id="br-color" :label="t('admin.accentColor')" :hint="t('admin.accentHint')" :error="error">
        <template #default="{ attrs }">
          <div class="row color-row">
            <input v-model="form.accent_color" type="color" class="color-input" :aria-label="t('admin.accentColor')" />
            <input v-bind="attrs" v-model="form.accent_color" class="input hex" maxlength="7" spellcheck="false" />
            <button
              v-for="preset in PRESETS"
              :key="preset"
              type="button"
              class="swatch"
              :class="{ active: form.accent_color.toUpperCase() === preset }"
              :style="{ background: preset }"
              :aria-label="preset"
              @click="form.accent_color = preset"
            />
          </div>
        </template>
      </FormField>
      <p v-if="validHex" class="small contrast" :class="readable ? 'ok' : 'bad'">
        <AppIcon :name="readable ? 'checkCircle' : 'alert'" :size="16" />
        {{ readable ? t('admin.contrastOk') : t('validation.accent_contrast') }}
      </p>
      <div class="row">
        <button type="submit" class="btn btn-primary" :disabled="saving">{{ t('app.save') }}</button>
        <button v-if="form.accent_color.toUpperCase() !== DEFAULT_ACCENT" type="button" class="btn btn-ghost" @click="form.accent_color = DEFAULT_ACCENT">
          {{ t('admin.accentReset') }}
        </button>
      </div>
    </form>

    <div class="stack">
      <p class="label-text">{{ t('admin.logo') }}</p>
      <div class="logo-box">
        <img v-if="branding.logo_version" :src="logoUrl()" alt="" />
        <span v-else class="muted small">{{ t('admin.noLogo') }}</span>
      </div>
      <p class="muted small">{{ t('admin.logoHint') }}</p>
      <div class="row">
        <label class="btn btn-secondary">
          <AppIcon name="upload" :size="18" />{{ t('admin.logoUpload') }}
          <input ref="logoInput" type="file" accept="image/png,image/jpeg" class="visually-hidden" @change="uploadLogo" />
        </label>
        <button v-if="branding.logo_version" type="button" class="btn btn-ghost" @click="removeLogo">{{ t('admin.logoRemove') }}</button>
      </div>

      <p class="label-text">{{ t('admin.preview') }}</p>
      <div class="preview" :style="{ '--preview': validHex ? form.accent_color : DEFAULT_ACCENT }">
        <span class="preview-btn">{{ t('admin.previewButton') }}</span>
        <span class="preview-link">{{ t('admin.previewLink') }}</span>
        <span class="preview-chip">{{ t('admin.previewChip') }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.branding {
  display: grid;
  gap: var(--space-6);
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr));
}

.color-row {
  gap: var(--space-2);
}

.color-input {
  width: 48px;
  height: var(--touch);
  padding: 2px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  cursor: pointer;
}

.hex {
  width: 110px;
  font-variant-numeric: tabular-nums;
  text-transform: uppercase;
}

.swatch {
  width: 28px;
  height: 28px;
  border: 2px solid var(--color-surface);
  border-radius: 50%;
  box-shadow: 0 0 0 1px var(--color-border-strong);
  cursor: pointer;
}

.swatch.active {
  box-shadow: 0 0 0 2px var(--color-text);
}

.contrast {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.contrast.ok {
  color: var(--color-success);
}

.contrast.bad {
  color: var(--color-danger);
}

.label-text {
  font-weight: 600;
  font-size: var(--text-sm);
}

.logo-box {
  display: grid;
  place-items: center;
  width: 160px;
  height: 80px;
  border: 1px dashed var(--color-border-strong);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
}

.logo-box img {
  max-width: 140px;
  max-height: 64px;
  object-fit: contain;
}

.preview {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.preview-btn {
  padding: 10px 16px;
  border-radius: var(--radius-md);
  background: var(--preview);
  color: #ffffff;
  font-weight: 600;
  font-size: var(--text-sm);
}

.preview-link {
  color: var(--preview);
  font-weight: 600;
  text-decoration: underline;
}

.preview-chip {
  padding: 2px 10px;
  border-radius: var(--radius-full);
  border: 1px solid var(--preview);
  color: var(--preview);
  font-size: var(--text-xs);
  font-weight: 700;
}
</style>
