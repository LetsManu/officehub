<script setup lang="ts">
/** Which office server opens Word, Excel and PowerPoint files (Collabora Online or ONLYOFFICE). */
import { onMounted, ref } from 'vue'
import { api } from '@/lib/api'
import { errorText, t } from '@/lib/i18n'
import { loadOfficeConfig } from '@/lib/spaces'
import { showToast } from '@/lib/toast'
import type { OfficeConfig } from '@/lib/types'

const config = ref<OfficeConfig | null>(null)

async function choose(engine: string) {
  try {
    config.value = await api.put<OfficeConfig>('/api/office/config', { engine })
    await loadOfficeConfig(true)
    showToast(t('officeAdmin.saved'))
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

onMounted(async () => {
  config.value = await loadOfficeConfig(true)
})
</script>

<template>
  <div v-if="config" class="stack">
    <p class="muted">{{ t('officeAdmin.intro') }}</p>
    <p v-if="!config.engines.length" class="notice notice-info small">{{ t('officeAdmin.none') }}</p>
    <fieldset v-else class="engines">
      <legend class="label">{{ t('officeAdmin.default') }}</legend>
      <label v-for="e in config.engines" :key="e" class="radio">
        <input type="radio" name="office-engine" :value="e" :checked="config.default === e" @change="choose(e)" />
        <span><strong>{{ t(`office.engines.${e}`) }}</strong><span class="muted small block">{{ t(`officeAdmin.about.${e}`) }}</span></span>
      </label>
    </fieldset>
    <p class="muted small">{{ t('officeAdmin.setupHint') }}</p>
  </div>
</template>

<style scoped>
.engines {
  display: grid;
  gap: var(--space-3);
  margin: 0;
  padding: 0;
  border: 0;
}

.label {
  margin-bottom: var(--space-2);
  font-weight: 600;
}

.radio {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  cursor: pointer;
}

.radio input {
  margin-top: 4px;
}

.block {
  display: block;
}
</style>
