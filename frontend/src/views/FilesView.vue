<script setup lang="ts">
/** All my files in one place, like "Files" in Teams: last changed in my spaces, plus the company documents. */
import { computed, onMounted, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api } from '@/lib/api'
import { errorText, formatDateTime, t } from '@/lib/i18n'
import { fileIcon, fileSize, fileTone, isOffice } from '@/lib/spaces'
import type { SpaceFile } from '@/lib/types'

type RecentFile = SpaceFile & { space_name: string }

const files = ref<RecentFile[]>([])
const search = ref('')
const loading = ref(true)
const error = ref<string | null>(null)

const shown = computed(() => {
  const term = search.value.trim().toLowerCase()
  return term ? files.value.filter((f) => `${f.name} ${f.space_name}`.toLowerCase().includes(term)) : files.value
})

async function load() {
  error.value = null
  try {
    files.value = await api.get<RecentFile[]>('/api/spaces/files/recent?limit=60')
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader :title="t('filesPage.title')" :subtitle="t('filesPage.subtitle')" />

    <div class="shortcuts">
      <RouterLink to="/documents" class="card shortcut">
        <span class="sc-icon"><AppIcon name="file" /></span>
        <span><strong>{{ t('filesPage.company') }}</strong><span class="muted small block">{{ t('filesPage.companyHint') }}</span></span>
      </RouterLink>
      <RouterLink to="/documents?tab=mine" class="card shortcut">
        <span class="sc-icon"><AppIcon name="lock" /></span>
        <span><strong>{{ t('filesPage.personal') }}</strong><span class="muted small block">{{ t('filesPage.personalHint') }}</span></span>
      </RouterLink>
      <RouterLink to="/spaces" class="card shortcut">
        <span class="sc-icon"><AppIcon name="spaces" /></span>
        <span><strong>{{ t('filesPage.spaces') }}</strong><span class="muted small block">{{ t('filesPage.spacesHint') }}</span></span>
      </RouterLink>
    </div>

    <section class="card card-flush" aria-labelledby="recent-title">
      <div class="head">
        <h2 id="recent-title" class="h3">{{ t('filesPage.recent') }}</h2>
        <div class="search-box">
          <label for="files-search" class="visually-hidden">{{ t('filesPage.search') }}</label>
          <AppIcon name="search" class="search-icon" />
          <input id="files-search" v-model="search" class="input" type="search" :placeholder="t('filesPage.search')" autocomplete="off" />
        </div>
      </div>
      <LoadState :loading="loading" :error="error" @retry="load">
        <ul v-if="shown.length" class="list">
          <li v-for="f in shown" :key="f.id" class="file">
            <span class="ficon" :class="`pc-${fileTone(f.file_type)}`"><AppIcon :name="fileIcon(f.file_type)" :size="18" /></span>
            <RouterLink :to="isOffice(f.file_type) ? `/office/${f.id}` : `/spaces/${f.space_id}/files?file=${f.id}`" class="fname">
              <span class="name">{{ f.name }}</span>
              <span class="muted small">{{ f.space_name }} · {{ f.updated_by }} · {{ formatDateTime(f.updated_at) }} · {{ fileSize(f.size) }}</span>
            </RouterLink>
            <RouterLink :to="`/spaces/${f.space_id}/files?file=${f.id}`" class="btn btn-ghost btn-icon" :aria-label="t('filesPage.showInSpace', { space: f.space_name })" :title="t('filesPage.showInSpace', { space: f.space_name })"><AppIcon name="folder" :size="18" /></RouterLink>
            <a class="btn btn-ghost btn-icon" :href="`/api/spaces/files/${f.id}/download`" download :aria-label="t('files.download')"><AppIcon name="download" :size="18" /></a>
          </li>
        </ul>
        <EmptyState v-else icon="folder" :message="search ? t('filesPage.noMatch') : t('filesPage.empty')" action-to="/spaces" :action-label="search ? undefined : t('filesPage.spaces')" />
      </LoadState>
    </section>
  </div>
</template>

<style scoped>
.shortcuts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.shortcut {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  color: inherit;
  text-decoration: none;
}

.shortcut:hover strong {
  color: var(--color-primary);
}

.sc-icon {
  display: grid;
  width: 40px;
  height: 40px;
  flex: none;
  place-items: center;
  border-radius: 10px;
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
}

.block {
  display: block;
}

.head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
}

.head .search-box {
  position: relative;
  width: min(320px, 100%);
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

.file {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-5);
}

.ficon {
  display: grid;
  width: 36px;
  height: 36px;
  flex: none;
  place-items: center;
  border-radius: 8px;
}

.fname {
  display: grid;
  flex: 1;
  min-width: 0;
  color: inherit;
  text-decoration: none;
}

.fname:hover .name {
  color: var(--color-primary);
  text-decoration: underline;
}

.name {
  overflow: hidden;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
