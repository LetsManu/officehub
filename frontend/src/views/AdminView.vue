<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import SortHeader from '@/components/SortHeader.vue'
import { useSort } from '@/lib/sort'
import FormField from '@/components/FormField.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import PortalSettingsPanel from '@/components/admin/PortalSettingsPanel.vue'
import QuickLinksPanel from '@/components/admin/QuickLinksPanel.vue'
import RoomsPanel from '@/components/admin/RoomsPanel.vue'
import BrandingPanel from '@/components/admin/BrandingPanel.vue'
import HolidaysPanel from '@/components/admin/HolidaysPanel.vue'
import OfficePanel from '@/components/admin/OfficePanel.vue'
import SsoPanel from '@/components/admin/SsoPanel.vue'
import BackupsPanel from '@/components/admin/BackupsPanel.vue'
import SecurityPanel from '@/components/admin/SecurityPanel.vue'
import { api, query } from '@/lib/api'
import { REQUEST_TYPES } from '@/lib/requestTypes'
import { currentUser, isAdmin, isHr, isOverseer, isSupport, roleNames, rolesOf } from '@/lib/session'
import { errorText, t } from '@/lib/i18n'
import { showToast } from '@/lib/toast'
import type { Role, Stats, User } from '@/lib/types'

const stats = ref<Stats | null>(null)
const people = ref<User[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

const exportFilters = reactive({ type: '', date_from: '', date_to: '' })
const exportUrl = computed(() => `/api/admin/requests/export.csv${query(exportFilters)}`)

// Every role besides "employee" (which everyone is); only an administrator gives the administrator role
const ROLES: Role[] = ['teamlead', 'manager', 'hr', 'servicedesk', 'admin']
const grantable = computed(() => ROLES.filter((r) => r !== 'admin' || isAdmin.value))
/** HR changes people, only an administrator changes an administrator. */
const canEdit = (person: User) => isHr.value && (isAdmin.value || !rolesOf(person).includes('admin'))
const canHelp = (person: User) => isSupport.value && (isAdmin.value || !rolesOf(person).includes('admin'))
const rolesFor = ref<User | null>(null)
const rolesDraft = ref<Role[]>([])
function openRoles(person: User) {
  rolesFor.value = person
  rolesDraft.value = [...rolesOf(person)]
}
function toggleRole(role: Role) {
  rolesDraft.value = rolesDraft.value.includes(role) ? rolesDraft.value.filter((r) => r !== role) : [...rolesDraft.value, role]
}
async function saveRoles() {
  if (!rolesFor.value) return
  await updatePerson(rolesFor.value, { roles: rolesDraft.value })
  rolesFor.value = null
}
const addOpen = ref(false)
const saving = ref(false)
const newPerson = reactive({
  first_name: '',
  last_name: '',
  email: '',
  department: '',
  job_title: '',
  roles: [] as Role[],
  language: 'de',
  password: '',
  phone: '',
  manager_id: '' as number | '',
  start_onboarding: true,
  start_date: '',
  vacation_days: 25,
})

const workTarget = ref<User | null>(null)
const workForm = reactive({ start_date: '', vacation_days: 25 })
const workError = ref('')

function openWork(person: User) {
  workTarget.value = person
  Object.assign(workForm, { start_date: person.start_date ?? '', vacation_days: person.vacation_days })
  workError.value = ''
}

async function saveWork() {
  if (!workTarget.value) return
  if (!Number.isInteger(workForm.vacation_days) || workForm.vacation_days < 0 || workForm.vacation_days > 60) {
    workError.value = t('validation.vacation_days_invalid')
    return
  }
  saving.value = true
  try {
    const updated = await api.patch<User>(`/api/admin/users/${workTarget.value.id}`, {
      start_date: workForm.start_date || null,
      vacation_days: workForm.vacation_days,
    })
    people.value = people.value.map((p) => (p.id === updated.id ? updated : p))
    workTarget.value = null
    showToast(t('admin.personSaved'))
  } catch (e) {
    workError.value = errorText(e)
  } finally {
    saving.value = false
  }
}

const PEOPLE_COLUMNS = [
  { key: 'name', label: 'admin.name' },
  { key: 'department', label: 'admin.department' },
  { key: 'manager', label: 'admin.manager' },
  { key: 'role', label: 'admin.role' },
  { key: 'status', label: 'admin.status' },
]
const peopleSort = useSort(
  people,
  {
    name: (p) => `${p.last_name} ${p.first_name}`,
    department: (p) => p.department,
    manager: (p) => people.value.find((m) => m.id === p.manager_id)?.full_name ?? '',
    role: (p) => roleNames(p),
    status: (p) => (p.is_active ? 0 : 1),
  },
  'name',
)

const resetTarget = ref<User | null>(null)
const resetPasswordValue = ref('')
const resetError = ref('')
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
    // Company-wide numbers only for managers and HR
    const [s, p] = await Promise.all([isOverseer.value ? api.get<Stats>('/api/admin/stats') : null, api.get<User[]>('/api/admin/users')])
    stats.value = s
    people.value = p
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

async function updatePerson(person: User, change: Partial<Pick<User, 'roles' | 'is_active' | 'manager_id' | 'e2ee_required'>>) {
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
  Object.assign(newPerson, { first_name: '', last_name: '', email: '', department: '', job_title: '', roles: [], language: 'de', password: '', phone: '', manager_id: '', start_onboarding: true, start_date: '', vacation_days: 25 })
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
    await api.post('/api/admin/users', { ...newPerson, email: newPerson.email.trim(), manager_id: newPerson.manager_id || null, start_date: newPerson.start_date || null })
    addOpen.value = false
    showToast(t('admin.personAdded'))
    await load()
  } catch (e) {
    addError.value = errorText(e)
  } finally {
    saving.value = false
  }
}

