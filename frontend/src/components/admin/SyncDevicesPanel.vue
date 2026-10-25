<script setup lang="ts">
/** Every computer with the OfficeHub folder (Windows app): who, which computer, when it last synced, problems. */
import { onMounted, ref } from 'vue'
import EmptyState from '@/components/EmptyState.vue'
import SyncStatusBadge from '@/components/SyncStatusBadge.vue'
import { api } from '@/lib/api'
import { locale, t } from '@/lib/i18n'
import { lastSynced, problemText, reasonText, syncedText } from '@/lib/syncStatus'
import type { SyncDeviceRow } from '@/lib/types'

const rows = ref<SyncDeviceRow[]>([])
const loaded = ref(false)

onMounted(async () => {
  rows.value = await api.get<SyncDeviceRow[]>('/api/sync/devices').catch(() => [])
  loaded.value = true
})
</script>

<template>
  <div class="stack">
    <p class="muted">{{ t('syncDevices.intro') }}</p>
    <EmptyState v-if="loaded && !rows.length" icon="folder" :message="t('syncDevices.empty')" />
    <div v-else-if="rows.length" class="table-wrap table-scroll">
      <table class="table">
        <thead>
          <tr>
            <th scope="col">{{ t('syncDevices.person') }}</th>
            <th scope="col">{{ t('syncDevices.device') }}</th>
            <th scope="col">{{ t('syncDevices.lastSync') }}</th>
            <th scope="col">{{ t('syncDevices.state') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td>{{ row.full_name }}</td>
            <td>
              {{ row.device_name || row.password_name }}
              <span v-if="row.device_name && row.device_name !== row.password_name" class="muted small block">{{ row.password_name }}</span>
            </td>
            <td>
              <span v-if="lastSynced(row)">{{ syncedText(row, locale) }}</span>
              <span v-else class="muted">{{ t('syncDevices.notYet') }}</span>
              <span v-if="!row.reports" class="muted small block">{{ t('syncDevices.oldApp') }}</span>
            </td>
            <td>
              <SyncStatusBadge :status="row.status" />
              <span v-if="problemText(row)" class="problem small block">{{ problemText(row) }}</span>
              <span v-if="row.pending_uploads" class="muted small block">{{ t('syncDevices.waiting', { count: row.pending_uploads }) }}</span>
              <details v-if="row.failed.length || row.last_error" class="small details">
                <summary>{{ t('syncFolder.errorDetails') }}</summary>
                <ul class="failed">
                  <li v-for="f in row.failed" :key="f.path">{{ f.path }} – {{ reasonText(f.reason) }}</li>
                </ul>
                <code v-if="row.last_error">{{ row.last_error }}</code>
                <span v-if="row.app_version" class="muted block">{{ row.app_version }}</span>
              </details>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.block {
  display: block;
}

.problem {
  margin-top: var(--space-1);
  color: var(--color-warning);
}

.details {
  margin-top: var(--space-1);
}

.failed {
  margin: var(--space-1) 0;
  padding-left: var(--space-4);
  overflow-wrap: anywhere;
}

code {
  overflow-wrap: anywhere;
}
</style>
