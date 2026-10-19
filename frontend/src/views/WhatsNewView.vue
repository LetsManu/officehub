<script setup lang="ts">
import PageHeader from '@/components/PageHeader.vue'
import { CHANGELOG } from '@/lib/changelog'
import { publicConfig } from '@/lib/session'
import { formatDate, language, t } from '@/lib/i18n'
</script>

<template>
  <div class="page news-page">
    <PageHeader :title="t('whatsNew.title')" :subtitle="t('whatsNew.subtitle', { version: publicConfig?.version ?? '–' })" back-to="/" />
    <article v-for="entry in CHANGELOG" :key="entry.version" class="card stack-sm">
      <h2>{{ t('whatsNew.version', { version: entry.version }) }}</h2>
      <p class="muted small">{{ formatDate(entry.date) }}</p>
      <ul class="changes">
        <li v-for="line in entry[language]" :key="line">{{ line }}</li>
      </ul>
    </article>
  </div>
</template>

<style scoped>
.news-page {
  max-width: 760px;
}

.changes {
  margin: var(--space-2) 0 0;
  padding-left: var(--space-5);
  display: grid;
  gap: var(--space-2);
}
</style>
