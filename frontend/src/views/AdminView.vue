<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import FormField from '@/components/FormField.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api, query } from '@/lib/api'
import { REQUEST_TYPES } from '@/lib/requestTypes'
import { currentUser, isAdmin } from '@/lib/session'
import { errorText, t } from '@/lib/i18n'
import { showToast } from '@/lib/toast'
import type { Role, Stats, User } from '@/lib/types'

const stats = ref<Stats | null>(null)
const people = ref<User[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

const exportFilters = reactive({ type: '', date_from: '', date_to: '' })
const exportUrl = computed(() => `/api/admin/requests/export.csv${query(exportFilters)}`)

const ROLES: Role[] = ['employee', 'manager', 'admin']
const addOpen = ref(false)
const saving = ref(false)
const newPerson = reactive({ first_name: '', last_name: '', email: '', department: '', job_title: '', role: 'employee' as Role, language: 'de', password: '' })
const newErrors = reactive({ first_name: '', last_name: '', email: '', password: '' })
const addError = ref('')

const tiles = computed(() => {
  const s = stats.value
  if (!s) return []
  return [
    { label: t('admin.pending'), value: String(s.pending), to: '/approvals' },
    { label: t('admin.decidedMonth'), value: String(s.decided_this_month) },
    { label: t('admin.avgDecision'), value: s.average_decision_hours === null ? '–' : t('admin.avgDecisionValue', { hours: s.average_decision_hours.toLocaleString() }) },
    { label: t('admin.vacationDays'), value: String(s.approved_vacation_days_this_year) },
  ]
})

const maxPending = computed(() => Math.max(1, ...Object.values(stats.value?.pending_by_type ?? {})))

async function load() {
  loading.value = true
  error.value = null
  try {
    const [s, p] = await Promise.all([api.get<Stats>('/api/admin/stats'), api.get<User[]>('/api/admin/users')])
    stats.value = s
    people.value = p
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

async function updatePerson(person: User, change: Partial<Pick<User, 'role' | 'is_active'>>) {
  try {
    const updated = await api.patch<User>(`/api/admin/users/${person.id}`, change)
    people.value = people.value.map((p) => (p.id === updated.id ? updated : p))
    showToast(t('admin.personSaved'))
  } catch (e) {
    showToast(errorText(e), 'error')
    await load()
  }
}

function openAdd() {
  Object.assign(newPerson, { first_name: '', last_name: '', email: '', department: '', job_title: '', role: 'employee', language: 'de', password: '' })
  Object.assign(newErrors, { first_name: '', last_name: '', email: '', password: '' })
  addError.value = ''
  addOpen.value = true
}

async function addPerson() {
  newErrors.first_name = newPerson.first_name.trim() ? '' : t('validation.first_name_required')
  newErrors.last_name = newPerson.last_name.trim() ? '' : t('validation.last_name_required')
  newErrors.email = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(newPerson.email.trim()) ? '' : t('validation.email_invalid')
  newErrors.password = newPerson.password.length >= 8 ? '' : t('validation.password_short')
  if (Object.values(newErrors).some(Boolean)) return
  saving.value = true
  addError.value = ''
  try {
    await api.post('/api/admin/users', { ...newPerson, email: newPerson.email.trim() })
    addOpen.value = false
    showToast(t('admin.personAdded'))
    await load()
  } catch (e) {
    addError.value = errorText(e)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader :title="t('admin.title')" :subtitle="t('admin.subtitle')" />

    <LoadState :loading="loading" :error="error" @retry="load">
      <section v-if="stats" aria-labelledby="stats-title" class="stack">
        <h2 id="stats-title">{{ t('admin.stats') }}</h2>
        <div class="tiles">
          <component :is="tile.to ? 'RouterLink' : 'div'" v-for="tile in tiles" :key="tile.label" :to="tile.to" class="card tile" :class="{ link: tile.to }">
            <span class="muted small">{{ tile.label }}</span>
            <span class="tile-value">{{ tile.value }}</span>
          </component>
        </div>
        <div class="card">
          <h3 class="bars-title">{{ t('admin.pendingByType') }}</h3>
          <ul class="bars">
            <li v-for="type in REQUEST_TYPES" :key="type">
              <span class="bar-label">{{ t(`requestTypes.${type}`) }}</span>
              <span class="bar-track" aria-hidden="true"><span class="bar-fill" :style="{ width: `${(stats.pending_by_type[type] / maxPending) * 100}%` }" /></span>
              <span class="bar-value">{{ stats.pending_by_type[type] }}</span>
            </li>
          </ul>
        </div>
      </section>

      <section class="card stack" aria-labelledby="export-title">
        <div>
          <h2 id="export-title">{{ t('admin.export') }}</h2>
          <p class="muted small">{{ t('admin.exportHint') }}</p>
        </div>
        <div class="export-grid">
          <div class="field">
            <label for="exp-type" class="label">{{ t('admin.exportType') }}</label>
            <select id="exp-type" v-model="exportFilters.type" class="select">
              <option value="">{{ t('app.all') }}</option>
              <option v-for="type in REQUEST_TYPES" :key="type" :value="type">{{ t(`requestTypes.${type}`) }}</option>
            </select>
          </div>
          <div class="field">
            <label for="exp-from" class="label">{{ t('admin.exportFrom') }}</label>
            <input id="exp-from" v-model="exportFilters.date_from" class="input" type="date" />
          </div>
          <div class="field">
            <label for="exp-to" class="label">{{ t('admin.exportTo') }}</label>
            <input id="exp-to" v-model="exportFilters.date_to" class="input" type="date" />
          </div>
          <a :href="exportUrl" class="btn btn-primary export-btn" download><AppIcon name="download" />{{ t('admin.exportButton') }}</a>
        </div>
      </section>

      <details class="disclosure">
        <summary>{{ t('admin.people') }} ({{ people.length }})</summary>
        <div class="disclosure-body stack">
          <div v-if="isAdmin"><button type="button" class="btn btn-secondary" @click="openAdd"><AppIcon name="plus" />{{ t('admin.addPerson') }}</button></div>
          <div class="table-wrap">
            <table class="table">
              <thead>
                <tr>
                  <th scope="col">{{ t('admin.name') }}</th>
                  <th scope="col">{{ t('admin.department') }}</th>
                  <th scope="col">{{ t('admin.role') }}</th>
                  <th scope="col">{{ t('admin.status') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="person in people" :key="person.id">
                  <td>
                    <span class="person-name">{{ person.full_name }}</span><br />
                    <span class="muted small">{{ person.email }}</span>
                  </td>
                  <td>{{ person.department }}</td>
                  <td>
                    <select
                      v-if="isAdmin && person.id !== currentUser?.id"
                      class="select role-select"
                      :value="person.role"
                      :aria-label="t('admin.changeRole', { name: person.full_name })"
                      @change="updatePerson(person, { role: ($event.target as HTMLSelectElement).value as Role })"
                    >
                      <option v-for="role in ROLES" :key="role" :value="role">{{ t(`roles.${role}`) }}</option>
                    </select>
                    <span v-else>{{ t(`roles.${person.role}`) }}</span>
                  </td>
                  <td>
                    <button
                      v-if="isAdmin && person.id !== currentUser?.id"
                      type="button"
                      class="btn btn-ghost"
                      @click="updatePerson(person, { is_active: !person.is_active })"
                    >
                      {{ person.is_active ? t('admin.deactivate') : t('admin.activate') }}
                    </button>
                    <span :class="person.is_active ? 'active' : 'muted'">{{ person.is_active ? t('admin.active') : t('admin.inactive') }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </details>
    </LoadState>

    <BaseModal :open="addOpen" :title="t('admin.addPersonTitle')" :confirm-label="t('admin.addPerson')" :busy="saving" wide @close="addOpen = false" @confirm="addPerson">
      <form class="stack" novalidate @submit.prevent="addPerson">
        <div v-if="addError" class="notice notice-danger small" role="alert">{{ addError }}</div>
        <div class="grid-2">
          <FormField id="np-first" :label="t('profile.firstName')" :error="newErrors.first_name">
            <template #default="{ attrs }"><input v-bind="attrs" v-model="newPerson.first_name" class="input" maxlength="60" /></template>
          </FormField>
          <FormField id="np-last" :label="t('profile.lastName')" :error="newErrors.last_name">
            <template #default="{ attrs }"><input v-bind="attrs" v-model="newPerson.last_name" class="input" maxlength="60" /></template>
          </FormField>
          <FormField id="np-email" :label="t('profile.email')" :error="newErrors.email">
            <template #default="{ attrs }"><input v-bind="attrs" v-model="newPerson.email" class="input" type="email" maxlength="254" /></template>
          </FormField>
          <FormField id="np-department" :label="t('profile.department')" optional>
            <template #default="{ attrs }"><input v-bind="attrs" v-model="newPerson.department" class="input" maxlength="80" /></template>
          </FormField>
          <FormField id="np-role" :label="t('profile.role')">
            <template #default="{ attrs }">
              <select v-bind="attrs" v-model="newPerson.role" class="select">
                <option v-for="role in ROLES" :key="role" :value="role">{{ t(`roles.${role}`) }}</option>
              </select>
            </template>
          </FormField>
          <FormField id="np-language" :label="t('profile.language')">
            <template #default="{ attrs }">
              <select v-bind="attrs" v-model="newPerson.language" class="select">
                <option value="de">Deutsch</option>
                <option value="en">English</option>
              </select>
            </template>
          </FormField>
        </div>
        <FormField id="np-password" :label="t('admin.initialPassword')" :hint="t('admin.initialPasswordHint')" :error="newErrors.password">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="newPerson.password" class="input" type="text" autocomplete="off" /></template>
        </FormField>
      </form>
    </BaseModal>
  </div>
</template>

<style scoped>
.tiles {
  display: grid;
  gap: var(--space-3);
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr));
}

.tile {
  display: grid;
  gap: var(--space-1);
  padding: var(--space-4) var(--space-5);
  color: var(--color-text);
  text-decoration: none;
}

.tile.link:hover {
  border-color: var(--color-primary);
}

.tile-value {
  font-size: var(--text-2xl);
  font-weight: 650;
}

.bars-title {
  margin-bottom: var(--space-3);
}

.bars {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-2);
}

.bars li {
  display: grid;
  grid-template-columns: minmax(120px, 180px) 1fr 32px;
  align-items: center;
  gap: var(--space-3);
  font-size: var(--text-sm);
}

.bar-track {
  height: 10px;
  border-radius: 999px;
  background: var(--color-neutral-soft);
  overflow: hidden;
}

.bar-fill {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: var(--color-primary);
}

.bar-value {
  text-align: right;
  font-weight: 600;
}

.export-grid {
  display: grid;
  gap: var(--space-4);
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 170px), 1fr));
  align-items: end;
}

.field {
  display: grid;
  gap: 6px;
}

.label {
  font-weight: 600;
  font-size: var(--text-sm);
}

.person-name {
  font-weight: 600;
}

.role-select {
  min-width: 170px;
}

.active {
  color: var(--color-success);
  font-weight: 600;
}
</style>
