<script setup lang="ts">
/**
 * Guided form for every request type: details → review → confirmation.
 * Used for new requests (/requests/new/:type) and for editing drafts (/requests/:id/edit).
 */
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import FormField from '@/components/FormField.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api } from '@/lib/api'
import { ACCESS_LEVELS, CURRENCIES, EQUIPMENT_CATEGORIES, EXPENSE_CATEGORIES, REQUEST_TYPES, TYPE_ICONS } from '@/lib/requestTypes'
import { errorText, formatDate, formatMoney, formatPeriod, t } from '@/lib/i18n'
import { loadConfig, publicConfig } from '@/lib/session'
import { showToast } from '@/lib/toast'
import { countWorkingDays, todayIso } from '@/lib/workdays'
import type { RequestDetail, RequestType } from '@/lib/types'

const props = defineProps<{ type?: string; id?: string }>()
const router = useRouter()

type Step = 'details' | 'review' | 'done'
type Field = 'title' | 'description' | 'start_date' | 'end_date' | 'amount' | 'currency' | 'category' | 'item' | 'access_level' | 'needed_by' | 'receipt'

const requestType = ref<RequestType>('general')
const step = ref<Step>('details')
const loading = ref(false)
const loadError = ref<string | null>(null)
const busy = ref(false)
const formError = ref('')
const saved = ref<RequestDetail | null>(null)
const isEdit = computed(() => Boolean(props.id))

const form = reactive({
  title: '',
  description: '',
  start_date: '',
  end_date: '',
  amount: '',
  currency: 'EUR',
  category: '',
  item: '',
  access_level: '',
  needed_by: '',
})
const receipt = ref<File | null>(null)
const receiptInput = ref<HTMLInputElement | null>(null)
const errors = reactive<Partial<Record<Field, string>>>({})

const today = todayIso()
const isPeriodType = computed(() => requestType.value === 'vacation' || requestType.value === 'home_office')
const showsTitleField = computed(() => requestType.value === 'expense' || requestType.value === 'general')
const maxUploadMb = computed(() => publicConfig.value?.max_upload_mb ?? 15)

const workingDays = computed(() => (form.start_date && form.end_date && form.end_date >= form.start_date ? countWorkingDays(form.start_date, form.end_date) : null))

// Clear a field's error as soon as the person changes that field.
for (const key of Object.keys(form) as (keyof typeof form)[]) {
  watch(
    () => form[key],
    () => {
      const field = key as Field
      if (!errors[field]) return
      delete errors[field]
      if (Object.keys(errors).length === 0) formError.value = ''
    },
  )
}

function parsedAmount(): string | null {
  const normalized = form.amount.replace(/\s/g, '').replace(',', '.')
  return /^\d{1,7}(\.\d{1,2})?$/.test(normalized) && Number(normalized) > 0 ? normalized : null
}

/** Title for types where the person does not type one. */
const generatedTitle = computed(() => {
  const label = t(`requestTypes.${requestType.value}`)
  switch (requestType.value) {
    case 'vacation':
    case 'home_office':
      return form.start_date ? `${label} ${formatPeriod(form.start_date, form.end_date || form.start_date)}` : label
    case 'equipment':
      return form.item.trim().slice(0, 120) || label
    case 'it_access':
      return `${label}: ${form.item.trim()}`.slice(0, 120)
    default:
      return form.title.trim()
  }
})

const pageTitle = computed(() => (isEdit.value ? t('form.editTitle') : t('form.newTitle', { type: t(`requestTypes.${requestType.value}`) })))

