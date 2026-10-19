<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import EmptyState from '@/components/EmptyState.vue'
import FormField from '@/components/FormField.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import SortHeader from '@/components/SortHeader.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import { api, query } from '@/lib/api'
import { ASSET_ICONS, ASSET_KINDS } from '@/lib/assets'
import { errorText, formatDate, formatDateTime, t } from '@/lib/i18n'
import { useSort } from '@/lib/sort'
import { showToast } from '@/lib/toast'
import type { Asset, User } from '@/lib/types'

const STATUSES = ['in_stock', 'assigned', 'repair', 'retired'] as const

const assets = ref<Asset[]>([])
const people = ref<User[]>([])
const search = ref('')
const status = ref('')
const loading = ref(true)
const error = ref<string | null>(null)
const busy = ref(false)

const assetSort = useSort(assets, {
  name: (a) => a.name,
  kind: (a) => a.kind,
  status: (a) => STATUSES.indexOf(a.status),
  person: (a) => a.assigned_to?.full_name ?? '',
}, 'name')

const editorOpen = ref(false)
const editing = ref<Asset | null>(null)
const form = reactive({ name: '', kind: 'laptop', serial: '', notes: '', status: 'in_stock' })
const formError = ref('')
const assignFor = ref<Asset | null>(null)
const assignPerson = ref<number | null>(null)
const assignError = ref('')
const detail = ref<Asset | null>(null)

let timer: number | undefined

