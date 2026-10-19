<script setup lang="ts">
/** Managers: who decides on my team's requests while I am away. */
import { computed, onMounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import FormField from './FormField.vue'
import { api } from '@/lib/api'
import { errorText, formatDateLong, t } from '@/lib/i18n'
import { currentUser, setUser } from '@/lib/session'
import { showToast } from '@/lib/toast'
import type { DirectoryEntry, User } from '@/lib/types'
import { todayIso } from '@/lib/workdays'

const people = ref<DirectoryEntry[]>([])
const deputyId = ref<number | null>(currentUser.value?.deputy_id ?? null)
const until = ref(currentUser.value?.deputy_until ?? '')
const errors = ref<Record<string, string>>({})
const busy = ref(false)

const active = computed(() => Boolean(currentUser.value?.deputy_id && currentUser.value.deputy_until && currentUser.value.deputy_until >= todayIso()))
const deputyName = computed(() => people.value.find((p) => p.id === currentUser.value?.deputy_id)?.full_name ?? '')

watch(currentUser, (u) => {
  deputyId.value = u?.deputy_id ?? null
  until.value = u?.deputy_until ?? ''
})

async function save(clear = false) {
  errors.value = {}
  if (!clear) {
    if (!deputyId.value) errors.value.deputy_id = t('validation.deputy_invalid')
    if (!until.value) errors.value.until = t('validation.date_required')
    if (Object.keys(errors.value).length) return
  }
  busy.value = true
  try {
    setUser(await api.put<User>('/api/profile/deputy', clear ? { deputy_id: null } : { deputy_id: deputyId.value, until: until.value }))
    showToast(clear ? t('deputy.removed') : t('deputy.saved'))
  } catch (e) {
    const field = (e as { field?: string }).field ?? 'deputy_id'
    errors.value = { [field]: errorText(e) }
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  people.value = (await api.get<DirectoryEntry[]>('/api/directory').catch(() => [])).filter((p) => p.id !== currentUser.value?.id)
})
</script>

<template>
  <div class="stack">
    <p class="muted small">{{ t('deputy.hint') }}</p>
    <div v-if="active" class="notice notice-info small">
      <AppIcon name="users" :size="18" />
      <p>{{ t('deputy.active', { name: deputyName, date: formatDateLong(currentUser?.deputy_until) }) }}</p>
    </div>
    <form class="row deputy-form" novalidate @submit.prevent="save()">
      <FormField id="dep-person" :label="t('deputy.person')" :error="errors.deputy_id">
        <template #default="{ attrs }">
          <select v-bind="attrs" v-model="deputyId" class="select">
            <option :value="null">{{ t('deputy.choose') }}</option>
            <option v-for="p in people" :key="p.id" :value="p.id">{{ p.full_name }} · {{ p.department }}</option>
          </select>
        </template>
      </FormField>
      <FormField id="dep-until" :label="t('deputy.until')" :error="errors.until">
        <template #default="{ attrs }"><input v-bind="attrs" v-model="until" type="date" class="input" :min="todayIso()" /></template>
      </FormField>
      <button type="submit" class="btn btn-primary" :disabled="busy">{{ t('app.save') }}</button>
      <button v-if="currentUser?.deputy_id" type="button" class="btn btn-ghost" :disabled="busy" @click="save(true)">{{ t('deputy.remove') }}</button>
    </form>
  </div>
</template>

<style scoped>
.deputy-form {
  align-items: flex-end;
}

.deputy-form > :first-child {
  flex: 1 1 240px;
}
</style>
