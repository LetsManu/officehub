<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import EmptyState from '@/components/EmptyState.vue'
import FormField from '@/components/FormField.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import SectionContact from '@/components/SectionContact.vue'
import { api } from '@/lib/api'
import { currentUser, isApprover } from '@/lib/session'
import { errorText, formatDate, formatDateLong, formatDateTime, t } from '@/lib/i18n'
import { showToast } from '@/lib/toast'
import { todayIso } from '@/lib/workdays'
import type { DirectoryEntry, Visitor } from '@/lib/types'

type Tab = 'mine' | 'reception'

const tab = ref<Tab>(isApprover.value ? 'reception' : 'mine')
const day = ref(todayIso())
const mine = ref<Visitor[]>([])
const reception = ref<Visitor[]>([])
const people = ref<DirectoryEntry[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

const formOpen = ref(false)
const form = reactive({ name: '', company: '', visit_date: todayIso(), expected_time: '', host_id: 0, note: '' })
const errors = reactive<Record<string, string>>({})
const saving = ref(false)
const cancelTarget = ref<Visitor | null>(null)

const list = computed(() => (tab.value === 'reception' ? reception.value : mine.value))

function badgeClass(status: Visitor['status']): string {
  return { expected: 'badge-submitted', checked_in: 'badge-approved', checked_out: 'badge-draft', cancelled: 'badge-cancelled' }[status]
}

function timeOf(value: string | null): string {
  return value ? formatDateTime(value).split(', ').pop() ?? '' : ''
}

async function load() {
  loading.value = list.value.length === 0
  error.value = null
  try {
    mine.value = await api.get<Visitor[]>('/api/visitors')
    if (isApprover.value) reception.value = await api.get<Visitor[]>(`/api/visitors?scope=day&day=${day.value}`)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

function openForm() {
  Object.assign(form, { name: '', company: '', visit_date: todayIso(), expected_time: '', host_id: currentUser.value?.id ?? 0, note: '' })
  for (const key of Object.keys(errors)) delete errors[key]
  formOpen.value = true
  if (!people.value.length) api.get<DirectoryEntry[]>('/api/directory').then((p) => (people.value = p)).catch(() => undefined)
}

async function register() {
  for (const key of Object.keys(errors)) delete errors[key]
  if (!form.name.trim()) errors.name = t('validation.name_required')
  if (!form.visit_date || form.visit_date < todayIso()) errors.visit_date = t('validation.day_past')
  if (Object.keys(errors).length) return
  saving.value = true
  try {
    await api.post('/api/visitors', { ...form, name: form.name.trim(), company: form.company.trim(), note: form.note.trim() })
    formOpen.value = false
    showToast(t('visitors.registered'))
    await load()
  } catch (e) {
    const field = (e as { field?: string }).field
    errors[field && field in form ? field : 'name'] = errorText(e)
  } finally {
    saving.value = false
  }
}

async function act(visitor: Visitor, action: 'check_in' | 'check_out' | 'cancel') {
  saving.value = true
  try {
    await api.post(`/api/visitors/${visitor.id}/status`, { action })
    const message = { check_in: 'visitors.checkedIn', check_out: 'visitors.checkedOut', cancel: 'visitors.cancelled' }[action]
    showToast(t(message, { name: visitor.name }))
    cancelTarget.value = null
    await load()
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    saving.value = false
  }
}

watch(day, load)
watch(tab, load)
onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader :title="t('visitors.title')" :subtitle="t('visitors.subtitle')">
      <template #actions>
        <button type="button" class="btn btn-primary" @click="openForm"><AppIcon name="plus" />{{ t('visitors.register') }}</button>
      </template>
    </PageHeader>

    <div v-if="isApprover" class="row">
      <div class="segmented" role="group" :aria-label="t('visitors.title')">
        <button type="button" :aria-pressed="tab === 'reception'" @click="tab = 'reception'">{{ t('visitors.reception') }}</button>
        <button type="button" :aria-pressed="tab === 'mine'" @click="tab = 'mine'">{{ t('visitors.mine') }}</button>
      </div>
      <template v-if="tab === 'reception'">
        <label for="visit-day" class="visually-hidden">{{ t('visitors.date') }}</label>
        <input id="visit-day" v-model="day" type="date" class="input day-input" />
        <span class="muted">{{ formatDateLong(day) }}</span>
      </template>
    </div>

    <LoadState :loading="loading" :error="error" @retry="load">
      <section class="card card-flush">
        <ul v-if="list.length" class="list">
          <li v-for="visitor in list" :key="visitor.id" class="visitor">
            <span class="visitor-icon"><AppIcon name="badge" /></span>
            <span class="main">
              <span class="visitor-name">{{ visitor.name }}<template v-if="visitor.company"> · <span class="muted">{{ visitor.company }}</span></template></span>
              <span class="muted small">
                <template v-if="tab === 'mine'">{{ formatDate(visitor.visit_date) }} · </template>
                <template v-if="visitor.expected_time">{{ visitor.expected_time }} · </template>{{ t('visitors.visits', { name: visitor.host_name }) }}
              </span>
              <span v-if="visitor.note" class="small">{{ visitor.note }}</span>
            </span>
            <span class="side">
              <span class="badge" :class="badgeClass(visitor.status)">
                {{ t(`visitors.statuses.${visitor.status}`) }}
                <template v-if="visitor.status === 'checked_in' && visitor.checked_in_at"> {{ t('visitors.since', { time: timeOf(visitor.checked_in_at) }) }}</template>
              </span>
              <span class="row actions">
                <button v-if="visitor.can_check_in && visitor.status === 'expected'" type="button" class="btn btn-primary" :disabled="saving" @click="act(visitor, 'check_in')">
                  {{ t('visitors.checkIn') }}
                </button>
                <button v-if="visitor.can_check_in && visitor.status === 'checked_in'" type="button" class="btn btn-secondary" :disabled="saving" @click="act(visitor, 'check_out')">
                  {{ t('visitors.checkOut') }}
                </button>
                <button v-if="visitor.can_cancel" type="button" class="btn btn-ghost danger-text" :disabled="saving" @click="cancelTarget = visitor">{{ t('visitors.cancel') }}</button>
              </span>
            </span>
          </li>
        </ul>
        <EmptyState
          v-else
          icon="badge"
          :message="tab === 'reception' ? t('visitors.receptionEmpty') : t('visitors.noMine')"
          :action-label="tab === 'mine' ? t('visitors.register') : undefined"
          @action="openForm"
        />
      </section>
    </LoadState>

    <SectionContact section="visitors" />

    <BaseModal :open="formOpen" :title="t('visitors.registerTitle')" :confirm-label="t('visitors.register')" :busy="saving" wide @close="formOpen = false" @confirm="register">
      <form class="stack" novalidate @submit.prevent="register">
        <div class="grid-2">
          <FormField id="v-name" :label="t('visitors.name')" :error="errors.name">
            <template #default="{ attrs }"><input v-bind="attrs" v-model="form.name" class="input" maxlength="120" autocomplete="off" /></template>
          </FormField>
          <FormField id="v-company" :label="t('visitors.company')" optional>
            <template #default="{ attrs }"><input v-bind="attrs" v-model="form.company" class="input" maxlength="120" /></template>
          </FormField>
          <FormField id="v-visit_date" :label="t('visitors.date')" :error="errors.visit_date">
            <template #default="{ attrs }"><input v-bind="attrs" v-model="form.visit_date" class="input" type="date" :min="todayIso()" /></template>
          </FormField>
          <FormField id="v-expected_time" :label="t('visitors.time')" optional>
            <template #default="{ attrs }"><input v-bind="attrs" v-model="form.expected_time" class="input" type="time" step="900" /></template>
          </FormField>
        </div>
        <FormField id="v-host_id" :label="t('visitors.host')" :error="errors.host_id">
          <template #default="{ attrs }">
            <select v-bind="attrs" v-model.number="form.host_id" class="select">
              <option :value="currentUser?.id">{{ currentUser?.full_name }}</option>
              <option v-for="p in people.filter((p) => p.id !== currentUser?.id)" :key="p.id" :value="p.id">{{ p.full_name }} · {{ p.department }}</option>
            </select>
          </template>
        </FormField>
        <FormField id="v-note" :label="t('visitors.note')" optional>
          <template #default="{ attrs }"><textarea v-bind="attrs" v-model="form.note" class="textarea" rows="2" maxlength="500" /></template>
        </FormField>
      </form>
    </BaseModal>

    <BaseModal
      :open="cancelTarget !== null"
      :title="t('visitors.cancelTitle')"
      :description="cancelTarget ? t('visitors.cancelText', { name: cancelTarget.name, date: formatDate(cancelTarget.visit_date) }) : ''"
      :confirm-label="t('visitors.cancelConfirm')"
      :cancel-label="t('visitors.keep')"
      tone="danger"
      :busy="saving"
      @close="cancelTarget = null"
      @confirm="cancelTarget && act(cancelTarget, 'cancel')"
    />
  </div>
</template>

<style scoped>
.day-input {
  width: auto;
}

.visitor {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3) var(--space-4);
  padding: var(--space-3) var(--space-4) var(--space-3) var(--space-5);
}

.visitor-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
  flex-shrink: 0;
}

.main {
  display: grid;
  gap: 2px;
  flex: 1;
  min-width: 200px;
}

.visitor-name {
  font-weight: 600;
}

.side {
  display: grid;
  justify-items: end;
  gap: var(--space-2);
}

.actions {
  gap: var(--space-2);
}

.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: var(--text-xs);
  font-weight: 600;
}

.badge-submitted {
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
}

.badge-approved {
  background: var(--color-success-soft);
  color: var(--color-success);
}

.badge-draft,
.badge-cancelled {
  background: var(--color-neutral-soft);
  color: var(--color-text-muted);
}

.danger-text {
  color: var(--color-danger);
}

@media (max-width: 560px) {
  .side {
    justify-items: start;
    width: 100%;
    padding-left: 56px;
  }
}
</style>