async function load() {
  loading.value = assets.value.length === 0
  error.value = null
  try {
    assets.value = await api.get<Asset[]>(`/api/assets${query({ q: search.value.trim(), status: status.value })}`)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

function openEditor(asset: Asset | null) {
  editing.value = asset
  Object.assign(form, asset
    ? { name: asset.name, kind: asset.kind, serial: asset.serial, notes: asset.notes, status: asset.status }
    : { name: '', kind: 'laptop', serial: '', notes: '', status: 'in_stock' })
  formError.value = ''
  editorOpen.value = true
}

async function save() {
  formError.value = form.name.trim() ? '' : t('validation.name_required')
  if (formError.value) return
  busy.value = true
  try {
    const body = { name: form.name.trim(), kind: form.kind, serial: form.serial.trim(), notes: form.notes.trim() }
    if (editing.value) {
      await api.put(`/api/assets/${editing.value.id}`, { ...body, ...(form.status !== 'assigned' ? { status: form.status } : {}) })
    } else {
      await api.post('/api/assets', body)
    }
    editorOpen.value = false
    showToast(t('assets.saved'))
    await load()
  } catch (e) {
    formError.value = errorText(e)
  } finally {
    busy.value = false
  }
}

function openAssign(asset: Asset) {
  assignFor.value = asset
  assignPerson.value = null
  assignError.value = ''
}

async function assign() {
  if (!assignFor.value) return
  assignError.value = assignPerson.value ? '' : t('validation.person_required')
  if (assignError.value) return
  busy.value = true
  try {
    await api.post(`/api/assets/${assignFor.value.id}/assign`, { person_id: assignPerson.value })
    assignFor.value = null
    showToast(t('assets.assigned'))
    await load()
  } catch (e) {
    assignError.value = errorText(e)
  } finally {
    busy.value = false
  }
}

async function giveBack(asset: Asset) {
  try {
    await api.post(`/api/assets/${asset.id}/return`, {})
    showToast(t('assets.returned'))
    await load()
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

async function showHistory(asset: Asset) {
  detail.value = await api.get<Asset>(`/api/assets/${asset.id}`)
}

watch(status, load)
watch(search, () => {
  window.clearTimeout(timer)
  timer = window.setTimeout(load, 250)
})

onMounted(async () => {
  load()
  people.value = (await api.get<User[]>('/api/admin/users').catch(() => [])).filter((p) => p.is_active)
})
</script>

<template>
  <div class="page">
    <PageHeader :title="t('assets.title')" :subtitle="t('assets.subtitle')">
      <template #actions>
        <button type="button" class="btn btn-primary" @click="openEditor(null)"><AppIcon name="plus" />{{ t('assets.new') }}</button>
      </template>
    </PageHeader>

    <div class="filters" role="search">
      <div class="search-box">
        <label for="as-search" class="visually-hidden">{{ t('assets.search') }}</label>
        <AppIcon name="search" class="search-icon" />
        <input id="as-search" v-model="search" class="input" type="search" :placeholder="t('assets.searchPlaceholder')" autocomplete="off" />
      </div>
      <div>
        <label for="as-status" class="visually-hidden">{{ t('assets.status') }}</label>
        <select id="as-status" v-model="status" class="select">
          <option value="">{{ t('assets.allStatuses') }}</option>
          <option v-for="s in STATUSES" :key="s" :value="s">{{ t(`assets.statuses.${s}`) }}</option>
        </select>
      </div>
    </div>

    <LoadState :loading="loading" :error="error" @retry="load">
      <section v-if="assets.length" class="card card-flush">
        <div class="table-wrap table-scroll">
          <table class="table table-sticky">
            <thead>
              <tr>
                <th scope="col" :aria-sort="assetSort.ariaSort('name')"><SortHeader :label="t('assets.name')" :active="assetSort.key.value === 'name'" :dir="assetSort.dir.value" @sort="assetSort.toggle('name')" /></th>
                <th scope="col" :aria-sort="assetSort.ariaSort('kind')"><SortHeader :label="t('assets.kind')" :active="assetSort.key.value === 'kind'" :dir="assetSort.dir.value" @sort="assetSort.toggle('kind')" /></th>
                <th scope="col" :aria-sort="assetSort.ariaSort('status')"><SortHeader :label="t('assets.status')" :active="assetSort.key.value === 'status'" :dir="assetSort.dir.value" @sort="assetSort.toggle('status')" /></th>
                <th scope="col" :aria-sort="assetSort.ariaSort('person')"><SortHeader :label="t('assets.person')" :active="assetSort.key.value === 'person'" :dir="assetSort.dir.value" @sort="assetSort.toggle('person')" /></th>
                <th scope="col"><span class="visually-hidden">{{ t('assets.actions') }}</span></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="a in assetSort.sorted.value" :key="a.id">
                <td>
                  <span class="name">
                    <span class="kind-icon"><AppIcon :name="ASSET_ICONS[a.kind] ?? 'box'" :size="16" /></span>
                    <span>
                      <strong>{{ a.name }}</strong>
                      <span v-if="a.serial" class="muted small serial">{{ a.serial }}</span>
                    </span>
                  </span>
                </td>
                <td>{{ t(`assets.kinds.${a.kind}`) }}</td>
                <td><span class="status" :class="`s-${a.status}`">{{ t(`assets.statuses.${a.status}`) }}</span></td>
                <td>
                  <span v-if="a.assigned_to" class="name">
                    <UserAvatar :id="a.assigned_to.id" :name="a.assigned_to.full_name" :photo-version="a.assigned_to.photo_version" :size="26" />
                    <span>{{ a.assigned_to.full_name }}<span v-if="a.assigned_at" class="muted small serial">{{ t('assets.since', { date: formatDate(a.assigned_at) }) }}</span></span>
                  </span>
                  <span v-else class="muted">–</span>
                </td>
                <td class="actions">
                  <button v-if="a.status === 'in_stock'" type="button" class="btn btn-secondary" @click="openAssign(a)">{{ t('assets.handOut') }}</button>
                  <button v-if="a.status === 'assigned'" type="button" class="btn btn-ghost" @click="giveBack(a)">{{ t('assets.takeBack') }}</button>
                  <button type="button" class="btn btn-ghost btn-icon" :aria-label="`${t('assets.history')}: ${a.name}`" @click="showHistory(a)"><AppIcon name="history" :size="18" /></button>
                  <button type="button" class="btn btn-ghost btn-icon" :aria-label="`${t('app.edit')}: ${a.name}`" @click="openEditor(a)"><AppIcon name="edit" :size="18" /></button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      <section v-else class="card"><EmptyState icon="box" :message="t('assets.empty')" :action-label="t('assets.new')" @action="openEditor(null)" /></section>
    </LoadState>

    <BaseModal :open="editorOpen" :title="editing ? t('assets.edit') : t('assets.new')" :confirm-label="t('app.save')" :busy="busy" @close="editorOpen = false" @confirm="save">
      <form class="stack" novalidate @submit.prevent="save">
        <div v-if="formError" class="notice notice-danger small" role="alert">{{ formError }}</div>
        <FormField id="as-name" :label="t('assets.name')">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.name" class="input" maxlength="120" :placeholder="t('assets.namePlaceholder')" /></template>
        </FormField>
        <div class="grid-2">
          <FormField id="as-kind" :label="t('assets.kind')">
            <template #default="{ attrs }">
              <select v-bind="attrs" v-model="form.kind" class="select">
                <option v-for="k in ASSET_KINDS" :key="k" :value="k">{{ t(`assets.kinds.${k}`) }}</option>
              </select>
            </template>
          </FormField>
          <FormField id="as-serial" :label="t('assets.serial')" optional>
            <template #default="{ attrs }"><input v-bind="attrs" v-model="form.serial" class="input" maxlength="80" /></template>
          </FormField>
        </div>
        <FormField v-if="editing && editing.status !== 'assigned'" id="as-status-set" :label="t('assets.status')">
          <template #default="{ attrs }">
            <select v-bind="attrs" v-model="form.status" class="select">
              <option v-for="s in ['in_stock', 'repair', 'retired']" :key="s" :value="s">{{ t(`assets.statuses.${s}`) }}</option>
            </select>
          </template>
        </FormField>
        <FormField id="as-notes" :label="t('assets.notes')" optional>
          <template #default="{ attrs }"><textarea v-bind="attrs" v-model="form.notes" class="textarea" rows="2" maxlength="500" /></template>
        </FormField>
      </form>
    </BaseModal>

    <BaseModal :open="assignFor !== null" :title="t('assets.handOutTitle', { name: assignFor?.name ?? '' })" :confirm-label="t('assets.handOut')" :busy="busy" @close="assignFor = null" @confirm="assign">
      <FormField id="as-person" :label="t('assets.person')" :error="assignError">
        <template #default="{ attrs }">
          <select v-bind="attrs" v-model="assignPerson" class="select">
            <option :value="null">{{ t('personalDocs.choosePerson') }}</option>
            <option v-for="p in people" :key="p.id" :value="p.id">{{ p.full_name }} · {{ p.department }}</option>
          </select>
        </template>
      </FormField>
    </BaseModal>

    <BaseModal :open="detail !== null" :title="detail?.name ?? ''" :description="detail?.serial ?? ''" hide-actions @close="detail = null">
      <ol v-if="detail" class="history">
        <li v-for="(e, i) in detail.history" :key="i">
          <span class="h-dot" aria-hidden="true" />
          <span>
            <strong>{{ t(`assets.events.${e.action}`) }}</strong>
            <template v-if="e.person_name"> · {{ e.person_name }}</template>
            <span class="muted small h-meta">{{ formatDateTime(e.created_at) }} · {{ e.actor_name }}<template v-if="e.note"> · {{ e.note }}</template></span>
          </span>
        </li>
      </ol>
    </BaseModal>
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

.name {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}

.serial {
  display: block;
}

.kind-icon {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: var(--radius-sm);
  background: var(--color-neutral-soft);
  color: var(--color-text-muted);
  flex-shrink: 0;
}

.status {
  padding: 2px 10px;
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: 700;
  white-space: nowrap;
  background: var(--color-neutral-soft);
  color: var(--color-text-muted);
}

.s-in_stock {
  background: var(--color-success-soft);
  color: var(--color-success);
}

.s-assigned {
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
}

.s-repair {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}

.actions {
  white-space: nowrap;
  text-align: right;
}

.history {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-3);
}

.history li {
  display: flex;
  gap: var(--space-3);
}

.h-dot {
  width: 10px;
  height: 10px;
  margin-top: 7px;
  border-radius: 50%;
  background: var(--color-primary);
  flex-shrink: 0;
}

.h-meta {
  display: block;
}

@media (max-width: 640px) {
  .filters {
    grid-template-columns: 1fr;
  }
}
</style>
