<script setup lang="ts">
// One person in the org chart, with their direct reports in a collapsible list.
import { computed } from 'vue'
import UserAvatar from './UserAvatar.vue'
import { t } from '@/lib/i18n'
import type { DirectoryEntry } from '@/lib/types'

defineOptions({ name: 'OrgNode' })

const props = defineProps<{ person: DirectoryEntry; reportsOf: Map<number, DirectoryEntry[]>; open: boolean }>()
const reports = computed(() => props.reportsOf.get(props.person.id) ?? [])
const teamLabel = computed(() => (reports.value.length === 1 ? t('people.teamOne') : t('people.team', { count: reports.value.length })))
</script>

<template>
  <li class="org-item">
    <details v-if="reports.length" :open="open || undefined" class="org-branch">
      <summary class="org-card">
        <UserAvatar :id="person.id" :name="person.full_name" :photo-version="person.photo_version" :size="40" class="org-avatar" />
        <span class="org-name">{{ person.full_name }}</span>
        <span class="muted small">{{ person.job_title }}<template v-if="person.job_title && person.department"> · </template>{{ person.department }}</span>
        <span class="org-team small">{{ teamLabel }}</span>
      </summary>
      <ul class="org-children">
        <OrgNode v-for="child in reports" :key="child.id" :person="child" :reports-of="reportsOf" :open="open" />
      </ul>
    </details>
    <div v-else class="org-card leaf">
      <UserAvatar :id="person.id" :name="person.full_name" :photo-version="person.photo_version" :size="40" class="org-avatar" />
      <span class="org-name">{{ person.full_name }}</span>
      <span class="muted small">{{ person.job_title }}<template v-if="person.job_title && person.department"> · </template>{{ person.department }}</span>
    </div>
  </li>
</template>

<style scoped>
.org-item {
  list-style: none;
}

.org-card {
  display: grid;
  grid-template-columns: auto 1fr;
  column-gap: var(--space-3);
  gap: 2px;
  padding: var(--space-3) var(--space-4);
  margin: var(--space-2) 0;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  max-width: 420px;
}

summary.org-card {
  cursor: pointer;
  list-style: none;
  position: relative;
  padding-right: var(--space-6);
}

summary.org-card::-webkit-details-marker {
  display: none;
}

summary.org-card::after {
  content: '';
  position: absolute;
  right: var(--space-4);
  top: 22px;
  width: 8px;
  height: 8px;
  border-right: 2px solid var(--color-text-muted);
  border-bottom: 2px solid var(--color-text-muted);
  transform: rotate(45deg);
}

.org-branch[open] > summary.org-card::after {
  transform: rotate(-135deg);
  top: 26px;
}

.org-name {
  font-weight: 650;
}

.org-team {
  color: var(--color-primary-text);
  font-weight: 600;
}

.org-children {
  margin: 0 0 0 var(--space-4);
  padding: 0 0 0 var(--space-4);
  border-left: 2px solid var(--color-border);
}
</style>

<style scoped>
.org-avatar {
  grid-row: span 3;
  align-self: center;
}

.org-card > :not(.org-avatar) {
  grid-column: 2;
}
</style>
