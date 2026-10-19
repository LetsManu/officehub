<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadState from '@/components/LoadState.vue'
import OrgNode from '@/components/OrgNode.vue'
import PageHeader from '@/components/PageHeader.vue'
import SectionContact from '@/components/SectionContact.vue'
import { api, query } from '@/lib/api'
import { downloadCsv } from '@/lib/csv'
import { errorText, t } from '@/lib/i18n'
import type { DirectoryEntry } from '@/lib/types'

type View = 'list' | 'org' | 'phones'
const VIEWS: View[] = ['list', 'org', 'phones']

const route = useRoute()
const router = useRouter()

const view = ref<View>(VIEWS.includes(route.query.view as View) ? (route.query.view as View) : 'list')
const search = ref(typeof route.query.q === 'string' ? route.query.q : '')
const department = ref(typeof route.query.department === 'string' ? route.query.department : '')
const people = ref<DirectoryEntry[]>([])
const everyone = ref<DirectoryEntry[]>([])
const departments = ref<string[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const orgOpen = ref(true)
const orgKey = ref(0)

let timer: number | undefined

const viewLabels = computed<Record<View, string>>(() => ({ list: t('people.viewList'), org: t('people.viewOrg'), phones: t('people.viewPhones') }))
const byId = computed(() => new Map(everyone.value.map((p) => [p.id, p])))
const resultLabel = computed(() => (people.value.length === 1 ? t('people.resultsOne') : t('people.results', { count: people.value.length })))

/** Top of the org chart: people without a (visible) manager. */
const roots = computed(() => everyone.value.filter((p) => p.manager_id === null || !byId.value.has(p.manager_id)))
const reportsOf = computed(() => {
  const map = new Map<number, DirectoryEntry[]>()
  for (const person of everyone.value) {
    if (person.manager_id !== null && byId.value.has(person.manager_id)) {
      map.set(person.manager_id, [...(map.get(person.manager_id) ?? []), person])
    }
  }
  return map
})

function telHref(number: string): string {
  return `tel:${number.replace(/[^0-9+]/g, '')}`
}

async function load() {
  loading.value = people.value.length === 0
  error.value = null
  try {
    people.value = await api.get<DirectoryEntry[]>(`/api/directory${query({ q: search.value.trim(), department: department.value })}`)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

async function loadAll() {
  try {
    const [all, deps] = await Promise.all([api.get<DirectoryEntry[]>('/api/directory'), api.get<string[]>('/api/directory/departments')])
    everyone.value = all
    departments.value = deps
  } catch {
    /* the list view still works */
  }
}

function exportCsv() {
  downloadCsv(
    'phone-list.csv',
    [t('people.name'), t('people.department'), t('people.phone'), t('people.mobile'), t('people.email')],
    people.value.map((p) => [p.full_name, p.department, p.phone, p.mobile, p.email]),
  )
}

function printPage() {
  window.print()
}

function toggleOrg(open: boolean) {
  orgOpen.value = open
  orgKey.value++
}

watch([search, department, view], () => {
  router.replace({
    query: {
      ...(view.value !== 'list' ? { view: view.value } : {}),
      ...(search.value ? { q: search.value } : {}),
      ...(department.value ? { department: department.value } : {}),
    },
  })
  window.clearTimeout(timer)
  timer = window.setTimeout(load, 250)
})

onMounted(() => {
  load()
  loadAll()
})
</script>

<template>
  <div class="page">
    <PageHeader :title="t('people.title')" :subtitle="t('people.subtitle')">
      <template v-if="view === 'phones'" #actions>
        <button type="button" class="btn btn-secondary" @click="exportCsv"><AppIcon name="download" />{{ t('people.exportCsv') }}</button>
        <button type="button" class="btn btn-secondary" @click="printPage"><AppIcon name="printer" />{{ t('people.print') }}</button>
      </template>
    </PageHeader>

    <div class="segmented no-print" role="group" :aria-label="t('people.viewLabel')">
      <button v-for="v in VIEWS" :key="v" type="button" :aria-pressed="view === v" @click="view = v">{{ viewLabels[v] }}</button>
    </div>

    <div v-if="view !== 'org'" class="filters no-print" role="search">
      <div class="search-box">
        <label for="people-search" class="visually-hidden">{{ t('people.search') }}</label>
        <AppIcon name="search" class="search-icon" />
        <input id="people-search" v-model="search" class="input" type="search" :placeholder="t('people.searchPlaceholder')" autocomplete="off" />
      </div>
      <div>
        <label for="people-department" class="visually-hidden">{{ t('people.department') }}</label>
        <select id="people-department" v-model="department" class="select">
          <option value="">{{ t('people.allDepartments') }}</option>
          <option v-for="d in departments" :key="d" :value="d">{{ d }}</option>
        </select>
      </div>
    </div>

    <LoadState :loading="loading" :error="error" @retry="load">
      <!-- Org chart -->
      <section v-if="view === 'org'" class="card">
        <div class="row no-print org-actions">
          <button type="button" class="btn btn-ghost" @click="toggleOrg(true)">{{ t('people.expandAll') }}</button>
          <button type="button" class="btn btn-ghost" @click="toggleOrg(false)">{{ t('people.collapseAll') }}</button>
        </div>
        <ul :key="orgKey" class="org-root">
          <OrgNode v-for="person in roots" :key="person.id" :person="person" :reports-of="reportsOf" :open="orgOpen" />
        </ul>
      </section>

      <template v-else-if="people.length">
        <p class="muted small" aria-live="polite">{{ resultLabel }}</p>

        <!-- Cards -->
        <ul v-if="view === 'list'" class="people-grid">
          <li v-for="person in people" :key="person.id" class="card person">
            <div class="person-head">
              <UserAvatar :id="person.id" :name="person.full_name" :photo-version="person.photo_version" :size="48" />
              <div class="person-names">
                <p class="person-name">{{ person.full_name }}</p>
                <p class="muted small">{{ person.job_title }}<template v-if="person.job_title && person.department"> · </template>{{ person.department }}</p>
              </div>
            </div>
            <ul class="contact-list">
              <li v-if="person.phone"><AppIcon name="phone" :size="18" /><a :href="telHref(person.phone)">{{ person.phone }}</a></li>
              <li v-if="person.mobile"><AppIcon name="phone" :size="18" /><a :href="telHref(person.mobile)">{{ person.mobile }}</a> <span class="muted small">({{ t('people.mobile') }})</span></li>
              <li><AppIcon name="mail" :size="18" /><a :href="`mailto:${person.email}`">{{ person.email }}</a></li>
              <li v-if="person.office_location" class="muted"><AppIcon name="home" :size="18" />{{ person.office_location }}</li>
            </ul>
            <p v-if="person.manager_id && byId.get(person.manager_id)" class="muted small">
              {{ t('people.reportsTo', { name: byId.get(person.manager_id)!.full_name }) }}
            </p>
          </li>
        </ul>

        <!-- Phone list -->
        <section v-else class="card card-flush">
          <div class="table-wrap">
            <table class="table phone-table">
              <thead>
                <tr>
                  <th scope="col">{{ t('people.name') }}</th>
                  <th scope="col">{{ t('people.department') }}</th>
                  <th scope="col">{{ t('people.phone') }}</th>
                  <th scope="col">{{ t('people.mobile') }}</th>
                  <th scope="col">{{ t('people.email') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="person in people" :key="person.id">
                  <th scope="row" class="name-cell">{{ person.full_name }}</th>
                  <td>{{ person.department }}</td>
                  <td><a v-if="person.phone" :href="telHref(person.phone)">{{ person.phone }}</a><span v-else class="muted">–</span></td>
                  <td><a v-if="person.mobile" :href="telHref(person.mobile)">{{ person.mobile }}</a><span v-else class="muted">–</span></td>
                  <td><a :href="`mailto:${person.email}`">{{ person.email }}</a></td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </template>

      <section v-else class="card">
        <EmptyState icon="search" :message="t('people.empty')" :action-label="t('documents.clearSearch')" @action="search = ''; department = ''" />
      </section>
    </LoadState>

    <SectionContact section="directory" />
  </div>
</template>

<style scoped>
.filters {
  display: grid;
  gap: var(--space-3);
  grid-template-columns: minmax(0, 1fr) minmax(180px, 240px);
}

.search-box {
  position: relative;
}

.search-box .input {
  padding-left: 42px;
}

.search-icon {
  position: absolute;
  left: 13px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-text-muted);
  pointer-events: none;
}

.people-grid {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-3);
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr));
}

.person {
  display: grid;
  gap: var(--space-3);
  align-content: start;
  padding: var(--space-4) var(--space-5);
}

.person-head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.avatar {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
  font-weight: 700;
  flex-shrink: 0;
}

.person-names {
  min-width: 0;
}

.person-name {
  font-weight: 650;
}

.contact-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 2px;
  font-size: var(--text-sm);
}

.contact-list li {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 32px;
  overflow-wrap: anywhere;
}

.contact-list .icon {
  color: var(--color-text-muted);
}

.name-cell {
  font-weight: 600;
  color: var(--color-text);
  background: transparent;
}

.org-actions {
  margin: calc(var(--space-2) * -1) 0 var(--space-3);
}

.org-root {
  list-style: none;
  margin: 0;
  padding: 0;
}

@media (max-width: 640px) {
  .filters {
    grid-template-columns: 1fr;
  }
}

@media print {
  .no-print {
    display: none !important;
  }

  .phone-table a {
    color: inherit;
    text-decoration: none;
  }
}
</style>
