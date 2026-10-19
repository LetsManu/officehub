<script setup lang="ts">
// HR manages the bookable meeting rooms.
import { onMounted, reactive, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import FormField from '@/components/FormField.vue'
import { api } from '@/lib/api'
import { errorText, t } from '@/lib/i18n'
import { showToast } from '@/lib/toast'
import type { Room } from '@/lib/types'

const rooms = ref<Room[]>([])
const editorOpen = ref(false)
const editing = ref<Room | null>(null)
const form = reactive({ name: '', seats: 4, equipment: '', active: true })
const nameError = ref('')
const saving = ref(false)

async function load() {
  rooms.value = await api.get<Room[]>('/api/rooms?include_inactive=true').catch(() => [])
}

function openEditor(room: Room | null) {
  editing.value = room
  Object.assign(form, room ?? { name: '', seats: 4, equipment: '', active: true })
  nameError.value = ''
  editorOpen.value = true
}

async function save() {
  nameError.value = form.name.trim() ? '' : t('validation.name_required')
  if (nameError.value) return
  saving.value = true
  try {
    const body = { ...form, name: form.name.trim(), equipment: form.equipment.trim() }
    if (editing.value) await api.patch(`/api/rooms/${editing.value.id}`, body)
    else await api.post('/api/rooms', body)
    editorOpen.value = false
    showToast(t('admin.roomSaved'))
    await load()
  } catch (e) {
    nameError.value = errorText(e)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="stack">
    <ul v-if="rooms.length" class="room-list">
      <li v-for="room in rooms" :key="room.id" :class="{ inactive: !room.active }">
        <AppIcon name="door" />
        <span class="grow">
          <span class="room-name">{{ room.name }}</span>
          <span class="muted small">{{ t('rooms.seats', { count: room.seats }) }}<template v-if="room.equipment"> · {{ room.equipment }}</template></span>
        </span>
        <button type="button" class="btn btn-ghost" @click="openEditor(room)">{{ t('app.edit') }}</button>
      </li>
    </ul>
    <div><button type="button" class="btn btn-secondary" @click="openEditor(null)"><AppIcon name="plus" />{{ t('admin.addRoom') }}</button></div>

    <BaseModal :open="editorOpen" :title="editing ? t('admin.editRoom') : t('admin.addRoom')" :confirm-label="t('app.save')" :busy="saving" @close="editorOpen = false" @confirm="save">
      <form class="stack" novalidate @submit.prevent="save">
        <FormField id="room-name" :label="t('admin.roomName')" :error="nameError">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.name" class="input" maxlength="80" /></template>
        </FormField>
        <FormField id="room-seats" :label="t('admin.roomSeats')">
          <template #default="{ attrs }"><input v-bind="attrs" v-model.number="form.seats" class="input" type="number" min="1" max="500" /></template>
        </FormField>
        <FormField id="room-equipment" :label="t('admin.roomEquipment')" optional>
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.equipment" class="input" maxlength="200" /></template>
        </FormField>
        <label class="checkbox"><input v-model="form.active" type="checkbox" /><span>{{ t('admin.roomActive') }}</span></label>
      </form>
    </BaseModal>
  </div>
</template>

<style scoped>
.room-list {
  list-style: none;
  margin: 0;
  padding: 0;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.room-list li {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-2) var(--space-2) var(--space-4);
}

.room-list li + li {
  border-top: 1px solid var(--color-border);
}

.inactive {
  opacity: 0.6;
}

.grow {
  flex: 1;
  display: grid;
}

.room-name {
  font-weight: 600;
}
</style>
