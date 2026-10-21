<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadState from '@/components/LoadState.vue'
import { api } from '@/lib/api'
import { errorText, formatDate, formatDateTime, t } from '@/lib/i18n'
import { useSpace } from '@/lib/spaceContext'
import { fileIcon, fileTone } from '@/lib/spaces'
import type { SpaceOverview } from '@/lib/types'

const { space } = useSpace()
const data = ref<SpaceOverview | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const today = new Date().toISOString().slice(0, 10)

async function load() {
  try {
    data.value = await api.get<SpaceOverview>(`/api/spaces/${space.value!.id}/overview`)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <LoadState :loading="loading" :error="error" @retry="load">
    <div v-if="data && space" class="overview">
      <div class="quick">
        <RouterLink :to="`/spaces/${space.id}/files`" class="quick-link"><AppIcon name="upload" />{{ t('spaces.quick.upload') }}</RouterLink>
        <RouterLink :to="`/spaces/${space.id}/board`" class="quick-link"><AppIcon name="plus" />{{ t('spaces.quick.task') }}</RouterLink>
        <RouterLink :to="`/spaces/${space.id}/chat`" class="quick-link"><AppIcon name="chat" />{{ t('spaces.quick.message') }}</RouterLink>
        <RouterLink :to="`/spaces/${space.id}/wiki`" class="quick-link"><AppIcon name="book" />{{ t('spaces.quick.wiki') }}</RouterLink>
      </div>

      <section class="card card-flush" aria-labelledby="ov-files">
        <div class="head"><h2 id="ov-files" class="h3">{{ t('spaces.recentFiles') }}</h2><RouterLink :to="`/spaces/${space.id}/files`" class="small">{{ t('spaces.allFiles') }}</RouterLink></div>
        <ul v-if="data.files.length" class="list">
          <li v-for="f in data.files" :key="f.id">
            <RouterLink :to="`/spaces/${space.id}/files?file=${f.id}`" class="list-link">
              <span class="ficon" :class="`pc-${fileTone(f.file_type)}`"><AppIcon :name="fileIcon(f.file_type)" :size="18" /></span>
              <span class="main"><span class="name">{{ f.name }}</span><span class="muted small">{{ formatDateTime(f.updated_at) }}<template v-if="f.updated_by"> · {{ f.updated_by }}</template></span></span>
            </RouterLink>
          </li>
        </ul>
        <EmptyState v-else icon="folder" :message="t('spaces.noFiles')" />
      </section>

      <section class="card card-flush" aria-labelledby="ov-cards">
        <div class="head"><h2 id="ov-cards" class="h3">{{ t('spaces.openTasks') }}</h2><RouterLink :to="`/spaces/${space.id}/board`" class="small">{{ t('spaces.toBoard') }}</RouterLink></div>
        <ul v-if="data.cards.length" class="list">
          <li v-for="c in data.cards" :key="c.id">
            <RouterLink :to="`/spaces/${space.id}/board?card=${c.id}`" class="list-link">
              <span class="ficon pc-slate"><AppIcon name="kanban" :size="18" /></span>
              <span class="main">
                <span class="name">{{ c.title }}</span>
                <span class="muted small">{{ c.column }}<template v-if="c.assignees.length"> · {{ c.assignees.join(', ') }}</template></span>
              </span>
              <span v-if="c.due_date" class="due small" :class="{ late: c.due_date < today }">{{ formatDate(c.due_date) }}</span>
            </RouterLink>
          </li>
        </ul>
        <EmptyState v-else icon="kanban" :message="t('spaces.noTasks')" />
      </section>

      <section class="card card-flush" aria-labelledby="ov-pages">
        <div class="head"><h2 id="ov-pages" class="h3">{{ t('spaces.wikiPages') }}</h2><RouterLink :to="`/spaces/${space.id}/wiki`" class="small">{{ t('spaces.toWiki') }}</RouterLink></div>
        <ul v-if="data.pages.length" class="list">
          <li v-for="p in data.pages" :key="p.id">
            <RouterLink :to="`/spaces/${space.id}/wiki/${p.id}`" class="list-link">
              <span class="ficon pc-teal"><AppIcon name="book" :size="18" /></span>
              <span class="main"><span class="name">{{ p.title }}</span><span class="muted small">{{ formatDateTime(p.updated_at) }}</span></span>
            </RouterLink>
          </li>
        </ul>
      </section>

      <section class="card card-flush" aria-labelledby="ov-members">
        <div class="head"><h2 id="ov-members" class="h3">{{ t('spaces.tabs.members') }}</h2><RouterLink :to="`/spaces/${space.id}/members`" class="small">{{ t('spaces.manageMembers') }}</RouterLink></div>
        <ul class="list">
          <li v-for="m in space.members" :key="m.person.id" class="member">
            <span class="name">{{ m.person.full_name }}</span>
            <span class="muted small">{{ m.role === 'manager' ? t('spaces.roles.manager') : m.person.department }}</span>
          </li>
        </ul>
      </section>
    </div>
  </LoadState>
</template>

<style scoped>
.overview {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
  gap: var(--space-4);
  align-items: start;
}

.quick {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.quick-link {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 44px;
  padding: 0 var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-text);
  font-weight: 600;
  text-decoration: none;
}

.quick-link:hover {
  border-color: var(--color-border-strong);
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4) var(--space-5) var(--space-2);
}



.main {
  display: grid;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.name {
  font-weight: 600;
  overflow-wrap: anywhere;
}

.due {
  font-weight: 600;
  color: var(--color-text-muted);
}

.due.late {
  color: var(--color-warning);
}

.member {
  display: flex;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-5);
}
</style>
