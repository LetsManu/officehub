<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import EmptyState from '@/components/EmptyState.vue'
import FormField from '@/components/FormField.vue'
import LoadState from '@/components/LoadState.vue'
import { api, query } from '@/lib/api'
import { errorText, formatDateTime, t } from '@/lib/i18n'
import { renderMarkdown } from '@/lib/markdown'
import { useSpace } from '@/lib/spaceContext'
import { currentUser } from '@/lib/session'
import { canPreview, craftApp, driveAddresses, fileIcon, fileSize, fileTone, isOffice, loadCraftConfig, loadOfficeConfig, warmCraft, type CraftConfig } from '@/lib/spaces'
import { showToast } from '@/lib/toast'
import type { FileListing, Folder, OfficeConfig, SpaceFile, SpaceFileDetail } from '@/lib/types'

const { space, reload: reloadSpace } = useSpace()
const route = useRoute()
const router = useRouter()

const listing = ref<FileListing | null>(null)
const trash = ref<{ folders: Folder[]; files: SpaceFile[] } | null>(null)
const showTrash = ref(route.query.trash === '1')
const folderId = ref<number | null>(Number(route.query.folder) || null)
const loading = ref(true)
const error = ref<string | null>(null)
const busy = ref(false)
const uploading = ref<string[]>([])
const dragging = ref(false)
const office = ref<OfficeConfig>({ engines: [], default: null, editable: {} })
const fileInput = ref<HTMLInputElement | null>(null)

const canWrite = computed(() => listing.value?.can_write ?? false)
const isManager = computed(() => space.value?.my_role === 'manager')

function editable(f: SpaceFile) {
  if (office.value.prefer_craft && craftFor(f)) return true // opens in WordCraft / DeckCraft
  return office.value.engines.length > 0 && isOffice(f.file_type)
}

// ---------- WordCraft / DeckCraft, check-out and the network drive ----------

const craft = ref<CraftConfig>({ apps: [], types: {} })
const craftFor = (f: SpaceFile) => craftApp(craft.value, f.file_type)

/** Word and PowerPoint open in WordCraft / DeckCraft (one person at a time); this opens the office editor instead,
 * where several people work in the same file at once. */
function canEditTogether(f: SpaceFile) {
  const engine = office.value.default
  return !!office.value.prefer_craft && !!craftFor(f) && !!engine && (office.value.editable[engine] ?? []).includes(f.file_type)
}

/** Open the file in the browser version of WordCraft or DeckCraft (a new tab, like Word online). */
async function openInCraft(f: SpaceFile) {
  const tab = window.open('', '_blank')
  try {
    const opened = await api.post<{ url: string; can_write: boolean }>(`/api/craft/open/${f.id}`)
    if (!opened.can_write) showToast(t('files.craftReadOnly'))
    if (tab) {
      tab.opener = null
      tab.location.href = opened.url
    } else {
      window.location.href = opened.url
    }
  } catch (e) {
    tab?.close()
    showToast(errorText(e), 'error')
  }
}

const checkedOutByOther = (f: SpaceFile) => !!f.checked_out_by_id && f.checked_out_by_id !== currentUser.value?.id

async function toggleCheckout(f: SpaceFile) {
  const out = !!f.checked_out_by_id
  try {
    const updated = await api.post<SpaceFile>(`/api/spaces/files/${f.id}/${out ? 'checkin' : 'checkout'}`)
    showToast(out ? t('files.checkedIn') : t('files.checkedOutToast'))
    if (detail.value?.id === f.id) Object.assign(detail.value, updated)
    await load()
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

const drive = computed(() => (detail.value?.drive_path ? driveAddresses(detail.value.drive_path) : null))

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    showToast(t('files.copied'))
  } catch {
    window.prompt(t('files.copyThis'), text)
  }
}