function validate(): boolean {
  for (const key of Object.keys(errors) as Field[]) delete errors[key]
  const type = requestType.value
  const set = (field: Field, code: string) => {
    if (!errors[field]) errors[field] = t(`validation.${code}`)
  }

  if (isPeriodType.value) {
    if (!form.start_date) set('start_date', 'start_required')
    if (!form.end_date) set('end_date', 'end_required')
    else if (form.start_date && form.end_date < form.start_date) set('end_date', 'end_before_start')
    else if (workingDays.value === 0) set('start_date', 'no_working_days')
  }
  if (type === 'expense') {
    if (!form.title.trim()) set('title', 'title_required')
    if (!form.amount.trim()) set('amount', 'amount_required')
    else if (!parsedAmount()) set('amount', 'amount_invalid')
    if (!form.start_date) set('start_date', 'expense_date_required')
    else if (form.start_date > today) set('start_date', 'expense_date_future')
    if (!form.category) set('category', 'category_required')
    if (receipt.value && receipt.value.size > maxUploadMb.value * 1024 * 1024) set('receipt', 'file_too_large')
  }
  if (type === 'equipment') {
    if (!form.item.trim()) set('item', 'item_required')
    if (!form.category) set('category', 'category_required')
  }
  if (type === 'it_access') {
    if (!form.item.trim()) set('item', 'system_required')
    if (!form.access_level) set('access_level', 'access_level_required')
  }
  if (type === 'general') {
    if (!form.title.trim()) set('title', 'title_required')
    if (!form.description.trim()) set('description', 'description_required')
  }
  if ((type === 'equipment' || type === 'it_access') && form.needed_by && form.needed_by < today) set('needed_by', 'needed_by_past')

  const firstInvalid = Object.keys(errors)[0]
  if (firstInvalid) {
    formError.value = t('form.fixErrors')
    nextTick(() => document.getElementById(`f-${firstInvalid}`)?.focus())
    return false
  }
  formError.value = ''
  return true
}

function payload(): Record<string, unknown> {
  const type = requestType.value
  const body: Record<string, unknown> = { title: generatedTitle.value, description: form.description.trim() }
  if (isPeriodType.value) Object.assign(body, { start_date: form.start_date, end_date: form.end_date })
  if (type === 'expense') Object.assign(body, { amount: parsedAmount(), currency: form.currency, start_date: form.start_date, category: form.category })
  if (type === 'equipment') Object.assign(body, { item: form.item.trim(), category: form.category, needed_by: form.needed_by || null })
  if (type === 'it_access') Object.assign(body, { item: form.item.trim(), access_level: form.access_level, needed_by: form.needed_by || null })
  return body
}

function applyServerError(error: unknown) {
  const err = error as { field?: string | null }
  const field = err.field === 'start_date' && requestType.value === 'expense' ? 'start_date' : err.field
  if (field && field in form) {
    errors[field as Field] = errorText(error)
    step.value = 'details'
    formError.value = t('form.fixErrors')
    nextTick(() => document.getElementById(`f-${field}`)?.focus())
  } else {
    formError.value = errorText(error)
  }
}

function goToReview() {
  if (!validate()) return
  step.value = 'review'
  nextTick(() => document.getElementById('review-title')?.focus())
}

async function uploadReceipt(requestId: number): Promise<boolean> {
  if (!receipt.value) return true
  const data = new FormData()
  data.append('file', receipt.value)
  try {
    await api.post(`/api/requests/${requestId}/attachment`, data)
    return true
  } catch {
    showToast(t('form.receiptFailed'), 'error')
    return false
  }
}

async function save(submit: boolean) {
  if (!validate()) return
  busy.value = true
  formError.value = ''
  try {
    let result: RequestDetail
    if (isEdit.value) {
      result = await api.patch<RequestDetail>(`/api/requests/${props.id}`, payload())
      if (receipt.value) await uploadReceipt(result.id)
      if (submit) result = await api.patch<RequestDetail>(`/api/requests/${props.id}`, { status: 'submitted' })
    } else {
      // Save first, attach the receipt, then send — so a failed upload never leaves a half-sent request.
      result = await api.post<RequestDetail>('/api/requests', { type: requestType.value, ...payload(), submit: submit && !receipt.value })
      if (receipt.value) {
        await uploadReceipt(result.id)
        if (submit) result = await api.patch<RequestDetail>(`/api/requests/${result.id}`, { status: 'submitted' })
      }
    }
    saved.value = result
    if (submit) {
      step.value = 'done'
      nextTick(() => document.getElementById('done-title')?.focus())
    } else {
      showToast(isEdit.value ? t('form.changesSaved') : t('form.draftSaved'))
      router.push(`/requests/${result.id}`)
    }
  } catch (error) {
    applyServerError(error)
  } finally {
    busy.value = false
  }
}

function onReceiptChange(event: Event) {
  const input = event.target as HTMLInputElement
  receipt.value = input.files?.[0] ?? null
  delete errors.receipt
}

function clearReceipt() {
  receipt.value = null
  if (receiptInput.value) receiptInput.value.value = ''
}

