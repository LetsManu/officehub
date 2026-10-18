<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api } from '@/lib/api'
import { errorText, formatDate, formatDateLong, t } from '@/lib/i18n'
import type { Announcement } from '@/lib/types'

const route = useRoute()
const items = ref<Announcement[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    items.value = await api.get<Announcement[]>('/api/announcements')
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
  // Coming from the dashboard: scroll to the announcement that was clicked.
  if (route.hash) {
    await nextTick()
    const target = document.querySelector<HTMLElement>(route.hash)
    target?.scrollIntoView({ block: 'start' })
    target?.focus({ preventScroll: true })
  }
}

onMounted(load)
</script>

<template>
  <div class="page news-page">
    <PageHeader :title="t('announcements.title')" :subtitle="t('announcements.subtitle')" />
    <LoadState :loading="loading" :error="error" @retry="load">
      <div v-if="items.length" class="stack">
        <article v-for="item in items" :id="`a-${item.id}`" :key="item.id" class="card news" :class="{ pinned: item.pinned }" tabindex="-1" :aria-labelledby="`a-${item.id}-title`">
          <div class="row tags">
            <span v-if="item.pinned" class="tag tag-pinned"><AppIcon name="pin" :size="14" />{{ t('announcements.pinned') }}</span>
            <span class="tag">{{ t(`announcements.categories.${item.category}`) }}</span>
            <span class="muted small">{{ t('announcements.published', { date: formatDate(item.publish_date) }) }}</span>
          </div>
          <h2 :id="`a-${item.id}-title`">{{ item.title }}</h2>
          <p v-if="item.event_date" class="event"><AppIcon name="calendar" :size="18" />{{ t('announcements.eventOn', { date: formatDateLong(item.event_date) }) }}</p>
          <p class="prewrap body">{{ item.body }}</p>
        </article>
      </div>
      <section v-else class="card">
        <EmptyState icon="megaphone" :message="t('announcements.empty')" />
      </section>
    </LoadState>
  </div>
</template>

<style scoped>
.news-page {
  max-width: 860px;
}

.news {
  display: grid;
  gap: var(--space-3);
  scroll-margin-top: 80px;
}

.news.pinned {
  border-color: color-mix(in srgb, var(--color-primary) 40%, var(--color-border));
}

.tags {
  gap: var(--space-2);
}

.tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 10px;
  border-radius: 999px;
  background: var(--color-neutral-soft);
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  font-weight: 600;
}

.tag-pinned {
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
}

.event {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-weight: 600;
  color: var(--color-primary-text);
}

.body {
  color: var(--color-text);
}
</style>
