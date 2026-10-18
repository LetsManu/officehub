<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'
import PageHeader from '@/components/PageHeader.vue'
import { REQUEST_TYPES, TYPE_ICONS } from '@/lib/requestTypes'
import { t } from '@/lib/i18n'
</script>

<template>
  <div class="page">
    <PageHeader :title="t('requests.chooseTitle')" :subtitle="t('requests.chooseSubtitle')" back-to="/requests" />
    <ul class="types">
      <li v-for="type in REQUEST_TYPES" :key="type">
        <RouterLink :to="`/requests/new/${type}`" class="type-card">
          <span class="type-icon"><AppIcon :name="TYPE_ICONS[type]" :size="22" /></span>
          <span class="type-text">
            <span class="type-name">{{ t(`requestTypes.${type}`) }}</span>
            <span class="muted small">{{ t(`requestTypeHints.${type}`) }}</span>
          </span>
          <AppIcon name="chevronRight" class="chevron" />
        </RouterLink>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.types {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-3);
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 320px), 1fr));
}

.type-card {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  height: 100%;
  min-height: 88px;
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  color: var(--color-text);
  text-decoration: none;
}

.type-card:hover {
  border-color: var(--color-primary);
}

.type-icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: var(--radius-md);
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
  flex-shrink: 0;
}

.type-text {
  display: grid;
  gap: 2px;
  flex: 1;
}

.type-name {
  font-weight: 600;
}

.chevron {
  color: var(--color-text-muted);
}
</style>
