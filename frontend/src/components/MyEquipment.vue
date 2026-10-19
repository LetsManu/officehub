<script setup lang="ts">
/** Read-only list of the equipment handed out to the signed-in person. */
import { onMounted, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import { api } from '@/lib/api'
import { ASSET_ICONS } from '@/lib/assets'
import { formatDate, t } from '@/lib/i18n'
import type { Asset } from '@/lib/types'

const items = ref<Asset[] | null>(null)

onMounted(async () => {
  items.value = await api.get<Asset[]>('/api/assets/mine').catch(() => [])
})
</script>

<template>
  <div v-if="items">
    <ul v-if="items.length" class="list items">
      <li v-for="item in items" :key="item.id" class="item">
        <span class="kind-icon"><AppIcon :name="ASSET_ICONS[item.kind] ?? 'box'" :size="18" /></span>
        <span class="grow">
          <strong>{{ item.name }}</strong>
          <span class="muted small"> · {{ t(`assets.kinds.${item.kind}`) }}<template v-if="item.serial"> · {{ item.serial }}</template></span>
        </span>
        <span v-if="item.assigned_at" class="muted small">{{ t('assets.since', { date: formatDate(item.assigned_at) }) }}</span>
      </li>
    </ul>
    <p v-else class="muted">{{ t('assets.noneMine') }}</p>
  </div>
</template>


<style scoped>
.items {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.item {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2) var(--space-3);
  padding: var(--space-3) var(--space-4);
}

.kind-icon {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  background: var(--color-neutral-soft);
  color: var(--color-text-muted);
}

.grow {
  flex: 1;
}
</style>
