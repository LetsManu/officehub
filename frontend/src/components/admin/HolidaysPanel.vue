<script setup lang="ts">
// HR chooses the public holidays (built in for AT, DE, CH) and adds company holidays.
import { onMounted, reactive, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import FormField from '@/components/FormField.vue'
import { api } from '@/lib/api'
import { clearHolidays } from '@/lib/holidays'
import { errorText, formatDateLong, t } from '@/lib/i18n'
import { showToast } from '@/lib/toast'

interface Holiday {
  id: number | null
  date: string
  name_de: string
  name_en: string
  company: boolean
}

interface Config {
  country: '' | 'AT' | 'DE' | 'CH'
  region: string
  company_holidays: Holiday[]
}

const DE_STATES = ['BW', 'BY', 'BE', 'BB', 'HB', 'HH', 'HE', 'MV', 'NI', 'NW', 'RP', 'SL', 'SN', 'ST', 'SH', 'TH']

const config = ref<Config>({ country: '', region: '', company_holidays: [] })
const form = reactive({ day: '', name: '' })
const errors = reactive({ day: '', name: '' })
const saving = ref(false)

async function load() {
  config.value = await api.get<Config>('/api/holidays/config').catch(() => config.value)
}

async function saveCountry() {
  saving.value = true
  try {
    config.value = await api.put<Config>('/api/holidays/config', { country: config.value.country, region: config.value.country === 'DE' ? config.value.region : '' })
    clearHolidays()
    showToast(t('admin.holidaysSaved'))
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    saving.value = false
  }
}

async function addHoliday() {
  errors.day = form.day ? '' : t('validation.date_required')
  errors.name = form.name.trim() ? '' : t('validation.name_required')
  if (errors.day || errors.name) return
  try {
    config.value = await api.post<Config>('/api/holidays/company', { day: form.day, name: form.name.trim() })
    form.day = form.name = ''
    clearHolidays()
    showToast(t('admin.holidaysSaved'))
  } catch (e) {
    errors.day = errorText(e)
  }
}

async function removeHoliday(holiday: Holiday) {
  config.value = await api.delete<Config>(`/api/holidays/company/${holiday.id}`)
  clearHolidays()
}

onMounted(load)
</script>

<template>
  <div class="stack">
    <p class="muted small">{{ t('admin.holidaysHint') }}</p>
    <div class="row selects">
      <div class="field">
        <label for="hol-country" class="label">{{ t('admin.holidayCountry') }}</label>
        <select id="hol-country" v-model="config.country" class="select">
          <option value="">{{ t('admin.holidayNone') }}</option>
          <option v-for="c in ['AT', 'DE', 'CH']" :key="c" :value="c">{{ t(`countries.${c}`) }}</option>
        </select>
      </div>
      <div v-if="config.country === 'DE'" class="field">
        <label for="hol-region" class="label">{{ t('admin.holidayRegion') }}</label>
        <select id="hol-region" v-model="config.region" class="select">
          <option value="">{{ t('admin.holidayRegionNone') }}</option>
          <option v-for="s in DE_STATES" :key="s" :value="s">{{ t(`deStates.${s}`) }}</option>
        </select>
      </div>
      <button type="button" class="btn btn-primary" :disabled="saving" @click="saveCountry">{{ t('app.save') }}</button>
    </div>

    <h3>{{ t('admin.companyHolidays') }}</h3>
    <ul v-if="config.company_holidays.length" class="list days">
      <li v-for="h in config.company_holidays" :key="h.id ?? h.date">
        <span class="grow"><strong>{{ formatDateLong(h.date) }}</strong> · {{ h.name_de }}</span>
        <button type="button" class="btn btn-ghost btn-icon" :aria-label="`${t('admin.removeHoliday')}: ${h.name_de}`" @click="removeHoliday(h)">
          <AppIcon name="trash" :size="18" />
        </button>
      </li>
    </ul>
    <p v-else class="muted small">{{ t('admin.noCompanyHolidays') }}</p>
    <form class="row add" novalidate @submit.prevent="addHoliday">
      <FormField id="hol-day" :label="t('admin.holidayDate')" :error="errors.day">
        <template #default="{ attrs }"><input v-bind="attrs" v-model="form.day" type="date" class="input" /></template>
      </FormField>
      <FormField id="hol-name" :label="t('admin.holidayName')" :error="errors.name">
        <template #default="{ attrs }"><input v-bind="attrs" v-model="form.name" class="input" maxlength="80" :placeholder="t('admin.holidayNamePlaceholder')" /></template>
      </FormField>
      <button type="submit" class="btn btn-secondary"><AppIcon name="plus" :size="18" />{{ t('admin.addHoliday') }}</button>
    </form>
  </div>
</template>

<style scoped>
.selects,
.add {
  align-items: flex-end;
}

.field {
  display: grid;
  gap: 6px;
  min-width: 200px;
}

.label {
  font-weight: 600;
  font-size: var(--text-sm);
}

.days {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.days li {
  display: flex;
  align-items: center;
  padding: var(--space-1) var(--space-1) var(--space-1) var(--space-4);
}

.grow {
  flex: 1;
}

.add > :not(button) {
  flex: 1 1 200px;
}
</style>
