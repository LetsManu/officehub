<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import FormField from '@/components/FormField.vue'
import LoadState from '@/components/LoadState.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import { api } from '@/lib/api'
import { errorText, formatDate, formatDateTime, t } from '@/lib/i18n'
import { renderMarkdown } from '@/lib/markdown'
import { PROJECT_COLORS } from '@/lib/planning'
import { currentUser } from '@/lib/session'
import { useSpace } from '@/lib/spaceContext'
import { showToast } from '@/lib/toast'
import type { Board, BoardCard, BoardCardDetail, BoardColumn } from '@/lib/types'

const { space } = useSpace()
const route = useRoute()
const router = useRouter()
const board = ref<Board | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const busy = ref(false)
const today = new Date().toISOString().slice(0, 10)
const filter = ref<'all' | 'mine'>('all')

const newTitles = reactive<Record<number, string>>({})
const adding = ref<number | null>(null)

async function load() {
  if (!space.value?.board_id) return
  try {
    board.value = await api.get<Board>(`/api/boards/${space.value.board_id}`)
    error.value = null
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

function visibleCards(column: BoardColumn): BoardCard[] {
  if (filter.value === 'all') return column.cards
  return column.cards.filter((c) => c.assignees.some((a) => a.id === currentUser.value?.id))
}

// ---------- add ----------

async function addCard(column: BoardColumn) {
  const title = (newTitles[column.id] ?? '').trim()
  if (!title) {
    adding.value = null
    return
  }
  try {
    await api.post(`/api/boards/columns/${column.id}/cards`, { title })
    newTitles[column.id] = ''
    await load()
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

// ---------- drag and drop (mouse) ----------

const dragged = ref<BoardCard | null>(null)
const dropTarget = ref<{ column: number; index: number } | null>(null)

function onDragStart(event: DragEvent, card: BoardCard) {
  if (!board.value?.can_write) return
  dragged.value = card
  event.dataTransfer?.setData('text/plain', String(card.id))
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}

function onDragOver(event: DragEvent, column: BoardColumn) {
  if (!dragged.value) return
  const list = (event.currentTarget as HTMLElement).querySelectorAll<HTMLElement>('[data-card]')
  let index = list.length
  for (let i = 0; i < list.length; i++) {
    const box = list[i].getBoundingClientRect()
    if (event.clientY < box.top + box.height / 2) {
      index = i
      break
    }
  }
  dropTarget.value = { column: column.id, index }
}

async function onDrop() {
  const card = dragged.value
  const target = dropTarget.value
  dragged.value = null
  dropTarget.value = null
  if (!card || !target) return
  await move(card, target.column, target.index)
}

async function move(card: BoardCard, columnId: number, position: number) {
  try {
    await api.post(`/api/boards/cards/${card.id}/move`, { column_id: columnId, position })
    await load()
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

// ---------- card details ----------

const card = ref<BoardCardDetail | null>(null)
const form = reactive({ title: '', description: '', due_date: '', label: '', assignee_ids: [] as number[], column_id: 0 })
const editingDescription = ref(false)
const comment = ref('')
const formError = ref('')
const deleting = ref(false)

async function openCard(id: number) {
  try {
    const detail = await api.get<BoardCardDetail>(`/api/boards/cards/${id}`)
    await router.replace({ query: { card: String(id) } })
    Object.assign(form, {
      title: detail.title, description: detail.description, due_date: detail.due_date ?? '',
      label: detail.label, assignee_ids: detail.assignees.map((a) => a.id), column_id: detail.column_id,
    })
    editingDescription.value = false
    comment.value = ''
    formError.value = ''
    card.value = detail
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

function closeCard() {
  card.value = null
  router.replace({ query: {} })
}

async function saveCard() {
  if (!card.value) return
  formError.value = form.title.trim() ? '' : t('validation.title_required')
  if (formError.value) return
  busy.value = true
  try {
    await api.put(`/api/boards/cards/${card.value.id}`, {
      title: form.title.trim(), description: form.description, due_date: form.due_date || null,
      label: form.label, assignee_ids: form.assignee_ids,
    })
    if (form.column_id !== card.value.column_id) {
      const target = board.value!.columns.find((c) => c.id === form.column_id)
      await api.post(`/api/boards/cards/${card.value.id}/move`, { column_id: form.column_id, position: target?.cards.length ?? 0 })
    }
    showToast(t('board.saved'))
    closeCard()
    await load()
  } catch (e) {
    formError.value = errorText(e)
  } finally {
    busy.value = false
  }
}

async function addComment() {
  if (!card.value || !comment.value.trim()) return
  try {
    card.value = await api.post<BoardCardDetail>(`/api/boards/cards/${card.value.id}/comments`, { body: comment.value.trim() })
    comment.value = ''
    load()
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

async function deleteCard() {
  if (!card.value) return
  busy.value = true
  try {
    await api.delete(`/api/boards/cards/${card.value.id}`)
    deleting.value = false
    closeCard()
    showToast(t('board.deleted'))
    await load()
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    busy.value = false
  }
}

// ---------- columns ----------

const columnEdit = ref<BoardColumn | 'new' | null>(null)
const columnForm = reactive({ name: '', is_done: false })
const columnError = ref('')

function editColumn(column: BoardColumn | 'new') {
  columnEdit.value = column
  Object.assign(columnForm, column === 'new' ? { name: '', is_done: false } : { name: column.name, is_done: column.is_done })
  columnError.value = ''
}

async function saveColumn() {
  columnError.value = columnForm.name.trim() ? '' : t('validation.name_required')
  if (columnError.value || !board.value) return
  busy.value = true
  try {
    if (columnEdit.value === 'new') board.value = await api.post<Board>(`/api/boards/${board.value.id}/columns`, { ...columnForm, name: columnForm.name.trim() })
    else board.value = await api.put<Board>(`/api/boards/columns/${(columnEdit.value as BoardColumn).id}`, { ...columnForm, name: columnForm.name.trim() })
    columnEdit.value = null
  } catch (e) {
    columnError.value = errorText(e)
  } finally {
    busy.value = false
  }
}

async function deleteColumn() {
  if (!columnEdit.value || columnEdit.value === 'new') return
  try {
    board.value = await api.delete<Board>(`/api/boards/columns/${columnEdit.value.id}`)
    columnEdit.value = null
  } catch (e) {
    columnError.value = errorText(e)
  }
}

onMounted(async () => {
  await load()
  const id = Number(route.query.card)
  if (id) openCard(id)
})
</script>

<template>
  <LoadState :loading="loading" :error="error" @retry="load">
    <div v-if="board" class="board-page stack">
      <div class="toolbar">
        <div class="segmented" role="group" :aria-label="t('board.show')">
          <button type="button" :aria-pressed="filter === 'all'" @click="filter = 'all'">{{ t('board.all') }}</button>
          <button type="button" :aria-pressed="filter === 'mine'" @click="filter = 'mine'">{{ t('board.mine') }}</button>
        </div>
        <button v-if="board.can_write" type="button" class="btn btn-ghost" @click="editColumn('new')"><AppIcon name="plus" :size="18" />{{ t('board.addColumn') }}</button>
      </div>

      <div class="columns" role="list">
        <section
          v-for="column in board.columns"
          :key="column.id"
          class="column"
          :class="{ done: column.is_done, over: dropTarget?.column === column.id }"
          role="listitem"
          :aria-labelledby="`col-${column.id}`"
          @dragover.prevent="onDragOver($event, column)"
          @drop.prevent="onDrop"
        >
          <header class="col-head">
            <h2 :id="`col-${column.id}`" class="col-title">
              <AppIcon v-if="column.is_done" name="checkCircle" :size="16" class="done-icon" />{{ column.name }}
              <span class="col-count">{{ column.cards.length }}</span>
            </h2>
            <button v-if="board.can_write" type="button" class="btn btn-ghost btn-icon" :aria-label="t('board.editColumn', { name: column.name })" @click="editColumn(column)"><AppIcon name="dots" :size="18" /></button>
          </header>
          <ol class="cards">
            <template v-for="(c, i) in visibleCards(column)" :key="c.id">
              <li v-if="dropTarget?.column === column.id && dropTarget.index === i && dragged?.id !== c.id" class="drop-line" aria-hidden="true" />
              <li data-card class="card-item" :class="{ dragging: dragged?.id === c.id }" :draggable="board.can_write" @dragstart="onDragStart($event, c)" @dragend="dragged = null; dropTarget = null">
                <button type="button" class="kcard" :class="c.label ? `pc-${c.label}` : ''" @click="openCard(c.id)">
                  <span v-if="c.label" class="label-bar" aria-hidden="true" />
                  <span class="ktitle">{{ c.title }}</span>
                  <span class="kmeta">
                    <span v-if="c.due_date" class="due" :class="{ late: !column.is_done && c.due_date < today, soon: !column.is_done && c.due_date === today }">
                      <AppIcon name="calendar" :size="14" />{{ formatDate(c.due_date) }}
                    </span>
                    <span v-if="c.has_description" class="icon-only" :title="t('board.hasDescription')"><AppIcon name="file" :size="14" /></span>
                    <span v-if="c.comment_count" class="icon-only"><AppIcon name="message" :size="14" />{{ c.comment_count }}</span>
                    <span class="people">
                      <UserAvatar v-for="a in c.assignees.slice(0, 3)" :id="a.id" :key="a.id" :name="a.full_name" :photo-version="a.photo_version" :size="24" />
                    </span>
                  </span>
                </button>
              </li>
            </template>
            <li v-if="dropTarget?.column === column.id && dropTarget.index >= visibleCards(column).length" class="drop-line" aria-hidden="true" />
          </ol>
          <template v-if="board.can_write">
            <form v-if="adding === column.id" class="add-form" @submit.prevent="addCard(column)">
              <label :for="`add-${column.id}`" class="visually-hidden">{{ t('board.cardTitle') }}</label>
              <textarea :id="`add-${column.id}`" v-model="newTitles[column.id]" class="textarea" rows="2" maxlength="200" :placeholder="t('board.cardPlaceholder')" @keydown.enter.exact.prevent="addCard(column)" @keydown.esc="adding = null" />
              <div class="row">
                <button type="submit" class="btn btn-primary">{{ t('board.add') }}</button>
                <button type="button" class="btn btn-ghost" @click="adding = null">{{ t('app.cancel') }}</button>
              </div>
            </form>
            <button v-else type="button" class="btn btn-ghost add-btn" @click="adding = column.id"><AppIcon name="plus" :size="18" />{{ t('board.addCard') }}</button>
          </template>
        </section>
      </div>
      <p class="muted small">{{ t('board.hint') }}</p>
    </div>

    <!-- Card -->
    <BaseModal :open="card !== null" :title="t('board.card')" wide :confirm-label="t('app.save')" :busy="busy" :hide-actions="!board?.can_write" @close="closeCard" @confirm="saveCard">
      <form v-if="card && board" class="card-form" novalidate @submit.prevent="saveCard">
        <div class="main-col stack">
          <div v-if="formError" class="notice notice-danger small" role="alert">{{ formError }}</div>
          <FormField id="cd-title" :label="t('board.cardTitle')">
            <template #default="{ attrs }"><input v-bind="attrs" v-model="form.title" class="input" maxlength="200" :disabled="!board.can_write" /></template>
          </FormField>
          <div class="field">
            <div class="row-between">
              <span class="label">{{ t('board.description') }}</span>
              <button v-if="board.can_write" type="button" class="btn btn-ghost small-btn" @click="editingDescription = !editingDescription">{{ editingDescription ? t('board.preview') : t('app.edit') }}</button>
            </div>
            <textarea v-if="editingDescription" id="cd-desc" v-model="form.description" class="textarea" rows="7" maxlength="10000" :aria-label="t('board.description')" :placeholder="t('board.descriptionHint')" />
            <!-- eslint-disable-next-line vue/no-v-html -- renderMarkdown escapes HTML first -->
            <div v-else-if="form.description.trim()" class="markdown desc" v-html="renderMarkdown(form.description)" />
            <p v-else class="muted small">{{ t('board.noDescription') }}</p>
          </div>
          <div class="comments">
            <h3 class="h4">{{ t('board.comments') }}</h3>
            <ol>
              <li v-for="c in card.comments" :key="c.id">
                <UserAvatar v-if="c.author" :id="c.author.id" :name="c.author.full_name" :photo-version="c.author.photo_version" :size="28" />
                <div>
                  <p class="small"><strong>{{ c.author?.full_name ?? '–' }}</strong> <span class="muted">{{ formatDateTime(c.created_at) }}</span></p>
                  <p class="comment-body">{{ c.body }}</p>
                </div>
              </li>
            </ol>
            <div v-if="board.can_write" class="comment-new">
              <label for="cd-comment" class="visually-hidden">{{ t('board.writeComment') }}</label>
              <textarea id="cd-comment" v-model="comment" class="textarea" rows="2" maxlength="5000" :placeholder="t('board.writeComment')" />
              <button type="button" class="btn btn-secondary" :disabled="!comment.trim()" @click="addComment">{{ t('board.sendComment') }}</button>
            </div>
          </div>
        </div>
        <aside class="side stack">
          <FormField id="cd-col" :label="t('board.column')">
            <template #default="{ attrs }">
              <select v-bind="attrs" v-model.number="form.column_id" class="select" :disabled="!board.can_write">
                <option v-for="c in board.columns" :key="c.id" :value="c.id">{{ c.name }}</option>
              </select>
            </template>
          </FormField>
          <FormField id="cd-due" :label="t('board.due')" optional>
            <template #default="{ attrs }"><input v-bind="attrs" v-model="form.due_date" type="date" class="input" :disabled="!board.can_write" /></template>
          </FormField>
          <fieldset class="assignees">
            <legend class="label">{{ t('board.assignees') }}</legend>
            <label v-for="m in board.members" :key="m.id" class="checkbox">
              <input v-model="form.assignee_ids" type="checkbox" :value="m.id" :disabled="!board.can_write" />
              <span>{{ m.full_name }}</span>
            </label>
          </fieldset>
          <fieldset class="swatches">
            <legend>{{ t('board.label') }}</legend>
            <label class="swatch none-swatch">
              <input v-model="form.label" type="radio" name="cd-label" value="" :disabled="!board.can_write" />
              <span class="dot" aria-hidden="true"><AppIcon v-if="!form.label" name="check" :size="16" /></span>
              <span class="visually-hidden">{{ t('board.noLabel') }}</span>
            </label>
            <label v-for="c in PROJECT_COLORS" :key="c" class="swatch" :class="`pc-${c}`">
              <input v-model="form.label" type="radio" name="cd-label" :value="c" :disabled="!board.can_write" />
              <span class="dot" aria-hidden="true"><AppIcon v-if="form.label === c" name="check" :size="16" /></span>
              <span class="visually-hidden">{{ t(`projects.colors.${c}`) }}</span>
            </label>
          </fieldset>
          <button v-if="board.can_write" type="button" class="btn btn-ghost danger-text" @click="deleting = true"><AppIcon name="trash" :size="18" />{{ t('board.delete') }}</button>
        </aside>
      </form>
    </BaseModal>

    <BaseModal :open="deleting" :title="t('board.deleteTitle')" :description="card?.title ?? ''" :confirm-label="t('board.delete')" tone="danger" :busy="busy" @close="deleting = false" @confirm="deleteCard" />

    <!-- Column -->
    <BaseModal :open="columnEdit !== null" :title="columnEdit === 'new' ? t('board.addColumn') : t('board.columnTitle')" :confirm-label="t('app.save')" :busy="busy" @close="columnEdit = null" @confirm="saveColumn">
      <form class="stack" novalidate @submit.prevent="saveColumn">
        <FormField id="col-name" :label="t('board.columnName')" :error="columnError">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="columnForm.name" class="input" maxlength="60" /></template>
        </FormField>
        <label class="checkbox">
          <input v-model="columnForm.is_done" type="checkbox" />
          <span>{{ t('board.doneColumn') }}</span>
        </label>
        <div v-if="columnEdit && columnEdit !== 'new'">
          <button type="button" class="btn btn-ghost danger-text" @click="deleteColumn"><AppIcon name="trash" :size="18" />{{ t('board.deleteColumn') }}</button>
        </div>
      </form>
    </BaseModal>
  </LoadState>
</template>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.columns {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(272px, 1fr);
  gap: var(--space-4);
  align-items: start;
  overflow-x: auto;
  padding-bottom: var(--space-2);
}

.column {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface-muted);
  transition: box-shadow 150ms ease-out;
}

.column.over {
  box-shadow: 0 0 0 2px var(--color-primary);
}

.col-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.col-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-md);
}

.done-icon {
  color: var(--color-success);
}

.col-count {
  padding: 0 8px;
  border-radius: 99px;
  background: var(--color-neutral-soft);
  color: var(--color-text-muted);
  font-size: 0.75rem;
  font-weight: 700;
}

.cards {
  display: grid;
  gap: var(--space-2);
  min-height: 12px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.card-item.dragging {
  opacity: 0.4;
}

.drop-line {
  height: 3px;
  border-radius: 2px;
  background: var(--color-primary);
}

.kcard {
  position: relative;
  display: grid;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-3);
  padding-top: var(--space-3);
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  box-shadow: 0 1px 2px rgb(0 0 0 / 0.04);
  color: var(--color-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 150ms ease-out, box-shadow 150ms ease-out;
}

.kcard:hover {
  border-color: var(--color-border-strong);
  box-shadow: var(--shadow-card);
}

.kcard:focus-visible {
  outline: 3px solid var(--color-focus);
  outline-offset: 2px;
}

.label-bar {
  position: absolute;
  inset: 0 0 auto;
  height: 4px;
  background: var(--pc);
}

.ktitle {
  font-weight: 600;
  overflow-wrap: anywhere;
}

.done .ktitle {
  color: var(--color-text-muted);
}

.kmeta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-muted);
  font-size: 0.78rem;
}

.due,
.icon-only {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.due.soon {
  color: var(--color-warning);
  font-weight: 600;
}

.due.late {
  padding: 1px 6px;
  border-radius: 99px;
  background: var(--color-warning-soft);
  color: var(--color-warning);
  font-weight: 700;
}

.people {
  display: flex;
  margin-left: auto;
}

.people > :deep(*) + :deep(*) {
  margin-left: -6px;
}

.add-form {
  display: grid;
  gap: var(--space-2);
}

.add-btn {
  justify-content: flex-start;
  color: var(--color-text-muted);
}

.card-form {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 240px;
  gap: var(--space-5);
}

.label {
  font-weight: 600;
  font-size: var(--text-sm);
}

.field {
  display: grid;
  gap: var(--space-2);
}

.small-btn {
  min-height: 32px;
}

.desc {
  padding: var(--space-3);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
}

.assignees {
  display: grid;
  gap: 2px;
  margin: 0;
  padding: 0;
  border: 0;
}

.none-swatch .dot {
  background: var(--color-neutral-soft);
  color: var(--color-text);
  border: 1px dashed var(--color-border-strong);
}

.comments ol {
  display: grid;
  gap: var(--space-3);
  margin: var(--space-3) 0;
  padding: 0;
  list-style: none;
}

.comments li {
  display: flex;
  gap: var(--space-3);
}

.comment-body {
  white-space: pre-wrap;
}

.comment-new {
  display: grid;
  gap: var(--space-2);
  justify-items: start;
}

.danger-text {
  color: var(--color-danger);
}

@media (max-width: 720px) {
  .card-form {
    grid-template-columns: 1fr;
  }
}

@media (prefers-reduced-motion: reduce) {
  .kcard,
  .column {
    transition: none;
  }
}
</style>