function openReset(person: User) {
  resetTarget.value = person
  resetPasswordValue.value = ''
  resetError.value = ''
}

async function resetPassword() {
  if (!resetTarget.value) return
  resetError.value = resetPasswordValue.value.length >= 8 ? '' : t('validation.password_short')
  if (resetError.value) return
  saving.value = true
  try {
    await api.post(`/api/admin/users/${resetTarget.value.id}/password`, { password: resetPasswordValue.value })
    resetTarget.value = null
    showToast(t('admin.passwordReset'))
  } catch (e) {
    resetError.value = errorText(e)
  } finally {
    saving.value = false
  }
}

// Something in the stack needs attention (old Collabora container, missing parts): a small hint for administrators
const systemNotices = ref<string[]>([])
onMounted(async () => {
  if (!isAdmin.value) return
  systemNotices.value = (await api.get<{ notices: string[] }>('/api/admin/system/notices').catch(() => ({ notices: [] }))).notices
})

onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader :title="t('admin.title')" :subtitle="t('admin.subtitle')" />

    <div v-if="systemNotices.length" class="notice notice-warning" role="status">
      <AppIcon name="alert" />
      <p>
        {{ t('admin.systemNotice') }}
        <RouterLink to="/admin/system">{{ t('admin.systemNoticeLink') }}</RouterLink>
      </p>
    </div>

    <LoadState :loading="loading" :error="error" @retry="load">
      <section v-if="stats && isOverseer" aria-labelledby="stats-title" class="stack">
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

      <section v-if="isOverseer" class="card stack" aria-labelledby="export-title">
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
          <div v-if="isHr"><button type="button" class="btn btn-secondary" @click="openAdd"><AppIcon name="plus" />{{ t('admin.addPerson') }}</button></div>
          <div class="table-wrap table-scroll">
            <table class="table table-sticky">
              <thead>
                <tr>
                  <th v-for="col in PEOPLE_COLUMNS" :key="col.key" scope="col" :aria-sort="peopleSort.ariaSort(col.key)">
                    <SortHeader :label="t(col.label)" :active="peopleSort.key.value === col.key" :dir="peopleSort.dir.value" @sort="peopleSort.toggle(col.key)" />
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="person in peopleSort.sorted.value" :key="person.id">
                  <td>
                    <span class="person-name">{{ person.full_name }}</span><br />
                    <span class="muted small">{{ person.email }}</span><br />
                    <button v-if="canEdit(person)" type="button" class="btn btn-ghost work-btn" @click="openWork(person)">
                      {{ t('admin.workDetails') }}
                    </button>
                  </td>
                  <td>{{ person.department }}<br /><span v-if="person.phone" class="muted small">{{ person.phone }}</span></td>
                  <td>
                    <select
                      v-if="canEdit(person)"
                      class="select role-select"
                      :value="person.manager_id ?? ''"
                      :aria-label="`${t('admin.manager')}: ${person.full_name}`"
                      @change="updatePerson(person, { manager_id: Number(($event.target as HTMLSelectElement).value) || null })"
                    >
                      <option value="">{{ t('admin.noManager') }}</option>
                      <option v-for="m in people.filter((p) => p.id !== person.id && p.is_active)" :key="m.id" :value="m.id">{{ m.full_name }}</option>
                    </select>
                    <span v-else>{{ people.find((p) => p.id === person.manager_id)?.full_name ?? '–' }}</span>
                  </td>
                  <td>
                    <span>{{ roleNames(person) }}</span><br />
                    <button
                      v-if="canEdit(person) && person.id !== currentUser?.id"
                      type="button"
                      class="btn btn-ghost work-btn"
                      :aria-label="t('admin.changeRole', { name: person.full_name })"
                      @click="openRoles(person)"
                    >
                      {{ t('admin.changeRoles') }}
                    </button>
                  </td>
                  <td>
                    <button
                      v-if="canEdit(person) && person.id !== currentUser?.id"
                      type="button"
                      class="btn btn-ghost"
                      @click="updatePerson(person, { is_active: !person.is_active })"
                    >
                      {{ person.is_active ? t('admin.deactivate') : t('admin.activate') }}
                    </button>
                    <span :class="person.is_active ? 'active' : 'muted'">{{ person.is_active ? t('admin.active') : t('admin.inactive') }}</span>
                    <button v-if="canHelp(person) && person.id !== currentUser?.id" type="button" class="btn btn-ghost" @click="openReset(person)">{{ t('admin.resetPassword') }}</button>
                    <label v-if="canEdit(person)" class="e2ee-toggle small" :title="t('admin.e2eeRequiredHint')">
                      <input type="checkbox" :checked="!!person.e2ee_required" @change="updatePerson(person, { e2ee_required: ($event.target as HTMLInputElement).checked })" />
                      {{ t('admin.e2eeRequired') }}
                    </label>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </details>

      <details v-if="isHr" class="disclosure">
        <summary>{{ t('admin.links') }}</summary>
        <div class="disclosure-body"><QuickLinksPanel /></div>
      </details>
      <details v-if="isHr" class="disclosure">
        <summary>{{ t('admin.holidays') }}</summary>
        <div class="disclosure-body"><HolidaysPanel /></div>
      </details>
      <template v-if="isAdmin">
        <details class="disclosure">
          <summary>{{ t('admin.portal') }}</summary>
          <div class="disclosure-body"><PortalSettingsPanel :people="people" /></div>
        </details>
        <details class="disclosure">
          <summary>{{ t('admin.rooms') }}</summary>
          <div class="disclosure-body"><RoomsPanel /></div>
        </details>
        <details class="disclosure">
          <summary>{{ t('admin.branding') }}</summary>
          <div class="disclosure-body"><BrandingPanel /></div>
        </details>
        <details class="disclosure">
          <summary>{{ t('admin.security') }}</summary>
          <div class="disclosure-body"><SecurityPanel /></div>
        </details>
        <details class="disclosure">
          <summary>{{ t('admin.sso') }}</summary>
          <div class="disclosure-body"><SsoPanel /></div>
        </details>
        <details class="disclosure">
          <summary>{{ t('admin.office') }}</summary>
          <div class="disclosure-body"><OfficePanel /></div>
        </details>
        <details class="disclosure">
          <summary>{{ t('admin.backups') }}</summary>
          <div class="disclosure-body"><BackupsPanel /></div>
        </details>
      </template>
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
          <fieldset class="roles-pick">
            <legend class="label">{{ t('admin.roles') }}</legend>
            <label v-for="role in grantable" :key="role" class="checkbox">
              <input v-model="newPerson.roles" type="checkbox" :value="role" />
              <span>{{ t(`roles.${role}`) }} <span class="muted small">– {{ t(`roleHints.${role}`) }}</span></span>
            </label>
          </fieldset>
          <FormField id="np-language" :label="t('profile.language')">
            <template #default="{ attrs }">
              <select v-bind="attrs" v-model="newPerson.language" class="select">
                <option value="de">Deutsch</option>
                <option value="en">English</option>
              </select>
            </template>
          </FormField>
        </div>
        <div class="grid-2">
          <FormField id="np-phone" :label="t('admin.phone')" optional>
            <template #default="{ attrs }"><input v-bind="attrs" v-model="newPerson.phone" class="input" type="tel" maxlength="40" /></template>
          </FormField>
          <FormField id="np-manager" :label="t('admin.manager')" optional>
            <template #default="{ attrs }">
              <select v-bind="attrs" v-model="newPerson.manager_id" class="select">
                <option value="">{{ t('admin.noManager') }}</option>
                <option v-for="m in people.filter((p) => p.is_active)" :key="m.id" :value="m.id">{{ m.full_name }}</option>
              </select>
            </template>
          </FormField>
        </div>
        <div class="grid-2">
          <FormField id="np-start" :label="t('admin.startDate')" optional>
            <template #default="{ attrs }"><input v-bind="attrs" v-model="newPerson.start_date" class="input" type="date" /></template>
          </FormField>
          <FormField id="np-vacation" :label="t('admin.vacationEntitlement')">
            <template #default="{ attrs }"><input v-bind="attrs" v-model.number="newPerson.vacation_days" class="input" type="number" min="0" max="60" /></template>
          </FormField>
        </div>
        <label class="checkbox"><input v-model="newPerson.start_onboarding" type="checkbox" /><span>{{ t('admin.startOnboarding') }}</span></label>
        <FormField id="np-password" :label="t('admin.initialPassword')" :hint="t('admin.initialPasswordHint')" :error="newErrors.password">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="newPerson.password" class="input" type="text" autocomplete="off" /></template>
        </FormField>
      </form>
    </BaseModal>

    <BaseModal
      :open="workTarget !== null"
      :title="t('admin.workDetailsTitle', { name: workTarget?.full_name ?? '' })"
      :confirm-label="t('app.save')"
      :busy="saving"
      @close="workTarget = null"
      @confirm="saveWork"
    >
      <form class="stack" novalidate @submit.prevent="saveWork">
        <div v-if="workError" class="notice notice-danger small" role="alert">{{ workError }}</div>
        <FormField id="wd-start" :label="t('admin.startDate')" :hint="t('admin.startDateHint')" optional>
          <template #default="{ attrs }"><input v-bind="attrs" v-model="workForm.start_date" class="input" type="date" /></template>
        </FormField>
        <FormField id="wd-vacation" :label="t('admin.vacationEntitlement')" :hint="t('admin.vacationEntitlementHint')">
          <template #default="{ attrs }"><input v-bind="attrs" v-model.number="workForm.vacation_days" class="input" type="number" min="0" max="60" /></template>
        </FormField>
      </form>
    </BaseModal>

    <BaseModal
      :open="resetTarget !== null"
      :title="t('admin.resetPasswordTitle', { name: resetTarget?.full_name ?? '' })"
      :description="t('admin.resetPasswordText')"
      :confirm-label="t('admin.resetPassword')"
      :busy="saving"
      @close="resetTarget = null"
      @confirm="resetPassword"
    >
      <form novalidate @submit.prevent="resetPassword">
        <FormField id="reset-password" :label="t('admin.initialPassword')" :hint="t('admin.initialPasswordHint')" :error="resetError">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="resetPasswordValue" class="input" type="text" autocomplete="off" /></template>
        </FormField>
      </form>
    </BaseModal>

    <BaseModal
      :open="rolesFor !== null"
      :title="t('admin.rolesTitle', { name: rolesFor?.full_name ?? '' })"
      :description="t('admin.rolesText')"
      :confirm-label="t('app.save')"
      @close="rolesFor = null"
      @confirm="saveRoles"
    >
      <fieldset class="roles-pick">
        <legend class="visually-hidden">{{ t('admin.roles') }}</legend>
        <label v-for="role in grantable" :key="role" class="checkbox">
          <input type="checkbox" :checked="rolesDraft.includes(role)" @change="toggleRole(role)" />
          <span>{{ t(`roles.${role}`) }} <span class="muted small">– {{ t(`roleHints.${role}`) }}</span></span>
        </label>
      </fieldset>
    </BaseModal>
  </div>
</template>

<style scoped>
.work-btn {
  min-height: 32px;
  padding: 0;
  font-size: var(--text-xs);
}

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

.roles-pick {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  border: 0;
}

.role-select {
  min-width: 170px;
}

.active {
  color: var(--color-success);
  font-weight: 600;
}

.e2ee-toggle {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-1);
}
</style>
