<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api, query } from '@/lib/api'
import { errorText, formatDate, formatMoney, t } from '@/lib/i18n'
import type { Report } from '@/lib/types'

type Name = 'absences' | 'expenses' | 'overdue' | 'equipment'
const NAMES: Name[] = ['absences', 'expenses', 'overdue', 'equipment']

const name = ref<Name>('absences')
const filters = reactive({ month: new Date().toISOString().slice(0, 7), date_from: '', date_to: '', days: 7 })
const report = ref<Report | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

const params = computed(() => {
  if (name.value === 'absences') return { month: filters.month }
  if (name.value === 'overdue') return { days: filters.days }
  return { date_from: filters.date_from, date_to: filters.date_to }
})
const csvUrl = computed(() => `/api/reports/${name.value}${query({ ...params.value, format: 'csv' })}`)

/** Turns raw values (type keys, dates, amounts) into readable text. */
function display(column: string, value: string | number | null, row: (string | number | null)[]): string {
  if (value === null || value === '') return '–'
  const text = String(value)
  if (column === 'type') return t(`requestTypes.${text}`)
  if (column === 'status') return t(`statuses.${text}`)
  if (column === 'category') {
    const key = name.value === 'expenses' ? `expenseCategories.${text}` : `equipmentCategories.${text}`
    return t(key)
  }
  if (['start_date', 'end_date', 'submitted', 'approved_on'].includes(column)) return formatDate(text)
  if (column === 'total') return formatMoney(text, String(row[report.value!.columns.indexOf('currency')] ?? 'EUR'))
  return text
}

async function load() {
  loading.value = true
  error.value = null
  try {
    report.value = await api.get<Report>(`/api/reports/${name.value}${query(params.value)}`)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

watch([name, filters], load, { deep: true })
onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader :title="t('reports.title')" :subtitle="t('reports.subtitle')" />

    <div class="segmented" role="group" :aria-label="t('reports.choose')">
      <button v-for="n in NAMES" :key="n" type="button" :aria-pressed="name === n" @click="name = n">{{ t(`reports.${n}`) }}</button>
    </div>

    <div class="filters">
      <div v-if="name === 'absences'" class="field">
        <label for="rep-month" class="label">{{ t('reports.month') }}</label>
        <input id="rep-month" v-model="filters.month" type="month" class="input" />
      </div>
      <div v-else-if="name === 'overdue'" class="field">
        <label for="rep-days" class="label">{{ t('reports.days') }}</label>
        <input id="rep-days" v-model.number="filters.days" type="number" min="1" max="365" class="input" />
      </div>
      <template v-else>
        <div class="field">
          <label for="rep-from" class="label">{{ t('reports.from') }}</label>
          <input id="rep-from" v-model="filters.date_from" type="date" class="input" />
        </div>
        <div class="field">
          <label for="rep-to" class="label">{{ t('reports.to') }}</label>
          <input id="rep-to" v-model="filters.date_to" type="date" class="input" :min="filters.date_from || undefined" />
        </div>
      </template>
      <a :href="csvUrl" class="btn btn-secondary csv" download><AppIcon name="download" />{{ t('reports.download') }}</a>
    </div>

    <LoadState :loading="loading" :error="error" @retry="load">
      <section v-if="report" class="card card-flush">
        <template v-if="report.rows.length">
          <p class="count muted small" aria-live="polite">{{ t('reports.rows', { count: report.rows.length }) }}</p>
          <div class="table-wrap">
            <table class="table">
              <caption class="visually-hidden">{{ t(`reports.${name}`) }}</caption>
              <thead>
                <tr><th v-for="column in report.columns" :key="column" scope="col">{{ t(`reports.columns.${column}`) }}</th></tr>
              </thead>
              <tbody>
                <tr v-for="(row, index) in report.rows" :key="index">
                  <td v-for="(value, col) in row" :key="col" :class="{ num: typeof value === 'number' || report.columns[col] === 'total' }">
                    {{ display(report.columns[col], value, row) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
        <EmptyState v-else icon="chart" :message="t('reports.empty')" />
      </section>
    </LoadState>
  </div>
</template>

<style scoped>
.filters {
  display: flex;
  flex-wrap: wrap;
  align-items: end;
  gap: var(--space-3);
}

.field {
  display: grid;
  gap: 6px;
  min-width: 180px;
}

.label {
  font-weight: 600;
  font-size: var(--text-sm);
}

.csv {
  margin-left: auto;
}

.count {
  padding: var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--color-border);
}

.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
</style>