async function load() {
  loading.value = listing.value === null && trash.value === null
  error.value = null
  try {
    if (showTrash.value) trash.value = await api.get(`/api/spaces/${space.value!.id}/trash`)
    else listing.value = await api.get<FileListing>(`/api/spaces/${space.value!.id}/files${query({ folder_id: folderId.value })}`)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

watch([folderId, showTrash], () => {
  router.replace({ query: { ...(folderId.value ? { folder: String(folderId.value) } : {}), ...(showTrash.value ? { trash: '1' } : {}) } })
  load()
})

// ---------- upload ----------

async function upload(files: FileList | File[]) {
  const list = Array.from(files)
  if (!list.length || !canWrite.value) return
  let ok = 0
  for (const file of list) {
    uploading.value.push(file.name)
    const form = new FormData()
    form.append('file', file)
    if (folderId.value) form.append('folder_id', String(folderId.value))
    try {
      await api.post(`/api/spaces/${space.value!.id}/files`, form)
      ok += 1
    } catch (e) {
      showToast(`${file.name}: ${errorText(e)}`, 'error')
    } finally {
      uploading.value = uploading.value.filter((name) => name !== file.name)
    }
  }
  if (ok) showToast(ok === 1 ? t('files.uploadedOne') : t('files.uploaded', { n: ok }))
  await load()
  reloadSpace()
}

function onPick(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files) upload(input.files)
  input.value = ''
}

function onDrop(event: DragEvent) {
  dragging.value = false
  if (event.dataTransfer?.files?.length) upload(event.dataTransfer.files)
}

// ---------- create ----------

type NewKind = 'folder' | 'docx' | 'xlsx' | 'pptx' | 'md'
const creating = ref<NewKind | null>(null)
const newName = ref('')
const newError = ref('')

function startNew(kind: NewKind) {
  creating.value = kind
  newName.value = ''
  newError.value = ''
  ;(document.activeElement as HTMLElement | null)?.closest('details')?.removeAttribute('open')
}

async function createNew() {
  newError.value = newName.value.trim() ? '' : t('validation.name_required')
  if (newError.value || !creating.value) return
  busy.value = true
  try {
    if (creating.value === 'folder') {
      await api.post(`/api/spaces/${space.value!.id}/folders`, { name: newName.value.trim(), parent_id: folderId.value })
      showToast(t('files.folderCreated'))
    } else {
      const item = await api.post<SpaceFile>(`/api/spaces/${space.value!.id}/files/new`, { kind: creating.value, name: newName.value.trim(), folder_id: folderId.value })
      if (creating.value !== 'md' && office.value.engines.length) {
        creating.value = null
        router.push(`/office/${item.id}`)
        return
      }
      showToast(t('files.created'))
    }
    creating.value = null
    await load()
  } catch (e) {
    newError.value = errorText(e)
  } finally {
    busy.value = false
  }
}

// ---------- open, rename, delete ----------

const preview = ref<SpaceFile | null>(null)
const previewText = ref('')

async function open(f: SpaceFile) {
  if (editable(f)) {
    router.push(`/office/${f.id}`)
  } else if (canPreview(f.file_type)) {
    preview.value = f
    previewText.value = ''
    if (['txt', 'md'].includes(f.file_type)) {
      const response = await fetch(`/api/spaces/files/${f.id}/download?inline=true`, { credentials: 'same-origin' })
      previewText.value = await response.text()
    }
  } else {
    window.location.href = `/api/spaces/files/${f.id}/download`
  }
}

const renaming = ref<SpaceFile | Folder | null>(null)
const renameValue = ref('')
const renameError = ref('')

function startRename(item: SpaceFile | Folder) {
  renaming.value = item
  renameValue.value = 'file_type' in item ? item.name.replace(new RegExp(`\\.${item.file_type}$`), '') : item.name
  renameError.value = ''
}

async function rename() {
  const item = renaming.value
  if (!item) return
  renameError.value = renameValue.value.trim() ? '' : t('validation.name_required')
  if (renameError.value) return
  busy.value = true
  try {
    if ('file_type' in item) await api.put(`/api/spaces/files/${item.id}`, { name: renameValue.value.trim(), folder_id: item.folder_id })
    else await api.put(`/api/spaces/folders/${item.id}`, { name: renameValue.value.trim(), parent_id: item.parent_id })
    renaming.value = null
    await load()
  } catch (e) {
    renameError.value = errorText(e)
  } finally {
    busy.value = false
  }
}

async function remove(item: SpaceFile | Folder) {
  try {
    if ('file_type' in item) await api.delete(`/api/spaces/files/${item.id}`)
    else await api.delete(`/api/spaces/folders/${item.id}`)
    showToast(t('files.trashed', { name: item.name }))
    await load()
    reloadSpace()
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

async function restore(item: SpaceFile | Folder) {
  try {
    if ('file_type' in item) await api.post(`/api/spaces/files/${item.id}/restore`)
    else await api.post(`/api/spaces/folders/${item.id}/restore`)
    showToast(t('files.restored', { name: item.name }))
    await load()
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

const purging = ref<SpaceFile | null>(null)

async function purge() {
  if (!purging.value) return
  busy.value = true
  try {
    await api.delete(`/api/spaces/files/${purging.value.id}/forever`)
    purging.value = null
    await load()
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    busy.value = false
  }
}

// ---------- details and versions ----------

const detail = ref<SpaceFileDetail | null>(null)

async function showDetail(id: number) {
  try {
    detail.value = await api.get<SpaceFileDetail>(`/api/spaces/files/${id}`)
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

async function restoreVersion(number: number) {
  if (!detail.value) return
  try {
    await api.post(`/api/spaces/files/${detail.value.id}/restore-version?version=${number}`)
    showToast(t('files.versionRestored', { n: number }))
    await showDetail(detail.value.id)
    await load()
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

onMounted(async () => {
  loadCraftConfig().then((c) => {
    craft.value = c
    warmCraft(c.apps)
  })
  office.value = await loadOfficeConfig()
  await load()
  const file = Number(route.query.file)
  if (file) showDetail(file)
})
</script>

<template>
  <div class="files stack">
    <div class="toolbar">
      <nav class="path" :aria-label="t('files.location')">
        <button type="button" class="crumb" :class="{ current: !folderId && !showTrash }" @click="showTrash = false; folderId = null">
          <AppIcon name="folder" :size="18" />{{ t('spaces.tabs.files') }}
        </button>
        <template v-if="!showTrash">
          <template v-for="f in listing?.path ?? []" :key="f.id">
            <AppIcon name="chevronRight" :size="14" class="sep" />
            <button type="button" class="crumb" :class="{ current: f.id === folderId }" @click="folderId = f.id">{{ f.name }}</button>
          </template>
        </template>
        <template v-else>
          <AppIcon name="chevronRight" :size="14" class="sep" />
          <span class="crumb current">{{ t('files.trash') }}</span>
        </template>
      </nav>
      <div class="row">
        <button type="button" class="btn btn-ghost" :aria-pressed="showTrash" @click="showTrash = !showTrash">
          <AppIcon name="trash" :size="18" />{{ showTrash ? t('files.backToFiles') : t('files.trash') }}
        </button>
        <template v-if="!showTrash && canWrite">
          <details class="menu">
            <summary class="btn btn-secondary"><AppIcon name="plus" :size="18" />{{ t('files.new') }}</summary>
            <div class="menu-list" role="menu">
              <button type="button" role="menuitem" @click="startNew('folder')"><AppIcon name="folderPlus" :size="18" />{{ t('files.newFolder') }}</button>
              <button type="button" role="menuitem" @click="startNew('docx')"><span class="ficon pc-blue"><AppIcon name="file" :size="16" /></span>{{ t('files.newDocx') }}</button>
              <button type="button" role="menuitem" @click="startNew('xlsx')"><span class="ficon pc-green"><AppIcon name="table" :size="16" /></span>{{ t('files.newXlsx') }}</button>
              <button type="button" role="menuitem" @click="startNew('pptx')"><span class="ficon pc-orange"><AppIcon name="presentation" :size="16" /></span>{{ t('files.newPptx') }}</button>
              <button type="button" role="menuitem" @click="startNew('md')"><span class="ficon pc-slate"><AppIcon name="edit" :size="16" /></span>{{ t('files.newMd') }}</button>
            </div>
          </details>
          <button type="button" class="btn btn-primary" @click="fileInput?.click()"><AppIcon name="upload" :size="18" />{{ t('files.upload') }}</button>
          <input ref="fileInput" type="file" multiple class="visually-hidden" tabindex="-1" aria-hidden="true" @change="onPick" />
        </template>
      </div>
    </div>

    <p v-if="!office.engines.length && !showTrash" class="notice notice-info small">{{ t('files.noOffice') }}</p>

    <LoadState :loading="loading" :error="error" @retry="load">
      <!-- Trash -->
      <section v-if="showTrash" class="card card-flush">
        <p class="muted small trash-hint">{{ t('files.trashHint') }}</p>
        <ul v-if="trash && (trash.folders.length || trash.files.length)" class="list">
          <li v-for="f in trash.folders" :key="`d${f.id}`" class="row-item">
            <span class="ficon pc-slate"><AppIcon name="folder" :size="18" /></span>
            <span class="main"><span class="name">{{ f.name }}</span><span class="muted small">{{ t('files.deletedAt', { date: formatDateTime(f.deleted_at ?? null) }) }}</span></span>
            <button type="button" class="btn btn-secondary" @click="restore(f)">{{ t('files.restore') }}</button>
          </li>
          <li v-for="f in trash.files" :key="`f${f.id}`" class="row-item">
            <span class="ficon" :class="`pc-${fileTone(f.file_type)}`"><AppIcon :name="fileIcon(f.file_type)" :size="18" /></span>
            <span class="main"><span class="name">{{ f.name }}</span><span class="muted small">{{ t('files.deletedAt', { date: formatDateTime(f.deleted_at ?? null) }) }}</span></span>
            <button type="button" class="btn btn-secondary" @click="restore(f)">{{ t('files.restore') }}</button>
            <button v-if="isManager" type="button" class="btn btn-ghost danger-text" @click="purging = f">{{ t('files.deleteForever') }}</button>
          </li>
        </ul>
        <EmptyState v-else icon="trash" :message="t('files.trashEmpty')" />
      </section>

      <!-- Files -->
      <section
        v-else-if="listing"
        class="card card-flush drop"
        :class="{ dragging }"
        @dragover.prevent="canWrite && (dragging = true)"
        @dragleave.self="dragging = false"
        @drop.prevent="onDrop"
      >
        <div v-if="uploading.length" class="uploading small" role="status">
          <AppIcon name="upload" :size="16" />{{ t('files.uploading', { names: uploading.join(', ') }) }}
        </div>
        <div v-if="listing.folders.length || listing.files.length" class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th scope="col">{{ t('files.name') }}</th>
                <th scope="col" class="hide-sm">{{ t('files.changed') }}</th>
                <th scope="col" class="num hide-sm">{{ t('files.size') }}</th>
                <th scope="col"><span class="visually-hidden">{{ t('assets.actions') }}</span></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="f in listing.folders" :key="`d${f.id}`">
                <td>
                  <button type="button" class="name-btn" @click="folderId = f.id">
                    <span class="ficon pc-amber"><AppIcon name="folder" :size="18" /></span>
                    <span class="name">{{ f.name }}</span>
                  </button>
                </td>
                <td class="hide-sm muted">–</td>
                <td class="num hide-sm muted">–</td>
                <td class="actions">
                  <template v-if="canWrite">
                    <button type="button" class="btn btn-ghost btn-icon" :aria-label="`${t('files.rename')}: ${f.name}`" @click="startRename(f)"><AppIcon name="edit" :size="18" /></button>
                    <button type="button" class="btn btn-ghost btn-icon" :aria-label="`${t('files.delete')}: ${f.name}`" @click="remove(f)"><AppIcon name="trash" :size="18" /></button>
                  </template>
                </td>
              </tr>
              <tr v-for="f in listing.files" :key="f.id">
                <td>
                  <button type="button" class="name-btn" @click="open(f)">
                    <span class="ficon" :class="`pc-${fileTone(f.file_type)}`"><AppIcon :name="fileIcon(f.file_type)" :size="18" /></span>
                    <span class="name">{{ f.name }}</span>
                    <span v-if="f.locked" class="tag"><AppIcon name="edit" :size="13" />{{ t('files.beingEdited') }}</span>
                    <span v-if="f.checked_out_by" class="tag" :class="{ mine: !checkedOutByOther(f) }"><AppIcon name="lock" :size="13" />{{ checkedOutByOther(f) ? t('files.checkedOutBy', { name: f.checked_out_by }) : t('files.checkedOutByMe') }}</span>
                  </button>
                </td>
                <td class="hide-sm muted small">{{ formatDateTime(f.updated_at) }}<template v-if="f.updated_by"><br />{{ f.updated_by }}</template></td>
                <td class="num hide-sm muted small">{{ fileSize(f.size) }}</td>
                <td class="actions">
                  <RouterLink v-if="editable(f)" :to="`/office/${f.id}`" class="btn btn-ghost btn-icon" :aria-label="`${t('files.edit')}: ${f.name}`" :title="t('files.edit')"><AppIcon name="edit" :size="18" /></RouterLink>
                  <RouterLink v-if="canEditTogether(f)" :to="`/office/${f.id}?together=1`" class="btn btn-ghost btn-icon" :aria-label="`${t('files.editTogether')}: ${f.name}`" :title="t('files.editTogetherHint')"><AppIcon name="users" :size="18" /></RouterLink>
                  <button v-if="craftFor(f) && !office.prefer_craft" type="button" class="btn btn-ghost btn-icon" :aria-label="`${t(`files.openIn.${craftFor(f)}`)}: ${f.name}`" :title="t(`files.openIn.${craftFor(f)}`)" @click="openInCraft(f)"><AppIcon name="external" :size="18" /></button>
                  <a class="btn btn-ghost btn-icon" :href="`/api/spaces/files/${f.id}/download`" download :aria-label="`${t('files.download')}: ${f.name}`" :title="t('files.download')"><AppIcon name="download" :size="18" /></a>
                  <button type="button" class="btn btn-ghost btn-icon" :aria-label="`${t('files.details')}: ${f.name}`" :title="t('files.details')" @click="showDetail(f.id)"><AppIcon name="history" :size="18" /></button>
                  <template v-if="canWrite">
                    <button type="button" class="btn btn-ghost btn-icon" :aria-label="`${t('files.rename')}: ${f.name}`" :title="t('files.rename')" @click="startRename(f)"><AppIcon name="move" :size="18" /></button>
                    <button type="button" class="btn btn-ghost btn-icon" :aria-label="`${t('files.delete')}: ${f.name}`" :title="t('files.delete')" @click="remove(f)"><AppIcon name="trash" :size="18" /></button>
                  </template>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <EmptyState v-else icon="upload" :message="canWrite ? t('files.emptyDrop') : t('files.empty')" />
        <p v-if="canWrite && (listing.folders.length || listing.files.length)" class="drop-hint muted small">{{ t('files.dropHint') }}</p>
      </section>
    </LoadState>

    <!-- New folder / document -->
    <BaseModal :open="creating !== null" :title="creating ? t(`files.newTitle.${creating}`) : ''" :confirm-label="t('files.create')" :busy="busy" @close="creating = null" @confirm="createNew">
      <form novalidate @submit.prevent="createNew">
        <FormField id="fl-new" :label="t('files.name')" :error="newError">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="newName" class="input" maxlength="120" /></template>
        </FormField>
      </form>
    </BaseModal>

    <!-- Rename -->
    <BaseModal :open="renaming !== null" :title="t('files.rename')" :confirm-label="t('app.save')" :busy="busy" @close="renaming = null" @confirm="rename">
      <form novalidate @submit.prevent="rename">
        <FormField id="fl-rename" :label="t('files.name')" :error="renameError">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="renameValue" class="input" maxlength="190" /></template>
        </FormField>
      </form>
    </BaseModal>

    <!-- Preview -->
    <BaseModal :open="preview !== null" :title="preview?.name ?? ''" wide hide-actions @close="preview = null">
      <div v-if="preview" class="preview">
        <img v-if="['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(preview.file_type)" :src="`/api/spaces/files/${preview.id}/download?inline=true`" :alt="preview.name" />
        <iframe v-else-if="preview.file_type === 'pdf'" :src="`/api/spaces/files/${preview.id}/download?inline=true`" :title="preview.name" />
        <!-- eslint-disable-next-line vue/no-v-html -- renderMarkdown escapes HTML first -->
        <div v-else-if="preview.file_type === 'md'" class="markdown" v-html="renderMarkdown(previewText)" />
        <pre v-else class="text">{{ previewText }}</pre>
        <a class="btn btn-secondary" :href="`/api/spaces/files/${preview.id}/download`" download><AppIcon name="download" :size="18" />{{ t('files.download') }}</a>
      </div>
    </BaseModal>

    <!-- Versions -->
    <BaseModal :open="detail !== null" :title="detail?.name ?? ''" wide hide-actions @close="detail = null">
      <section v-if="detail" class="detail-block">
        <h3 class="h4">{{ t('files.checkOutTitle') }}</h3>
        <p class="muted small">
          <template v-if="detail.checked_out_by">{{ checkedOutByOther(detail) ? t('files.checkedOutSince', { name: detail.checked_out_by, when: formatDateTime(detail.checked_out_at ?? '') }) : t('files.checkedOutMine') }}</template>
          <template v-else>{{ t('files.checkOutHint') }}</template>
        </p>
        <button v-if="canWrite && (!checkedOutByOther(detail) || isManager)" type="button" class="btn btn-secondary" @click="toggleCheckout(detail)">
          <AppIcon name="lock" :size="18" />{{ detail.checked_out_by ? (checkedOutByOther(detail) ? t('files.checkInForce') : t('files.checkIn')) : t('files.checkOut') }}
        </button>
      </section>
      <section v-if="detail && drive" class="detail-block">
        <h3 class="h4">{{ t('files.onComputer') }}</h3>
        <p class="muted small">{{ t('files.onComputerHint') }}</p>
        <div class="address">
          <span class="small">{{ t('files.windowsPath') }}</span>
          <code>{{ drive.windows }}</code>
          <button type="button" class="btn btn-ghost btn-icon" :aria-label="t('files.copy')" :title="t('files.copy')" @click="copy(drive.windows)"><AppIcon name="clipboard" :size="16" /></button>
        </div>
        <div class="address">
          <span class="small">{{ t('files.otherPath') }}</span>
          <code>{{ drive.web }}</code>
          <button type="button" class="btn btn-ghost btn-icon" :aria-label="t('files.copy')" :title="t('files.copy')" @click="copy(drive.web)"><AppIcon name="clipboard" :size="16" /></button>
        </div>
        <RouterLink to="/profile#programs" class="small">{{ t('files.appPasswordLink') }}</RouterLink>
      </section>
      <h3 v-if="detail" class="h4 versions-title">{{ t('files.versions') }}</h3>
      <p v-if="detail" class="muted small">{{ t('files.versionsHint') }}</p>
      <ol v-if="detail" class="versions">
        <li v-for="v in detail.versions" :key="v.number">
          <span class="vnum">v{{ v.number }}</span>
          <span class="main">
            <span>{{ t(`files.sources.${v.source}`) }}<template v-if="v.created_by"> · {{ v.created_by }}</template></span>
            <span class="muted small">{{ formatDateTime(v.created_at) }} · {{ fileSize(v.size) }}</span>
          </span>
          <span v-if="v.number === detail.version" class="tag current-tag">{{ t('files.current') }}</span>
          <a class="btn btn-ghost btn-icon" :href="`/api/spaces/files/${detail.id}/download?version=${v.number}`" download :aria-label="t('files.downloadVersion', { n: v.number })"><AppIcon name="download" :size="18" /></a>
          <button v-if="v.number !== detail.version && canWrite" type="button" class="btn btn-ghost" @click="restoreVersion(v.number)">{{ t('files.restoreVersion') }}</button>
        </li>
      </ol>
    </BaseModal>

    <BaseModal
      :open="purging !== null"
      :title="t('files.deleteForeverTitle', { name: purging?.name ?? '' })"
      :description="t('files.deleteForeverText')"
      :confirm-label="t('files.deleteForever')"
      tone="danger"
      :busy="busy"
      @close="purging = null"
      @confirm="purge"
    />
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.path {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px;
  min-width: 0;
}

.crumb {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 36px;
  padding: 0 var(--space-2);
  border: 0;
  border-radius: var(--radius-sm);
  background: none;
  color: var(--color-text-muted);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}

.crumb:hover {
  background: var(--color-neutral-soft);
}

.crumb.current {
  color: var(--color-text);
}

.sep {
  color: var(--color-text-subtle);
}

.menu {
  position: relative;
}

.tag.mine {
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
}

.detail-block {
  display: grid;
  justify-items: start;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
  padding-bottom: var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.address {
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
}

.address code {
  overflow-wrap: anywhere;
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  background: var(--color-surface-muted);
  font-size: 0.82rem;
}

.versions-title {
  margin-bottom: 2px;
}

@media (max-width: 560px) {
  .address {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .address span {
    grid-column: 1 / -1;
  }
}

.menu summary {
  list-style: none;
}

.menu summary::-webkit-details-marker {
  display: none;
}

.menu-list {
  position: absolute;
  right: 0;
  z-index: var(--z-popover);
  display: grid;
  min-width: 230px;
  margin-top: 6px;
  padding: 6px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-raised);
  box-shadow: var(--shadow-hover);
}

.menu-list button {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-height: 42px;
  padding: 0 var(--space-3);
  border: 0;
  border-radius: var(--radius-sm);
  background: none;
  color: var(--color-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.menu-list button:hover,
.menu-list button:focus-visible {
  background: var(--color-neutral-soft);
}


.menu-list .ficon {
  width: 26px;
  height: 26px;
}


.drop {
  position: relative;
  transition: box-shadow 150ms ease-out;
}

.drop.dragging {
  box-shadow: 0 0 0 3px var(--color-primary);
}

.uploading {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-5);
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
}

.name-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-3);
  max-width: 100%;
  padding: 0;
  border: 0;
  background: none;
  color: var(--color-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.name-btn:hover .name {
  text-decoration: underline;
}

.name {
  font-weight: 600;
  overflow-wrap: anywhere;
}

.tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 8px;
  border-radius: 99px;
  background: var(--color-warning-soft);
  color: var(--color-warning);
  font-size: 0.75rem;
  font-weight: 600;
  white-space: nowrap;
}

.actions {
  white-space: nowrap;
  text-align: right;
}

.drop-hint {
  padding: var(--space-3) var(--space-5);
  border-top: 1px dashed var(--color-border);
  text-align: center;
}

.trash-hint {
  padding: var(--space-3) var(--space-5) 0;
}

.row-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-5);
}

.main {
  display: grid;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.danger-text {
  color: var(--color-danger);
}

.preview {
  display: grid;
  gap: var(--space-4);
  justify-items: start;
}

.preview img {
  max-width: 100%;
  max-height: 70vh;
  border-radius: var(--radius-md);
}

.preview iframe {
  width: 100%;
  height: 70vh;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.preview .text {
  width: 100%;
  max-height: 60vh;
  margin: 0;
  padding: var(--space-4);
  overflow: auto;
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
  white-space: pre-wrap;
}

.versions {
  display: grid;
  margin: 0;
  padding: 0;
  list-style: none;
}

.versions li {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--color-border);
}

.vnum {
  display: grid;
  place-items: center;
  width: 40px;
  height: 32px;
  border-radius: var(--radius-sm);
  background: var(--color-neutral-soft);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.current-tag {
  background: var(--color-success-soft);
  color: var(--color-success);
}

@media (max-width: 720px) {
  .hide-sm {
    display: none;
  }
}
</style>
