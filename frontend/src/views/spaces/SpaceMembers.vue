<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import FormField from '@/components/FormField.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import { api } from '@/lib/api'
import { errorText, t } from '@/lib/i18n'
import { PROJECT_COLORS } from '@/lib/planning'
import { currentUser } from '@/lib/session'
import { useSpace } from '@/lib/spaceContext'
import { showToast } from '@/lib/toast'
import type { DirectoryEntry, Project, SpaceDetail } from '@/lib/types'

const { space, reload } = useSpace()
const router = useRouter()
const people = ref<DirectoryEntry[]>([])
const projects = ref<Project[]>([])
const addPerson = ref<number | ''>('')
const addRole = ref<'member' | 'manager'>('member')
const busy = ref(false)
const form = reactive({ name: '', description: '', color: 'blue', project_id: null as number | null })
const formError = ref('')
const confirm = ref<'leave' | 'archive' | 'delete' | null>(null)

const isManager = computed(() => space.value?.my_role === 'manager')
const candidates = computed(() => people.value.filter((p) => !space.value?.members.some((m) => m.person.id === p.id)))

function fill() {
  if (!space.value) return
  Object.assign(form, { name: space.value.name, description: space.value.description, color: space.value.color, project_id: space.value.project_id })
}

async function add() {
  if (!addPerson.value) return
  busy.value = true
  try {
    space.value = await api.post<SpaceDetail>(`/api/spaces/${space.value!.id}/members`, { user_id: addPerson.value, role: addRole.value })
    addPerson.value = ''
    showToast(t('spaces.memberAdded'))
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    busy.value = false
  }
}

async function setRole(userId: number, role: string) {
  try {
    space.value = await api.post<SpaceDetail>(`/api/spaces/${space.value!.id}/members`, { user_id: userId, role })
  } catch (e) {
    showToast(errorText(e), 'error')
    await reload()
  }
}

