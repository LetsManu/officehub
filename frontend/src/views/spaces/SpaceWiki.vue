<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import EmptyState from '@/components/EmptyState.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import { ApiError, api } from '@/lib/api'
import { errorText, formatDateTime, t } from '@/lib/i18n'
import { renderMarkdown } from '@/lib/markdown'
import { useSpace } from '@/lib/spaceContext'
import { showToast } from '@/lib/toast'
import type { UserBrief, WikiPage, WikiPageSummary, WikiRevision } from '@/lib/types'

const props = defineProps<{ pageId?: string }>()
const { space } = useSpace()
const router = useRouter()

const pages = ref<WikiPageSummary[]>([])
const page = ref<WikiPage | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const editing = ref(false)
const draft = ref({ title: '', body: '', parent_id: null as number | null })
const baseVersion = ref(0)
const editors = ref<UserBrief[]>([])
const newerBy = ref<string | null>(null)
const saving = ref(false)
const textarea = ref<HTMLTextAreaElement | null>(null)
let heartbeat: number | undefined

const base = computed(() => `/spaces/${space.value!.id}/wiki`)
const canWrite = computed(() => page.value?.can_write ?? !space.value?.archived)
const dirty = computed(() => editing.value && page.value !== null &&
  (draft.value.title !== page.value.title || draft.value.body !== page.value.body))

/** Pages as an indented tree. */
const tree = computed(() => {
  const out: { page: WikiPageSummary; depth: number }[] = []
  const children = (parent: number | null, depth: number) => {
    for (const p of pages.value.filter((x) => x.parent_id === parent)) {
      out.push({ page: p, depth })
      if (depth < 6) children(p.id, depth + 1)
    }
  }
  children(null, 0)
  return out
})

async function loadPages() {
  pages.value = await api.get<WikiPageSummary[]>(`/api/spaces/${space.value!.id}/pages`)
}