async function loadDraft() {
  loading.value = true
  loadError.value = null
  try {
    const request = await api.get<RequestDetail>(`/api/requests/${props.id}`)
    if (!request.permissions.can_edit) {
      router.replace(`/requests/${request.id}`)
      return
    }
    requestType.value = request.type
    Object.assign(form, {
      title: request.title,
      description: request.description,
      start_date: request.start_date ?? '',
      end_date: request.end_date ?? '',
      amount: request.amount ?? '',
      currency: request.currency ?? 'EUR',
      category: request.category ?? '',
      item: request.item ?? '',
      access_level: request.access_level ?? '',
      needed_by: request.needed_by ?? '',
    })
  } catch (error) {
    loadError.value = errorText(error)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadConfig()
  if (props.id) {
    loadDraft()
  } else if (props.type && (REQUEST_TYPES as string[]).includes(props.type)) {
    requestType.value = props.type as RequestType
    if (requestType.value === 'expense') form.start_date = today
  } else {
    router.replace('/requests/new')
  }
})

/** Rows for the review step. */
const reviewRows = computed(() => {
  const rows: { label: string; value: string }[] = []
  const type = requestType.value
  rows.push({ label: t('form.title'), value: generatedTitle.value })
  if (isPeriodType.value) {
    rows.push({ label: t('detail.period'), value: formatPeriod(form.start_date, form.end_date) })
    rows.push({ label: t('form.workingDays'), value: workingDays.value === 1 ? t('form.workingDaysOne') : t('form.workingDaysValue', { count: workingDays.value ?? 0 }) })
  }
  if (type === 'expense') {
    rows.push({ label: t('form.amount'), value: formatMoney(parsedAmount(), form.currency) })
    rows.push({ label: t('form.expenseDate'), value: formatDate(form.start_date) })
    rows.push({ label: t('form.category'), value: t(`expenseCategories.${form.category}`) })
    rows.push({ label: t('form.receipt'), value: receipt.value?.name ?? t('detail.noReceipt') })
  }
  if (type === 'equipment') {
    rows.push({ label: t('form.item'), value: form.item })
    rows.push({ label: t('form.category'), value: t(`equipmentCategories.${form.category}`) })
    if (form.needed_by) rows.push({ label: t('form.neededBy'), value: formatDate(form.needed_by) })
  }
  if (type === 'it_access') {
    rows.push({ label: t('form.system'), value: form.item })
    rows.push({ label: t('form.accessLevel'), value: t(`accessLevels.${form.access_level}`) })
    if (form.needed_by) rows.push({ label: t('form.neededBy'), value: formatDate(form.needed_by) })
  }
  if (form.description.trim()) rows.push({ label: descriptionLabel.value, value: form.description.trim() })
  return rows
})

const descriptionLabel = computed(() => {
  switch (requestType.value) {
    case 'vacation':
    case 'home_office':
    case 'it_access':
      return t('form.reason')
    case 'equipment':
      return t('form.equipmentReason')
    case 'expense':
      return t('form.moreDetails')
    default:
      return t('form.description')
  }
})
</script>

