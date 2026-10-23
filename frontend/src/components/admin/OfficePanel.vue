<script setup lang="ts">
/** Whether office files open in the craft apps (WordCraft, DeckCraft, GridCraft) or in the office server
 * (ONLYOFFICE, optional). */
import { onMounted, ref } from 'vue'
import { api } from '@/lib/api'
import { errorText, t } from '@/lib/i18n'
import { loadCraftConfig, loadOfficeConfig } from '@/lib/spaces'
import { showToast } from '@/lib/toast'
import type { OfficeConfig } from '@/lib/types'

const config = ref<OfficeConfig | null>(null)

async function choose(change: { engine?: string; prefer_craft?: boolean }) {
  try {
    config.value = await api.put<OfficeConfig>('/api/office/config', change)
    loadCraftConfig()
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
    <fieldset v-if="config.craft?.length" class="engines">
      <legend class="label">{{ t('officeAdmin.wordPowerPoint') }}</legend>
      <label class="radio">
        <input type="radio" name="office-craft" :checked="config.prefer_craft" @change="choose({ prefer_craft: true })" />
        <span><strong>{{ t('officeAdmin.craft') }}</strong><span class="muted small block">{{ t('officeAdmin.about.craft') }}</span></span>
      </label>
      <label class="radio">
        <input type="radio" name="office-craft" :checked="!config.prefer_craft" :disabled="!config.engines.length" @change="choose({ prefer_craft: false })" />
        <span><strong>{{ t('officeAdmin.officeEditor') }}</strong><span class="muted small block">{{ t('officeAdmin.about.officeEditor') }}</span></span>
      </label>
    </fieldset>
    <p v-if="!config.engines.length && !config.craft?.length" class="notice notice-info small">{{ t('officeAdmin.none') }}</p>
    <fieldset v-if="config.engines.length" class="engines">
      <legend class="label">{{ t('officeAdmin.default') }}</legend>
      <label v-for="e in config.engines" :key="e" class="radio">
        <input type="radio" name="office-engine" :value="e" :checked="config.default === e" @change="choose({ engine: e })" />
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
