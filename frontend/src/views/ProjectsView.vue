<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import EmptyState from '@/components/EmptyState.vue'
import FormField from '@/components/FormField.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import SortHeader from '@/components/SortHeader.vue'
import { api, query } from '@/lib/api'
import { errorText, formatDate, t } from '@/lib/i18n'
import { PROJECT_COLORS, percent } from '@/lib/planning'
import { useSort } from '@/lib/sort'
import { hours } from '@/lib/time'
import { showToast } from '@/lib/toast'
import type { Project } from '@/lib/types'

const projects = ref<Project[]>([])
const showFinished = ref(false)
const loading = ref(true)
const error = ref<string | null>(null)
const busy = ref(false)

const sort = useSort(projects, {
  name: (p) => p.name.toLowerCase(),
  client: (p) => p.client.toLowerCase(),
  end: (p) => p.end_date ?? '9999',
  booked: (p) => (p.budget_minutes ? (p.booked_minutes ?? 0) / p.budget_minutes : -1),
}, 'name')

const editorOpen = ref(false)
const editing = ref<Project | null>(null)
const form = reactive({ name: '', client: '', color: 'blue', budget: '' as string | number, start_date: '', end_date: '', active: true })
const errors = reactive<Record<string, string>>({})

async function load() {
  loading.value = projects.value.length === 0
  error.value = null
  try {
    projects.value = await api.get<Project[]>(`/api/planning/projects${query({ include_inactive: showFinished.value ? 'true' : '' })}`)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

function budgetState(p: Project): 'none' | 'ok' | 'near' | 'over' {
  if (!p.budget_minutes) return 'none'
  const used = (p.booked_minutes ?? 0) / p.budget_minutes
  return used > 1 ? 'over' : used >= 0.85 ? 'near' : 'ok'
}

function openEditor(p: Project | null) {
  editing.value = p
  Object.assign(form, p
    ? { name: p.name, client: p.client, color: p.color, budget: p.budget_minutes != null ? p.budget_minutes / 60 : '',
        start_date: p.start_date ?? '', end_date: p.end_date ?? '', active: p.active }
    : { name: '', client: '', color: PROJECT_COLORS[projects.value.length % PROJECT_COLORS.length], budget: '', start_date: '', end_date: '', active: true })
  for (const key of Object.keys(errors)) delete errors[key]
  editorOpen.value = true
}

async function save() {
  for (const key of Object.keys(errors)) delete errors[key]
  if (!form.name.trim()) errors.name = t('validation.name_required')
  if (form.start_date && form.end_date && form.end_date < form.start_date) errors.end_date = t('validation.end_before_start')
  const budget = form.budget === '' ? null : Number(form.budget)
  if (budget !== null && !(budget >= 0)) errors.budget = t('projects.budgetInvalid')
  if (Object.keys(errors).length) return
  busy.value = true
  try {
    const body = {
      name: form.name.trim(), client: form.client.trim(), color: form.color, budget_hours: budget,
      start_date: form.start_date || null, end_date: form.end_date || null, active: form.active,
    }
    if (editing.value) await api.put(`/api/planning/projects/${editing.value.id}`, body)
    else await api.post('/api/planning/projects', body)
    editorOpen.value = false
    showToast(t('projects.saved'))
    await load()
  } catch (e) {
    const field = (e as { field?: string }).field
    errors[field && field in form ? field : 'form'] = errorText(e)
  } finally {
    busy.value = false
  }
}

const deleting = ref<Project | null>(null)

async function remove() {
  if (!deleting.value) return
  busy.value = true
  try {
    await api.delete(`/api/planning/projects/${deleting.value.id}`)
    showToast(t('projects.deleted'))
    deleting.value = null
    editorOpen.value = false
    await load()
  } catch (e) {
    showToast(errorText(e), 'error')
    deleting.value = null
  } finally {
    busy.value = false
  }
}

watch(showFinished, load)
onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader :title="t('projects.title')" :subtitle="t('projects.subtitle')" :crumbs="[{ label: t('planning.title'), to: '/planning' }]">
      <template #actions>
        <button type="button" class="btn btn-primary" @click="openEditor(null)"><AppIcon name="plus" />{{ t('projects.new') }}</button>
      </template>
    </PageHeader>

    <label class="checkbox">
      <input v-model="showFinished" type="checkbox" />
      <span>{{ t('projects.showFinished') }}</span>
    </label>

    <LoadState :loading="loading" :error="error" @retry="load">
      <section v-if="projects.length" class="card card-flush">
        <div class="table-wrap table-scroll">
          <table class="table table-sticky">
            <thead>
              <tr>
                <th scope="col" :aria-sort="sort.ariaSort('name')"><SortHeader :label="t('projects.name')" :active="sort.key.value === 'name'" :dir="sort.dir.value" @sort="sort.toggle('name')" /></th>
                <th scope="col" :aria-sort="sort.ariaSort('client')"><SortHeader :label="t('projects.client')" :active="sort.key.value === 'client'" :dir="sort.dir.value" @sort="sort.toggle('client')" /></th>
                <th scope="col" :aria-sort="sort.ariaSort('end')"><SortHeader :label="t('projects.period')" :active="sort.key.value === 'end'" :dir="sort.dir.value" @sort="sort.toggle('end')" /></th>
                <th scope="col" class="num">{{ t('projects.planned') }}</th>
                <th scope="col" :aria-sort="sort.ariaSort('booked')"><SortHeader :label="t('projects.booked')" :active="sort.key.value === 'booked'" :dir="sort.dir.value" @sort="sort.toggle('booked')" /></th>
                <th scope="col"><span class="visually-hidden">{{ t('assets.actions') }}</span></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in sort.sorted.value" :key="p.id" :class="{ finished: !p.active }">
                <td>
                  <RouterLink :to="`/planning/projects/${p.id}`" class="pname" :class="`pc-${p.color}`">
                    <span class="project-dot" aria-hidden="true" />
                    <strong>{{ p.name }}</strong>
                  </RouterLink>
                  <span v-if="!p.active" class="tag">{{ t('projects.finished') }}</span>
                </td>
                <td>{{ p.client || '–' }}</td>
                <td class="nowrap">
                  <template v-if="p.start_date || p.end_date">{{ formatDate(p.start_date) || '…' }} – {{ formatDate(p.end_date) || '…' }}</template>
                  <span v-else class="muted">–</span>
                </td>
                <td class="num">{{ hours(p.planned_minutes ?? 0) }} h</td>
                <td>
                  <div class="budget" :class="`b-${budgetState(p)}`">
                    <span class="num">{{ hours(p.booked_minutes ?? 0) }} h<template v-if="p.budget_minutes"> / {{ hours(p.budget_minutes) }} h</template></span>
                    <template v-if="p.budget_minutes">
                      <span class="bar" aria-hidden="true"><span :style="{ width: `${Math.min(100, percent(p.booked_minutes ?? 0, p.budget_minutes))}%` }" /></span>
                      <span class="small state">{{ t(`projects.budget.${budgetState(p)}`, { pct: percent(p.booked_minutes ?? 0, p.budget_minutes) }) }}</span>
                    </template>
                  </div>
                </td>
                <td class="actions">
                  <button type="button" class="btn btn-ghost btn-icon" :aria-label="`${t('app.edit')}: ${p.name}`" @click="openEditor(p)"><AppIcon name="edit" :size="18" /></button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      <section v-else class="card"><EmptyState icon="briefcase" :message="t('projects.empty')" :action-label="t('projects.new')" @action="openEditor(null)" /></section>
    </LoadState>

    <BaseModal :open="editorOpen" :title="editing ? t('projects.edit') : t('projects.new')" :confirm-label="t('app.save')" :busy="busy" @close="editorOpen = false" @confirm="save">
      <form class="stack" novalidate @submit.prevent="save">
        <div v-if="errors.form" class="notice notice-danger small" role="alert">{{ errors.form }}</div>
        <FormField id="pr-name" :label="t('projects.name')" :error="errors.name">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.name" class="input" maxlength="100" /></template>
        </FormField>
        <FormField id="pr-client" :label="t('projects.client')" optional>
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.client" class="input" maxlength="100" :placeholder="t('projects.clientPlaceholder')" /></template>
        </FormField>
        <fieldset class="colors">
          <legend>{{ t('projects.color') }}</legend>
          <label v-for="c in PROJECT_COLORS" :key="c" class="swatch" :class="`pc-${c}`">
            <input v-model="form.color" type="radio" name="pr-color" :value="c" />
            <span class="dot" aria-hidden="true"><AppIcon v-if="form.color === c" name="check" :size="16" /></span>
            <span class="visually-hidden">{{ t(`projects.colors.${c}`) }}</span>
          </label>
        </fieldset>
        <FormField id="pr-budget" :label="t('projects.budgetHours')" :hint="t('projects.budgetHint')" :error="errors.budget" optional>
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.budget" type="number" min="0" step="1" class="input short" inputmode="numeric" /></template>
        </FormField>
        <div class="grid-2">
          <FormField id="pr-start" :label="t('planning.from')" optional>
            <template #default="{ attrs }"><input v-bind="attrs" v-model="form.start_date" type="date" class="input" /></template>
          </FormField>
          <FormField id="pr-end" :label="t('planning.to')" :error="errors.end_date" optional>
            <template #default="{ attrs }"><input v-bind="attrs" v-model="form.end_date" type="date" class="input" :min="form.start_date" /></template>
          </FormField>
        </div>
        <label v-if="editing" class="checkbox">
          <input v-model="form.active" type="checkbox" />
          <span>{{ t('projects.activeLabel') }}</span>
        </label>
        <div v-if="editing">
          <button type="button" class="btn btn-ghost danger-text" @click="deleting = editing"><AppIcon name="trash" />{{ t('projects.delete') }}</button>
        </div>
      </form>
    </BaseModal>

    <BaseModal
      :open="deleting !== null"
      :title="t('projects.deleteTitle', { name: deleting?.name ?? '' })"
      :description="t('projects.deleteText')"
      :confirm-label="t('projects.delete')"
      tone="danger"
      :busy="busy"
      @close="deleting = null"
      @confirm="remove"
    />
  </div>
</template>

<style scoped>
.pname {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text);
  text-decoration: none;
}

.pname:hover strong {
  text-decoration: underline;
}

.finished td {
  color: var(--color-text-muted);
}

.tag {
  margin-left: var(--space-2);
  padding: 1px 8px;
  border-radius: 99px;
  background: var(--color-neutral-soft);
  font-size: 0.75rem;
}

.nowrap {
  white-space: nowrap;
}

.budget {
  display: grid;
  gap: 4px;
  min-width: 170px;
}

.bar {
  position: relative;
  height: 6px;
  border-radius: 99px;
  background: var(--color-neutral-soft);
  overflow: hidden;
}

.bar > span {
  position: absolute;
  inset: 0 auto 0 0;
  border-radius: inherit;
  background: var(--color-success);
}

.b-near .bar > span,
.b-over .bar > span {
  background: var(--color-warning);
}

.b-near .state,
.b-over .state {
  color: var(--color-warning);
  font-weight: 600;
}

.colors {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  border: 0;
}

.colors legend {
  margin-bottom: var(--space-2);
  font-weight: 600;
  font-size: var(--text-sm);
}

.swatch {
  position: relative;
  cursor: pointer;
}

.swatch input {
  position: absolute;
  opacity: 0;
}

.swatch .dot {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: var(--pc);
  color: #fff;
}

.swatch input:focus-visible + .dot {
  outline: 3px solid var(--color-focus);
  outline-offset: 2px;
}

.short {
  max-width: 160px;
}

.danger-text {
  color: var(--color-danger);
}
</style>