async function loadPage() {
  stopEditing()
  error.value = null
  // Without a page in the address, open the oldest top-level page (the space's start page)
  const id = props.pageId ? Number(props.pageId) : Math.min(...pages.value.filter((p) => p.parent_id === null).map((p) => p.id))
  if (!Number.isFinite(id)) {
    page.value = null
    loading.value = false
    return
  }
  try {
    page.value = await api.get<WikiPage>(`/api/wiki/${id}`)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

// ---------- editing ----------

async function beat() {
  if (!page.value) return
  try {
    const presence = await api.post<{ version: number; updated_by: string | null; editors: UserBrief[] }>(`/api/wiki/${page.value.id}/presence`)
    editors.value = presence.editors
    newerBy.value = presence.version > baseVersion.value ? presence.updated_by ?? '' : null
  } catch {
    /* next time */
  }
}

function startEditing() {
  if (!page.value) return
  draft.value = { title: page.value.title, body: page.value.body, parent_id: page.value.parent_id }
  baseVersion.value = page.value.version
  newerBy.value = null
  editing.value = true
  beat()
  heartbeat = window.setInterval(beat, 10_000)
  nextTick(() => textarea.value?.focus())
}

function stopEditing() {
  if (heartbeat) window.clearInterval(heartbeat)
  heartbeat = undefined
  if (editing.value && page.value) api.delete(`/api/wiki/${page.value.id}/presence`).catch(() => undefined)
  editing.value = false
  editors.value = []
}

const conflict = ref<WikiPage | null>(null)

async function save(force = false) {
  if (!page.value || !draft.value.title.trim()) return
  saving.value = true
  try {
    const version = force && conflict.value ? conflict.value.version : baseVersion.value
    page.value = await api.put<WikiPage>(`/api/wiki/${page.value.id}`, { ...draft.value, title: draft.value.title.trim(), base_version: version })
    conflict.value = null
    stopEditing()
    showToast(t('wiki.saved'))
    loadPages()
  } catch (e) {
    if (e instanceof ApiError && e.code === 'page_conflict') {
      conflict.value = await api.get<WikiPage>(`/api/wiki/${page.value.id}`)
    } else {
      showToast(errorText(e), 'error')
    }
  } finally {
    saving.value = false
  }
}

function takeTheirs() {
  if (!conflict.value) return
  page.value = conflict.value
  draft.value = { title: conflict.value.title, body: conflict.value.body, parent_id: conflict.value.parent_id }
  baseVersion.value = conflict.value.version
  conflict.value = null
  newerBy.value = null
}

async function reloadNewer() {
  if (!page.value) return
  const fresh = await api.get<WikiPage>(`/api/wiki/${page.value.id}`)
  page.value = fresh
  draft.value = { title: fresh.title, body: fresh.body, parent_id: fresh.parent_id }
  baseVersion.value = fresh.version
  newerBy.value = null
}

/** Wrap the selection (or insert at the cursor) with Markdown. */
function format(before: string, after = '', placeholder = '') {
  const el = textarea.value
  if (!el) return
  const start = el.selectionStart
  const end = el.selectionEnd
  const selected = draft.value.body.slice(start, end) || placeholder
  draft.value.body = draft.value.body.slice(0, start) + before + selected + after + draft.value.body.slice(end)
  nextTick(() => {
    el.focus()
    el.setSelectionRange(start + before.length, start + before.length + selected.length)
  })
}

function linePrefix(prefix: string) {
  const el = textarea.value
  if (!el) return
  const start = draft.value.body.lastIndexOf('\n', el.selectionStart - 1) + 1
  draft.value.body = draft.value.body.slice(0, start) + prefix + draft.value.body.slice(start)
  nextTick(() => {
    el.focus()
    el.setSelectionRange(el.selectionStart + prefix.length, el.selectionStart + prefix.length)
  })
}

function onKeydown(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key === 's') {
    event.preventDefault()
    save()
  }
  if ((event.ctrlKey || event.metaKey) && event.key === 'b') {
    event.preventDefault()
    format('**', '**', t('wiki.bold'))
  }
}

// ---------- new page, delete, history ----------

const newOpen = ref(false)
const newTitle = ref('')
const newParent = ref<number | null>(null)

async function createPage() {
  if (!newTitle.value.trim()) return
  try {
    const created = await api.post<WikiPage>(`/api/spaces/${space.value!.id}/pages`, { title: newTitle.value.trim(), body: `# ${newTitle.value.trim()}\n\n`, parent_id: newParent.value })
    newOpen.value = false
    await loadPages()
    await router.push(`${base.value}/${created.id}`)
    startEditing()
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

const deleting = ref(false)

async function deletePage() {
  if (!page.value) return
  try {
    await api.delete(`/api/wiki/${page.value.id}`)
    deleting.value = false
    showToast(t('wiki.deleted'))
    await loadPages()
    router.push(base.value)
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

const history = ref<WikiRevision[] | null>(null)
const revision = ref<WikiRevision | null>(null)

async function openHistory() {
  if (!page.value) return
  history.value = await api.get<WikiRevision[]>(`/api/wiki/${page.value.id}/revisions`)
  revision.value = null
}

async function showRevision(version: number) {
  revision.value = await api.get<WikiRevision>(`/api/wiki/${page.value!.id}/revisions/${version}`)
}

async function restoreRevision() {
  if (!revision.value || !page.value) return
  startEditing()
  draft.value.title = revision.value.title
  draft.value.body = revision.value.body ?? ''
  history.value = null
  await save()
}

watch(() => props.pageId, loadPage)
onMounted(async () => {
  await loadPages()
  await loadPage()
})
onBeforeUnmount(stopEditing)
onBeforeRouteLeave(() => (dirty.value ? window.confirm(t('wiki.leaveConfirm')) : true))
</script>

<template>
  <div class="wiki">
    <aside class="tree card card-flush" :aria-label="t('wiki.pages')">
      <div class="tree-head">
        <h2 class="h4">{{ t('wiki.pages') }}</h2>
        <button v-if="canWrite" type="button" class="btn btn-ghost btn-icon" :aria-label="t('wiki.newPage')" :title="t('wiki.newPage')" @click="newOpen = true; newTitle = ''; newParent = null"><AppIcon name="plus" :size="18" /></button>
      </div>
      <ul>
        <li v-for="item in tree" :key="item.page.id">
          <RouterLink :to="`${base}/${item.page.id}`" class="tree-link" :class="[`d${Math.min(item.depth, 4)}`, { active: item.page.id === page?.id }]">
            <AppIcon name="file" :size="15" />{{ item.page.title }}
          </RouterLink>
        </li>
      </ul>
    </aside>

    <section class="card page-card">
      <p v-if="error" class="notice notice-danger">{{ error }}</p>
      <EmptyState v-else-if="!loading && !page" icon="book" :message="t('wiki.empty')" :action-label="canWrite ? t('wiki.newPage') : undefined" @action="newOpen = true" />

      <!-- Reading -->
      <article v-else-if="page && !editing" class="read">
        <header class="read-head">
          <div>
            <h1 class="title">{{ page.title }}</h1>
            <p class="muted small">{{ t('wiki.lastChange', { name: page.updated_by ?? '–', date: formatDateTime(page.updated_at) }) }}</p>
          </div>
          <div class="row">
            <button type="button" class="btn btn-ghost" @click="openHistory"><AppIcon name="history" :size="18" />{{ t('wiki.history') }}</button>
            <template v-if="canWrite">
              <button type="button" class="btn btn-ghost btn-icon" :aria-label="t('wiki.subpage')" :title="t('wiki.subpage')" @click="newOpen = true; newTitle = ''; newParent = page.id"><AppIcon name="plus" :size="18" /></button>
              <button type="button" class="btn btn-ghost btn-icon" :aria-label="t('wiki.delete')" :title="t('wiki.delete')" @click="deleting = true"><AppIcon name="trash" :size="18" /></button>
              <button type="button" class="btn btn-primary" @click="startEditing"><AppIcon name="edit" :size="18" />{{ t('wiki.edit') }}</button>
            </template>
          </div>
        </header>
        <p v-if="page.editors.length" class="notice notice-info small editing-now">
          <AppIcon name="edit" :size="16" />{{ t('wiki.othersEditing', { names: page.editors.map((e) => e.full_name).join(', ') }) }}
        </p>
        <!-- eslint-disable-next-line vue/no-v-html -- renderMarkdown escapes HTML first -->
        <div class="markdown body" v-html="renderMarkdown(page.body)" />
      </article>

      <!-- Editing -->
      <form v-else-if="page && editing" class="edit" @submit.prevent="save()">
        <div v-if="editors.length" class="presence notice notice-info small" role="status">
          <span class="faces"><UserAvatar v-for="e in editors" :id="e.id" :key="e.id" :name="e.full_name" :photo-version="e.photo_version" :size="24" /></span>
          {{ t('wiki.alsoEditing', { names: editors.map((e) => e.full_name).join(', ') }) }}
        </div>
        <div v-if="newerBy !== null" class="notice notice-warning small newer" role="alert">
          <span>{{ t('wiki.newerSaved', { name: newerBy || '–' }) }}</span>
          <button type="button" class="btn btn-secondary" @click="reloadNewer">{{ t('wiki.loadNewer') }}</button>
        </div>
        <label for="wk-title" class="visually-hidden">{{ t('wiki.title') }}</label>
        <input id="wk-title" v-model="draft.title" class="input title-input" maxlength="150" />
        <div class="toolbar" role="toolbar" :aria-label="t('wiki.format')">
          <button type="button" class="tool" :title="t('wiki.bold')" :aria-label="t('wiki.bold')" @click="format('**', '**', t('wiki.bold'))"><b>B</b></button>
          <button type="button" class="tool" :title="t('wiki.italic')" :aria-label="t('wiki.italic')" @click="format('_', '_', t('wiki.italic'))"><i>I</i></button>
          <button type="button" class="tool" :title="t('wiki.heading')" :aria-label="t('wiki.heading')" @click="linePrefix('## ')">H</button>
          <button type="button" class="tool" :title="t('wiki.list')" :aria-label="t('wiki.list')" @click="linePrefix('- ')"><AppIcon name="tasks" :size="16" /></button>
          <button type="button" class="tool" :title="t('wiki.link')" :aria-label="t('wiki.link')" @click="format('[', '](https://)', t('wiki.linkText'))"><AppIcon name="link" :size="16" /></button>
          <span class="muted small tip">{{ t('wiki.markdownHint') }}</span>
        </div>
        <div class="split">
          <label for="wk-body" class="visually-hidden">{{ t('wiki.text') }}</label>
          <textarea id="wk-body" ref="textarea" v-model="draft.body" class="textarea editor" spellcheck="true" @keydown="onKeydown" />
          <!-- eslint-disable-next-line vue/no-v-html -- renderMarkdown escapes HTML first -->
          <div class="markdown preview" :aria-label="t('wiki.preview')" v-html="renderMarkdown(draft.body)" />
        </div>
        <div class="row actions">
          <button type="submit" class="btn btn-primary" :disabled="saving || !draft.title.trim()">{{ t('app.save') }}</button>
          <button type="button" class="btn btn-ghost" @click="stopEditing">{{ t('app.cancel') }}</button>
          <span class="muted small">{{ t('wiki.saveHint') }}</span>
        </div>
      </form>
    </section>

    <!-- New page -->
    <BaseModal :open="newOpen" :title="newParent ? t('wiki.subpage') : t('wiki.newPage')" :confirm-label="t('files.create')" @close="newOpen = false" @confirm="createPage">
      <form novalidate @submit.prevent="createPage">
        <label for="wk-new" class="label">{{ t('wiki.title') }}</label>
        <input id="wk-new" v-model="newTitle" class="input" maxlength="150" />
      </form>
    </BaseModal>

    <BaseModal :open="deleting" :title="t('wiki.deleteTitle', { title: page?.title ?? '' })" :description="t('wiki.deleteText')" :confirm-label="t('wiki.delete')" tone="danger" @close="deleting = false" @confirm="deletePage" />

    <!-- Conflict -->
    <BaseModal :open="conflict !== null" :title="t('wiki.conflictTitle')" :description="t('wiki.conflictText', { name: conflict?.updated_by ?? '–' })" wide hide-actions @close="conflict = null">
      <div v-if="conflict" class="conflict">
        <div>
          <h3 class="h4">{{ t('wiki.theirVersion', { name: conflict.updated_by ?? '–' }) }}</h3>
          <!-- eslint-disable-next-line vue/no-v-html -- renderMarkdown escapes HTML first -->
          <div class="markdown pane" v-html="renderMarkdown(conflict.body)" />
          <button type="button" class="btn btn-secondary" @click="takeTheirs">{{ t('wiki.takeTheirs') }}</button>
        </div>
        <div>
          <h3 class="h4">{{ t('wiki.yourVersion') }}</h3>
          <!-- eslint-disable-next-line vue/no-v-html -- renderMarkdown escapes HTML first -->
          <div class="markdown pane" v-html="renderMarkdown(draft.body)" />
          <button type="button" class="btn btn-primary" @click="save(true)">{{ t('wiki.keepMine') }}</button>
        </div>
      </div>
    </BaseModal>

    <!-- History -->
    <BaseModal :open="history !== null" :title="t('wiki.history')" wide hide-actions @close="history = null">
      <div v-if="history" class="history">
        <ol>
          <li v-for="r in history" :key="r.version">
            <button type="button" class="rev" :class="{ active: revision?.version === r.version }" @click="showRevision(r.version)">
              <strong>v{{ r.version }}</strong>
              <span class="muted small">{{ formatDateTime(r.created_at) }} · {{ r.author ?? '–' }}</span>
            </button>
          </li>
        </ol>
        <div class="rev-view">
          <template v-if="revision">
            <!-- eslint-disable-next-line vue/no-v-html -- renderMarkdown escapes HTML first -->
            <div class="markdown pane" v-html="renderMarkdown(revision.body ?? '')" />
            <button v-if="canWrite && revision.version !== page?.version" type="button" class="btn btn-secondary" @click="restoreRevision">{{ t('wiki.restore') }}</button>
          </template>
          <p v-else class="muted">{{ t('wiki.pickVersion') }}</p>
        </div>
      </div>
    </BaseModal>
  </div>
</template>

<style scoped>
.wiki {
  display: grid;
  grid-template-columns: 250px minmax(0, 1fr);
  gap: var(--space-4);
  align-items: start;
}

.tree {
  position: sticky;
  top: calc(var(--header-height, 64px) + var(--space-4));
  padding-bottom: var(--space-2);
}

.tree-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-3) var(--space-2) var(--space-4);
}

.tree ul {
  margin: 0;
  padding: 0 var(--space-2);
  list-style: none;
}

.tree-link {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 36px;
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  color: var(--color-text-muted);
  text-decoration: none;
  overflow-wrap: anywhere;
}

.tree-link:hover {
  background: var(--color-surface-muted);
}

.tree-link.active {
  background: var(--color-primary-soft);
  color: var(--color-text);
  font-weight: 600;
}

.d1 {
  padding-left: calc(var(--space-2) + 16px);
}

.d2 {
  padding-left: calc(var(--space-2) + 32px);
}

.d3,
.d4 {
  padding-left: calc(var(--space-2) + 48px);
}

.page-card {
  min-width: 0;
}

.read-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.title {
  font-size: var(--text-xl);
}

.editing-now {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
}

.body {
  max-width: 76ch;
}

.edit {
  display: grid;
  gap: var(--space-3);
}

.presence,
.newer {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}

.faces {
  display: flex;
}

.faces > :deep(*) + :deep(*) {
  margin-left: -6px;
}

.title-input {
  font-family: var(--font-heading);
  font-size: var(--text-lg);
  font-weight: 600;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}

.tool {
  display: grid;
  place-items: center;
  min-width: 36px;
  height: 36px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text);
  font: inherit;
  font-weight: 700;
  cursor: pointer;
}

.tool:hover {
  background: var(--color-neutral-soft);
}

.tip {
  margin-left: var(--space-2);
}

.split {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
}

.editor {
  min-height: 420px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.92rem;
  line-height: 1.6;
}

.preview {
  min-height: 420px;
  max-height: 70vh;
  padding: var(--space-3) var(--space-4);
  overflow-y: auto;
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-md);
}

.actions {
  align-items: center;
}

.conflict {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-4);
}

.conflict > div {
  display: grid;
  gap: var(--space-3);
  align-content: start;
  justify-items: start;
}

.pane {
  width: 100%;
  max-height: 50vh;
  padding: var(--space-3);
  overflow-y: auto;
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
}

.history {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: var(--space-4);
}

.history ol {
  display: grid;
  gap: 2px;
  max-height: 60vh;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}

.rev {
  display: grid;
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: 0;
  border-radius: var(--radius-sm);
  background: none;
  color: var(--color-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.rev:hover,
.rev.active {
  background: var(--color-primary-soft);
}

.rev-view {
  display: grid;
  gap: var(--space-3);
  align-content: start;
  justify-items: start;
}

@media (max-width: 900px) {
  .wiki,
  .split,
  .conflict,
  .history {
    grid-template-columns: 1fr;
  }

  .tree {
    position: static;
  }

  .preview {
    display: none;
  }
}
</style>
