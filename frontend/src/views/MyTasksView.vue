<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api } from '@/lib/api'
import { errorText, formatDate, t } from '@/lib/i18n'
import type { MyCard } from '@/lib/types'

const cards = ref<MyCard[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const today = new Date().toISOString().slice(0, 10)
const weekEnd = (() => {
  const d = new Date()
  d.setDate(d.getDate() + 7)
  return d.toISOString().slice(0, 10)
})()

const groups = computed(() => {
  const late = cards.value.filter((c) => c.due_date && c.due_date < today)
  const now = cards.value.filter((c) => c.due_date && c.due_date >= today && c.due_date <= weekEnd)
  const later = cards.value.filter((c) => c.due_date && c.due_date > weekEnd)
  const open = cards.value.filter((c) => !c.due_date)
  return [
    { key: 'late', items: late },
    { key: 'week', items: now },
    { key: 'later', items: later },
    { key: 'noDate', items: open },
  ].filter((g) => g.items.length)
})

async function load() {
  try {
    cards.value = await api.get<MyCard[]>('/api/boards/mine')
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
    <PageHeader :title="t('tasks.title')" :subtitle="t('tasks.subtitle')" />
    <LoadState :loading="loading" :error="error" @retry="load">
      <template v-if="groups.length">
        <section v-for="g in groups" :key="g.key" class="card card-flush" :aria-labelledby="`tg-${g.key}`">
          <h2 :id="`tg-${g.key}`" class="h4 group" :class="{ late: g.key === 'late' }">{{ t(`tasks.groups.${g.key}`) }} <span class="muted">({{ g.items.length }})</span></h2>
          <ul class="list">
            <li v-for="c in g.items" :key="c.id">
              <RouterLink :to="`/spaces/${c.space_id}/board?card=${c.id}`" class="list-link">
                <span class="ficon" :class="c.label ? `pc-${c.label}` : 'pc-slate'"><AppIcon name="kanban" :size="18" /></span>
                <span class="main">
                  <span class="name">{{ c.title }}</span>
                  <span class="muted small">{{ c.space_name }} · {{ c.column }}</span>
                </span>
                <span v-if="c.due_date" class="due small" :class="{ late: c.due_date < today }"><AppIcon name="calendar" :size="14" />{{ formatDate(c.due_date) }}</span>
              </RouterLink>
            </li>
          </ul>
        </section>
      </template>
      <section v-else class="card"><EmptyState icon="checkCircle" :message="t('tasks.empty')" /></section>
    </LoadState>
  </div>
</template>

<style scoped>
.group {
  padding: var(--space-4) var(--space-5) var(--space-2);
}

.group.late {
  color: var(--color-warning);
}

.main {
  display: grid;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.name {
  font-weight: 600;
}

.due {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--color-text-muted);
  font-weight: 600;
  white-space: nowrap;
}

.due.late {
  color: var(--color-warning);
}
</style>
