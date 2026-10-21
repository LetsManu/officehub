<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import EmptyState from '@/components/EmptyState.vue'
import FormField from '@/components/FormField.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api, query } from '@/lib/api'
import { errorText, formatDateTime, t } from '@/lib/i18n'
import { PROJECT_COLORS } from '@/lib/planning'
import { showToast } from '@/lib/toast'
import type { Space } from '@/lib/types'

const router = useRouter()
const spaces = ref<Space[]>([])
const archived = ref(false)
const search = ref('')
const loading = ref(true)
const error = ref<string | null>(null)
const busy = ref(false)
const createOpen = ref(false)
const form = reactive({ name: '', description: '', color: 'blue' })
const errors = reactive<Record<string, string>>({})

const shown = computed(() => {
  const term = search.value.trim().toLowerCase()
  return term ? spaces.value.filter((s) => `${s.name} ${s.description}`.toLowerCase().includes(term)) : spaces.value
})

async function load() {
  loading.value = spaces.value.length === 0
  error.value = null
  try {
    spaces.value = await api.get<Space[]>(`/api/spaces${query({ archived: archived.value ? 'true' : '' })}`)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, { name: '', description: '', color: PROJECT_COLORS[spaces.value.length % PROJECT_COLORS.length] })
  for (const key of Object.keys(errors)) delete errors[key]
  createOpen.value = true
}

async function create() {
  for (const key of Object.keys(errors)) delete errors[key]
  if (!form.name.trim()) errors.name = t('validation.name_required')
  if (Object.keys(errors).length) return
  busy.value = true
  try {
    const space = await api.post<Space>('/api/spaces', { name: form.name.trim(), description: form.description.trim(), color: form.color })
    createOpen.value = false
    showToast(t('spaces.created'))
    router.push(`/spaces/${space.id}`)
  } catch (e) {
    errors.form = errorText(e)
  } finally {
    busy.value = false
  }
}

watch(archived, load)
onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader :title="t('spaces.title')" :subtitle="t('spaces.subtitle')">
      <template #actions>
        <button type="button" class="btn btn-primary" @click="openCreate"><AppIcon name="plus" />{{ t('spaces.new') }}</button>
      </template>
    </PageHeader>

    <div class="filters" role="search">
      <div class="search-box">
        <label for="sp-search" class="visually-hidden">{{ t('spaces.search') }}</label>
        <AppIcon name="search" class="search-icon" />
        <input id="sp-search" v-model="search" class="input" type="search" :placeholder="t('spaces.search')" autocomplete="off" />
      </div>
      <label class="checkbox">
        <input v-model="archived" type="checkbox" />
        <span>{{ t('spaces.showArchived') }}</span>
      </label>
    </div>

    <LoadState :loading="loading" :error="error" @retry="load">
      <ul v-if="shown.length" class="grid" role="list">
        <li v-for="s in shown" :key="s.id">
          <RouterLink :to="`/spaces/${s.id}`" class="space-card" :class="`pc-${s.color}`">
            <span class="badge" aria-hidden="true">{{ s.name.slice(0, 1).toUpperCase() }}</span>
            <span class="body">
              <span class="name">{{ s.name }}</span>
              <span v-if="s.description" class="desc muted small">{{ s.description }}</span>
              <span class="stats small">
                <span><AppIcon name="users" :size="15" />{{ t('spaces.members', { n: s.member_count }) }}</span>
                <span><AppIcon name="folder" :size="15" />{{ t('spaces.files', { n: s.file_count }) }}</span>
                <span><AppIcon name="kanban" :size="15" />{{ t('spaces.openCards', { n: s.open_cards }) }}</span>
              </span>
              <span v-if="s.updated_at" class="muted tiny">{{ t('spaces.updated', { date: formatDateTime(s.updated_at) }) }}</span>
            </span>
            <span v-if="s.unread" class="unread" :aria-label="t('spaces.unread', { n: s.unread })">{{ s.unread }}</span>
          </RouterLink>
        </li>
      </ul>
      <section v-else class="card">
        <EmptyState icon="spaces" :message="search ? t('spaces.noMatch') : t('spaces.empty')" :action-label="search ? undefined : t('spaces.new')" @action="openCreate" />
      </section>
    </LoadState>

    <BaseModal :open="createOpen" :title="t('spaces.new')" :description="t('spaces.newHint')" :confirm-label="t('spaces.create')" :busy="busy" @close="createOpen = false" @confirm="create">
      <form class="stack" novalidate @submit.prevent="create">
        <div v-if="errors.form" class="notice notice-danger small" role="alert">{{ errors.form }}</div>
        <FormField id="sp-name" :label="t('spaces.name')" :error="errors.name">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.name" class="input" maxlength="80" :placeholder="t('spaces.namePlaceholder')" /></template>
        </FormField>
        <FormField id="sp-desc" :label="t('spaces.description')" optional>
          <template #default="{ attrs }"><textarea v-bind="attrs" v-model="form.description" class="textarea" rows="2" maxlength="300" /></template>
        </FormField>
        <fieldset class="swatches">
          <legend>{{ t('projects.color') }}</legend>
          <label v-for="c in PROJECT_COLORS" :key="c" class="swatch" :class="`pc-${c}`">
            <input v-model="form.color" type="radio" name="sp-color" :value="c" />
            <span class="dot" aria-hidden="true"><AppIcon v-if="form.color === c" name="check" :size="16" /></span>
            <span class="visually-hidden">{{ t(`projects.colors.${c}`) }}</span>
          </label>
        </fieldset>
      </form>
    </BaseModal>
  </div>
</template>

<style scoped>
.filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3) var(--space-5);
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
  gap: var(--space-4);
  margin: 0;
  padding: 0;
  list-style: none;
}

.space-card {
  position: relative;
  display: flex;
  gap: var(--space-4);
  height: 100%;
  padding: var(--space-5);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: var(--shadow-card);
  color: var(--color-text);
  text-decoration: none;
  transition: border-color var(--t-fast) ease, box-shadow var(--t-fast) ease, transform var(--t-fast) ease;
}

.space-card:hover {
  border-color: var(--color-border-strong);
  box-shadow: var(--shadow-hover);
  transform: translateY(-1px);
}

.space-card::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 4px;
  border-radius: var(--radius-lg) 0 0 var(--radius-lg);
  background: var(--pc);
}

.badge {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 44px;
  height: 44px;
  border-radius: var(--radius-md);
  background: var(--pc);
  color: #fff;
  font-family: var(--font-heading);
  font-size: var(--text-lg);
  font-weight: 700;
}

.body {
  display: grid;
  align-content: start;
  gap: 6px;
  min-width: 0;
}

.name {
  font-family: var(--font-heading);
  font-size: var(--text-lg);
  font-weight: 600;
}

.desc {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.stats {
  display: flex;
  flex-wrap: wrap;
  gap: 4px var(--space-4);
  color: var(--color-text-muted);
}

.stats > span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.tiny {
  font-size: 0.75rem;
}

.unread {
  position: absolute;
  top: var(--space-3);
  right: var(--space-3);
  display: grid;
  place-items: center;
  min-width: 22px;
  height: 22px;
  padding: 0 6px;
  border-radius: 99px;
  background: var(--color-badge);
  color: var(--color-on-badge);
  font-size: 0.75rem;
  font-weight: 700;
}

</style>