<template>
  <div class="page form-page">
    <PageHeader :title="pageTitle" :back-to="isEdit ? `/requests/${id}` : '/requests/new'">
      <template #actions>
        <span v-if="step !== 'done'" class="muted small">{{ t('form.stepOf', { step: step === 'details' ? 1 : 2, total: 2 }) }}</span>
      </template>
    </PageHeader>

    <LoadState :loading="loading" :error="loadError" @retry="loadDraft">
      <!-- Step 3: confirmation -->
      <section v-if="step === 'done' && saved" class="card done" aria-labelledby="done-title">
        <span class="done-icon"><AppIcon name="checkCircle" :size="32" /></span>
        <h2 id="done-title" tabindex="-1">{{ t('form.successTitle') }}</h2>
        <p class="muted">{{ t('form.successText') }}</p>
        <div class="row center">
          <RouterLink :to="`/requests/${saved.id}`" class="btn btn-primary">{{ t('form.viewRequest') }}</RouterLink>
          <RouterLink to="/" class="btn btn-secondary">{{ t('form.toDashboard') }}</RouterLink>
        </div>
      </section>

      <template v-else>
        <div v-if="formError" class="notice notice-danger" role="alert">
          <AppIcon name="alert" />
          <p>{{ formError }}</p>
        </div>

        <!-- Step 1: details -->
        <form v-show="step === 'details'" class="card stack" novalidate @submit.prevent="goToReview">
          <div class="type-line">
            <span class="type-icon"><AppIcon :name="TYPE_ICONS[requestType]" /></span>
            <p class="muted">{{ t(`requestTypeHints.${requestType}`) }}</p>
          </div>

          <FormField v-if="showsTitleField" id="f-title" :label="requestType === 'expense' ? t('form.expenseTitle') : t('form.title')" :hint="requestType === 'general' ? t('form.titleHint') : ''" :error="errors.title">
            <template #default="{ attrs }">
              <input v-bind="attrs" v-model="form.title" class="input" maxlength="120" :placeholder="requestType === 'expense' ? t('form.expenseTitlePlaceholder') : ''" />
            </template>
          </FormField>

          <!-- Vacation & home office -->
          <template v-if="isPeriodType">
            <div class="grid-2">
              <FormField id="f-start_date" :label="t('form.startDate')" :error="errors.start_date">
                <template #default="{ attrs }"><input v-bind="attrs" v-model="form.start_date" class="input" type="date" /></template>
              </FormField>
              <FormField id="f-end_date" :label="t('form.endDate')" :error="errors.end_date">
                <template #default="{ attrs }"><input v-bind="attrs" v-model="form.end_date" class="input" type="date" :min="form.start_date || undefined" /></template>
              </FormField>
            </div>
            <div class="notice notice-info" aria-live="polite">
              <AppIcon name="calendar" />
              <div>
                <p>
                  <strong>{{ t('form.workingDays') }}:</strong>
                  {{ workingDays === null ? '–' : workingDays === 1 ? t('form.workingDaysOne') : t('form.workingDaysValue', { count: workingDays }) }}
                </p>
                <p class="muted small">{{ t('form.workingDaysHint') }}</p>
              </div>
            </div>
          </template>

          <!-- Expense -->
          <template v-if="requestType === 'expense'">
            <div class="grid-2">
              <FormField id="f-amount" :label="t('form.amount')" :error="errors.amount">
                <template #default="{ attrs }"><input v-bind="attrs" v-model="form.amount" class="input" inputmode="decimal" autocomplete="off" placeholder="0,00" /></template>
              </FormField>
              <FormField id="f-currency" :label="t('form.currency')" :error="errors.currency">
                <template #default="{ attrs }">
                  <select v-bind="attrs" v-model="form.currency" class="select">
                    <option v-for="c in CURRENCIES" :key="c" :value="c">{{ c }}</option>
                  </select>
                </template>
              </FormField>
              <FormField id="f-start_date" :label="t('form.expenseDate')" :error="errors.start_date">
                <template #default="{ attrs }"><input v-bind="attrs" v-model="form.start_date" class="input" type="date" :max="today" /></template>
              </FormField>
              <FormField id="f-category" :label="t('form.category')" :error="errors.category">
                <template #default="{ attrs }">
                  <select v-bind="attrs" v-model="form.category" class="select">
                    <option value="" disabled>–</option>
                    <option v-for="c in EXPENSE_CATEGORIES" :key="c" :value="c">{{ t(`expenseCategories.${c}`) }}</option>
                  </select>
                </template>
              </FormField>
            </div>
            <FormField id="f-receipt" :label="t('form.receipt')" :hint="t('form.receiptHint', { size: maxUploadMb })" :error="errors.receipt" optional>
              <template #default="{ attrs }">
                <div class="row">
                  <input v-bind="attrs" ref="receiptInput" class="file-input" type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" @change="onReceiptChange" />
                  <button v-if="receipt" type="button" class="btn btn-ghost" @click="clearReceipt">{{ t('form.receiptRemove') }}</button>
                </div>
              </template>
            </FormField>
          </template>

          <!-- Equipment -->
          <template v-if="requestType === 'equipment'">
            <FormField id="f-item" :label="t('form.item')" :error="errors.item">
              <template #default="{ attrs }"><input v-bind="attrs" v-model="form.item" class="input" maxlength="120" :placeholder="t('form.itemPlaceholder')" /></template>
            </FormField>
            <div class="grid-2">
              <FormField id="f-category" :label="t('form.category')" :error="errors.category">
                <template #default="{ attrs }">
                  <select v-bind="attrs" v-model="form.category" class="select">
                    <option value="" disabled>–</option>
                    <option v-for="c in EQUIPMENT_CATEGORIES" :key="c" :value="c">{{ t(`equipmentCategories.${c}`) }}</option>
                  </select>
                </template>
              </FormField>
              <FormField id="f-needed_by" :label="t('form.neededBy')" :error="errors.needed_by" optional>
                <template #default="{ attrs }"><input v-bind="attrs" v-model="form.needed_by" class="input" type="date" :min="today" /></template>
              </FormField>
            </div>
          </template>

          <!-- IT access -->
          <template v-if="requestType === 'it_access'">
            <FormField id="f-item" :label="t('form.system')" :error="errors.item">
              <template #default="{ attrs }"><input v-bind="attrs" v-model="form.item" class="input" maxlength="100" :placeholder="t('form.systemPlaceholder')" /></template>
            </FormField>
            <div class="grid-2">
              <FormField id="f-access_level" :label="t('form.accessLevel')" :error="errors.access_level">
                <template #default="{ attrs }">
                  <select v-bind="attrs" v-model="form.access_level" class="select">
                    <option value="" disabled>–</option>
                    <option v-for="level in ACCESS_LEVELS" :key="level" :value="level">{{ t(`accessLevels.${level}`) }}</option>
                  </select>
                </template>
              </FormField>
              <FormField id="f-needed_by" :label="t('form.neededBy')" :error="errors.needed_by" optional>
                <template #default="{ attrs }"><input v-bind="attrs" v-model="form.needed_by" class="input" type="date" :min="today" /></template>
              </FormField>
            </div>
          </template>

          <FormField id="f-description" :label="descriptionLabel" :error="errors.description" :optional="requestType !== 'general'">
            <template #default="{ attrs }"><textarea v-bind="attrs" v-model="form.description" class="textarea" maxlength="4000" rows="4" /></template>
          </FormField>

          <div class="form-actions">
            <button type="button" class="btn btn-secondary" :disabled="busy" @click="save(false)">{{ isEdit ? t('form.saveChanges') : t('form.saveDraft') }}</button>
            <button type="submit" class="btn btn-primary" :disabled="busy">{{ t('form.next') }}<AppIcon name="chevronRight" :size="18" /></button>
          </div>
        </form>

        <!-- Step 2: review -->
        <section v-if="step === 'review'" class="card stack" aria-labelledby="review-title">
          <h2 id="review-title" tabindex="-1">{{ t('form.reviewTitle') }}</h2>
          <dl class="facts review">
            <div v-for="row in reviewRows" :key="row.label">
              <dt>{{ row.label }}</dt>
              <dd class="prewrap">{{ row.value }}</dd>
            </div>
          </dl>
          <div class="notice">
            <AppIcon name="info" />
            <p class="small">{{ t('form.reviewHint') }}</p>
          </div>
          <div class="form-actions">
            <button type="button" class="btn btn-secondary" :disabled="busy" @click="step = 'details'">{{ t('form.backToEdit') }}</button>
            <button type="button" class="btn btn-primary" :disabled="busy" @click="save(true)">{{ busy ? t('form.submitting') : t('form.submit') }}</button>
          </div>
        </section>
      </template>
    </LoadState>
  </div>
</template>

<style scoped>
.form-page {
  max-width: 760px;
}

.type-line {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.type-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
  flex-shrink: 0;
}

.file-input {
  min-height: var(--touch);
  font: inherit;
  font-size: var(--text-sm);
  max-width: 100%;
}

.file-input::file-selector-button {
  min-height: 40px;
  margin-right: var(--space-3);
  padding: 0 var(--space-4);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-text);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}

.review {
  grid-template-columns: 1fr;
}

.review > div {
  display: grid;
  grid-template-columns: minmax(140px, 1fr) 2fr;
  gap: var(--space-3);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--color-border);
}

@media (max-width: 560px) {
  .review > div {
    grid-template-columns: 1fr;
    gap: 2px;
  }
}

h2[tabindex='-1']:focus {
  outline: none;
}

.done {
  display: grid;
  justify-items: center;
  gap: var(--space-3);
  padding: var(--space-7) var(--space-5);
  text-align: center;
}

.done-icon {
  display: grid;
  place-items: center;
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: var(--color-success-soft);
  color: var(--color-success);
}

.center {
  justify-content: center;
  margin-top: var(--space-2);
}
</style>
