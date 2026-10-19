<script setup lang="ts">
// HR manages the external tools shown in the menu under "More tools".
import { onMounted, reactive, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import FormField from '@/components/FormField.vue'
import { api } from '@/lib/api'
import { loadPortal } from '@/lib/portal'
import { errorText, t } from '@/lib/i18n'
import { showToast } from '@/lib/toast'
import type { QuickLink } from '@/lib/types'

const ICONS = ['link', 'book', 'graduation', 'clock', 'lifebuoy', 'workflow', 'tasks', 'chart', 'mail'] as const

const links = ref<QuickLink[]>([])
const editorOpen = ref(false)
const editing = ref<QuickLink | null>(null)
const form = reactive({ title: '', url: 'https://', icon: 'link', description: '', sort_order: 0, active: true })
const errors = reactive({ title: '', url: '' })
const saving = ref(false)
const deleteTarget = ref<QuickLink | null>(null)

async function load() {
  links.value = await api.get<QuickLink[]>('/api/portal/links?include_inactive=true').catch(() => [])
}

function openEditor(link: QuickLink | null) {
  editing.value = link
  Object.assign(form, link ?? { title: '', url: 'https://', icon: 'link', description: '', sort_order: (links.value.at(-1)?.sort_order ?? -1) + 1, active: true })
  errors.title = errors.url = ''
  editorOpen.value = true
}

async function save() {
  errors.title = form.title.trim() ? '' : t('validation.title_required')
  errors.url = /^https?:\/\/[^\s<>"']+$/.test(form.url.trim()) ? '' : t('validation.url_invalid')
  if (errors.title || errors.url) return
  saving.value = true
  try {
    const body = { ...form, title: form.title.trim(), url: form.url.trim(), description: form.description.trim() }
    if (editing.value) await api.patch(`/api/portal/links/${editing.value.id}`, body)
    else await api.post('/api/portal/links', body)
    editorOpen.value = false
    showToast(t('admin.linkSaved'))
    await Promise.all([load(), loadPortal(true)])
  } catch (e) {
    errors.url = errorText(e)
  } finally {
    saving.value = false
  }
}

async function remove() {
  if (!deleteTarget.value) return
  saving.value = true
  try {
    await api.delete(`/api/portal/links/${deleteTarget.value.id}`)
    deleteTarget.value = null
    showToast(t('admin.linkDeleted'))
    await Promise.all([load(), loadPortal(true)])
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="stack">
    <p class="muted small">{{ t('admin.linksHint') }}</p>
    <ul v-if="links.length" class="link-list">
      <li v-for="link in links" :key="link.id" :class="{ inactive: !link.active }">
        <AppIcon :name="link.icon" />
        <span class="grow">
          <span class="link-title">{{ link.title }}</span>
          <span class="muted small url">{{ link.url }}</span>
        </span>
        <button type="button" class="btn btn-ghost" @click="openEditor(link)">{{ t('app.edit') }}</button>
        <button type="button" class="btn btn-ghost danger-text" @click="deleteTarget = link">{{ t('admin.remove') }}</button>
      </li>
    </ul>
    <div><button type="button" class="btn btn-secondary" @click="openEditor(null)"><AppIcon name="plus" />{{ t('admin.addLink') }}</button></div>

    <BaseModal :open="editorOpen" :title="editing ? t('admin.editLink') : t('admin.addLink')" :confirm-label="t('app.save')" :busy="saving" wide @close="editorOpen = false" @confirm="save">
      <form class="stack" novalidate @submit.prevent="save">
        <div class="grid-2">
          <FormField id="l-title" :label="t('admin.linkTitle')" :error="errors.title">
            <template #default="{ attrs }"><input v-bind="attrs" v-model="form.title" class="input" maxlength="60" /></template>
          </FormField>
          <FormField id="l-icon" :label="t('admin.linkIcon')">
            <template #default="{ attrs }">
              <select v-bind="attrs" v-model="form.icon" class="select">
                <option v-for="icon in ICONS" :key="icon" :value="icon">{{ t(`linkIcons.${icon}`) }}</option>
              </select>
            </template>
          </FormField>
        </div>
        <FormField id="l-url" :label="t('admin.linkUrl')" :error="errors.url">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.url" class="input" type="url" maxlength="500" /></template>
        </FormField>
        <FormField id="l-description" :label="t('admin.linkDescription')" optional>
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.description" class="input" maxlength="200" /></template>
        </FormField>
        <div class="grid-2">
          <FormField id="l-order" :label="t('admin.linkOrder')">
            <template #default="{ attrs }"><input v-bind="attrs" v-model.number="form.sort_order" class="input" type="number" min="0" max="1000" /></template>
          </FormField>
          <label class="checkbox active-check"><input v-model="form.active" type="checkbox" /><span>{{ t('admin.linkActive') }}</span></label>
        </div>
      </form>
    </BaseModal>

    <BaseModal
      :open="deleteTarget !== null"
      :title="t('admin.deleteLinkTitle')"
      :description="t('admin.deleteLinkText', { title: deleteTarget?.title ?? '' })"
      :confirm-label="t('admin.remove')"
      tone="danger"
      :busy="saving"
      @close="deleteTarget = null"
      @confirm="remove"
    />
  </div>
</template>

<style scoped>
.link-list {
  list-style: none;
  margin: 0;
  padding: 0;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.link-list li {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-2) var(--space-2) var(--space-4);
}

.link-list li + li {
  border-top: 1px solid var(--color-border);
}

.inactive {
  opacity: 0.6;
}

.grow {
  flex: 1;
  display: grid;
  min-width: 0;
}

.link-title {
  font-weight: 600;
}

.url {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.active-check {
  align-self: end;
}

.danger-text {
  color: var(--color-danger);
}
</style>