async function remove(userId: number) {
  try {
    await api.delete(`/api/spaces/${space.value!.id}/members/${userId}`)
    if (userId === currentUser.value?.id) {
      router.push('/spaces')
      return
    }
    await reload()
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

async function saveSettings(archived = space.value?.archived ?? false) {
  formError.value = form.name.trim() ? '' : t('validation.name_required')
  if (formError.value) return
  busy.value = true
  try {
    await api.put(`/api/spaces/${space.value!.id}`, { ...form, name: form.name.trim(), description: form.description.trim(), archived })
    await reload()
    fill()
    showToast(t('spaces.saved'))
  } catch (e) {
    formError.value = errorText(e)
  } finally {
    busy.value = false
  }
}

async function confirmAction() {
  const action = confirm.value
  confirm.value = null
  if (action === 'leave') await remove(currentUser.value!.id)
  if (action === 'archive') await saveSettings(!space.value!.archived)
  if (action === 'delete') {
    try {
      await api.delete(`/api/spaces/${space.value!.id}`)
      showToast(t('spaces.deleted'))
      router.push('/spaces')
    } catch (e) {
      showToast(errorText(e), 'error')
    }
  }
}

onMounted(async () => {
  fill()
  ;[people.value, projects.value] = await Promise.all([
    api.get<DirectoryEntry[]>('/api/directory'),
    api.get<Project[]>('/api/planning/projects').catch(() => []),
  ])
})
</script>

<template>
  <div v-if="space" class="members-page">
    <section class="card card-flush" aria-labelledby="mem-title">
      <h2 id="mem-title" class="h3 head">{{ t('spaces.tabs.members') }} <span class="muted">({{ space.members.length }})</span></h2>
      <ul class="list">
        <li v-for="m in space.members" :key="m.person.id" class="member">
          <UserAvatar :id="m.person.id" :name="m.person.full_name" :photo-version="m.person.photo_version" :size="36" status />
          <span class="who"><strong>{{ m.person.full_name }}</strong><span class="muted small">{{ m.person.department }}</span></span>
          <template v-if="isManager && !space.archived">
            <label :for="`role-${m.person.id}`" class="visually-hidden">{{ t('spaces.role') }}</label>
            <select :id="`role-${m.person.id}`" class="select role" :value="m.role" @change="setRole(m.person.id, ($event.target as HTMLSelectElement).value)">
              <option value="member">{{ t('spaces.roles.member') }}</option>
              <option value="manager">{{ t('spaces.roles.manager') }}</option>
            </select>
            <button v-if="m.person.id !== currentUser?.id" type="button" class="btn btn-ghost btn-icon" :aria-label="t('spaces.removeMember', { name: m.person.full_name })" @click="remove(m.person.id)"><AppIcon name="close" :size="18" /></button>
          </template>
          <span v-else class="tag">{{ t(`spaces.roles.${m.role}`) }}</span>
        </li>
      </ul>
      <form v-if="isManager && !space.archived" class="add" @submit.prevent="add">
        <label for="mem-add" class="visually-hidden">{{ t('spaces.addPerson') }}</label>
        <select id="mem-add" v-model.number="addPerson" class="select">
          <option value="">{{ t('spaces.addPerson') }}</option>
          <option v-for="p in candidates" :key="p.id" :value="p.id">{{ p.full_name }}<template v-if="p.department"> · {{ p.department }}</template></option>
        </select>
        <label for="mem-role" class="visually-hidden">{{ t('spaces.role') }}</label>
        <select id="mem-role" v-model="addRole" class="select role">
          <option value="member">{{ t('spaces.roles.member') }}</option>
          <option value="manager">{{ t('spaces.roles.manager') }}</option>
        </select>
        <button type="submit" class="btn btn-primary" :disabled="!addPerson || busy"><AppIcon name="plus" :size="18" />{{ t('spaces.add') }}</button>
      </form>
      <p class="muted small hint">{{ t('spaces.rolesHint') }}</p>
    </section>

    <section v-if="isManager" class="card stack" aria-labelledby="set-title">
      <h2 id="set-title" class="h3">{{ t('spaces.settings') }}</h2>
      <div v-if="formError" class="notice notice-danger small" role="alert">{{ formError }}</div>
      <FormField id="set-name" :label="t('spaces.name')">
        <template #default="{ attrs }"><input v-bind="attrs" v-model="form.name" class="input" maxlength="80" :disabled="space.archived" /></template>
      </FormField>
      <FormField id="set-desc" :label="t('spaces.description')" optional>
        <template #default="{ attrs }"><textarea v-bind="attrs" v-model="form.description" class="textarea" rows="2" maxlength="300" :disabled="space.archived" /></template>
      </FormField>
      <FormField v-if="projects.length" id="set-project" :label="t('spaces.project')" :hint="t('spaces.projectHint')" optional>
        <template #default="{ attrs }">
          <select v-bind="attrs" v-model="form.project_id" class="select" :disabled="space.archived">
            <option :value="null">{{ t('spaces.noProject') }}</option>
            <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
        </template>
      </FormField>
      <fieldset class="swatches">
        <legend>{{ t('projects.color') }}</legend>
        <label v-for="c in PROJECT_COLORS" :key="c" class="swatch" :class="`pc-${c}`">
          <input v-model="form.color" type="radio" name="set-color" :value="c" :disabled="space.archived" />
          <span class="dot" aria-hidden="true"><AppIcon v-if="form.color === c" name="check" :size="16" /></span>
          <span class="visually-hidden">{{ t(`projects.colors.${c}`) }}</span>
        </label>
      </fieldset>
      <div class="row">
        <button v-if="!space.archived" type="button" class="btn btn-primary" :disabled="busy" @click="saveSettings()">{{ t('app.save') }}</button>
        <button type="button" class="btn btn-secondary" @click="confirm = 'archive'"><AppIcon name="archive" :size="18" />{{ space.archived ? t('spaces.unarchive') : t('spaces.archive') }}</button>
        <button v-if="space.archived" type="button" class="btn btn-ghost danger-text" @click="confirm = 'delete'"><AppIcon name="trash" :size="18" />{{ t('spaces.delete') }}</button>
      </div>
    </section>

    <section v-if="space.members.some((m) => m.person.id === currentUser?.id)" class="card">
      <button type="button" class="btn btn-ghost danger-text" @click="confirm = 'leave'"><AppIcon name="logout" :size="18" />{{ t('spaces.leave') }}</button>
    </section>

    <BaseModal
      :open="confirm !== null"
      :title="confirm ? t(`spaces.confirm.${confirm}.title`, { name: space.name }) : ''"
      :description="confirm ? t(`spaces.confirm.${confirm}.text`) : ''"
      :confirm-label="confirm ? t(`spaces.confirm.${confirm}.button`) : ''"
      :tone="confirm === 'archive' ? 'primary' : 'danger'"
      @close="confirm = null"
      @confirm="confirmAction"
    />
  </div>
</template>

<style scoped>
.members-page {
  display: grid;
  gap: var(--space-4);
  max-width: 820px;
}

.head {
  padding: var(--space-4) var(--space-5) var(--space-2);
}

.member {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-5);
}

.who {
  display: grid;
  flex: 1;
  min-width: 0;
}

.role {
  width: auto;
}

.tag {
  padding: 2px 10px;
  border-radius: 99px;
  background: var(--color-neutral-soft);
  font-size: 0.78rem;
  font-weight: 600;
}

.add {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-5);
  border-top: 1px solid var(--color-border);
}

.add .select:first-of-type {
  flex: 1;
  min-width: 200px;
}

.hint {
  padding: 0 var(--space-5) var(--space-4);
}

.danger-text {
  color: var(--color-danger);
}
</style>
