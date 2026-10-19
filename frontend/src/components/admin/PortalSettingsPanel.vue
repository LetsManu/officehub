<script setup lang="ts">
// HR settings: which quick actions appear on the dashboard (and their order), and contact people per section.
import { computed, onMounted, reactive, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import { api } from '@/lib/api'
import { loadPortal, portalSettings } from '@/lib/portal'
import { errorText, t } from '@/lib/i18n'
import { DEFAULT_TILES, TILES, tileByKey } from '@/lib/tiles'
import { showToast } from '@/lib/toast'
import type { PortalSettings, User } from '@/lib/types'

const props = defineProps<{ people: User[] }>()

const SECTIONS = ['dashboard', 'requests', 'documents', 'announcements', 'directory', 'rooms', 'visitors', 'time'] as const

const selected = ref<string[]>([])
const contacts = reactive<Record<string, number | ''>>({})
const saving = ref(false)

const unselected = computed(() => TILES.filter((tile) => !selected.value.includes(tile.key)))
const activePeople = computed(() => props.people.filter((p) => p.is_active))

function apply(settings: PortalSettings) {
  selected.value = settings.dashboard_tiles.length ? [...settings.dashboard_tiles] : [...DEFAULT_TILES]
  for (const section of SECTIONS) contacts[section] = settings.section_contacts[section]?.id ?? ''
}

function move(index: number, delta: number) {
  const list = [...selected.value]
  const [item] = list.splice(index, 1)
  list.splice(index + delta, 0, item)
  selected.value = list
}

async function save() {
  saving.value = true
  try {
    const result = await api.put<PortalSettings>('/api/portal/settings', {
      dashboard_tiles: selected.value,
      section_contacts: Object.fromEntries(SECTIONS.map((s) => [s, contacts[s] === '' ? null : contacts[s]])),
    })
    portalSettings.value = result
    apply(result)
    showToast(t('admin.portalSaved'))
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await loadPortal(true)
  apply(portalSettings.value)
})
</script>

<template>
  <div class="stack">
    <section class="stack-sm" aria-labelledby="tiles-title">
      <h3 id="tiles-title">{{ t('admin.tiles') }}</h3>
      <p class="muted small">{{ t('admin.tilesHint') }}</p>
      <ol class="tile-list">
        <li v-for="(key, index) in selected" :key="key">
          <AppIcon :name="tileByKey(key)?.icon ?? 'link'" />
          <span class="grow">{{ t(tileByKey(key)?.label ?? key) }}</span>
          <button type="button" class="btn btn-ghost btn-icon" :disabled="index === 0" :aria-label="t('admin.moveUp', { name: t(tileByKey(key)?.label ?? key) })" @click="move(index, -1)">
            <AppIcon name="arrowUp" />
          </button>
          <button type="button" class="btn btn-ghost btn-icon" :disabled="index === selected.length - 1" :aria-label="t('admin.moveDown', { name: t(tileByKey(key)?.label ?? key) })" @click="move(index, 1)">
            <AppIcon name="arrowDown" />
          </button>
          <button type="button" class="btn btn-ghost btn-icon" :disabled="selected.length === 1" :aria-label="`${t('admin.remove')}: ${t(tileByKey(key)?.label ?? key)}`" @click="selected = selected.filter((k) => k !== key)">
            <AppIcon name="close" />
          </button>
        </li>
      </ol>
      <div v-if="unselected.length && selected.length < 8" class="row add-tiles">
        <button v-for="tile in unselected" :key="tile.key" type="button" class="btn btn-secondary" @click="selected = [...selected, tile.key]">
          <AppIcon name="plus" :size="16" />{{ t(tile.label) }}
        </button>
      </div>
    </section>

    <section class="stack-sm" aria-labelledby="contacts-title">
      <h3 id="contacts-title">{{ t('admin.contacts') }}</h3>
      <p class="muted small">{{ t('admin.contactsHint') }}</p>
      <div class="contact-grid">
        <div v-for="section in SECTIONS" :key="section" class="field">
          <label :for="`contact-${section}`" class="label">{{ t(`sections.${section}`) }}</label>
          <select :id="`contact-${section}`" v-model="contacts[section]" class="select">
            <option value="">{{ t('admin.noContact') }}</option>
            <option v-for="p in activePeople" :key="p.id" :value="p.id">{{ p.full_name }}</option>
          </select>
        </div>
      </div>
    </section>

    <div class="form-actions"><button type="button" class="btn btn-primary" :disabled="saving" @click="save">{{ saving ? t('app.saving') : t('app.save') }}</button></div>
  </div>
</template>

<style scoped>
.tile-list {
  list-style: none;
  margin: 0;
  padding: 0;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.tile-list li {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-2) 0 var(--space-4);
  min-height: 52px;
}

.tile-list li + li {
  border-top: 1px solid var(--color-border);
}

.grow {
  flex: 1;
}

.add-tiles {
  gap: var(--space-2);
}

.contact-grid {
  display: grid;
  gap: var(--space-3) var(--space-4);
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 220px), 1fr));
}

.field {
  display: grid;
  gap: 6px;
}

.label {
  font-weight: 600;
  font-size: var(--text-sm);
}
</style>
