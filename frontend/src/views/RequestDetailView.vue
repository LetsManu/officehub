<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import FormField from '@/components/FormField.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { api } from '@/lib/api'
import { TYPE_ICONS } from '@/lib/requestTypes'
import { currentUser, isApprover } from '@/lib/session'
import { errorText, formatDate, formatDateTime, formatMoney, formatPeriod, t } from '@/lib/i18n'
import { showToast } from '@/lib/toast'
import type { RequestDetail } from '@/lib/types'

const props = defineProps<{ id: string }>()

const request = ref<RequestDetail | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const busy = ref(false)

const modal = ref<'cancel' | 'approve' | 'reject' | null>(null)
const decisionComment = ref('')
const modalError = ref('')

const comment = ref('')
const commentError = ref('')
const receiptInput = ref<HTMLInputElement | null>(null)

const isOwner = computed(() => request.value?.requester.id === currentUser.value?.id)
const backTo = computed(() => (isApprover.value && !isOwner.value ? '/approvals' : '/requests'))

const statusTone = computed(() => {
  switch (request.value?.status) {
    case 'approved':
      return 'notice-success'
    case 'rejected':
      return 'notice-danger'
    case 'in_review':
      return 'notice-warning'
    case 'submitted':
      return 'notice-info'
    default:
      return ''
  }
})

const statusIcon = computed(() => {
  switch (request.value?.status) {
    case 'approved':
      return 'checkCircle'
    case 'rejected':
      return 'alert'
    case 'in_review':
    case 'submitted':
      return 'clock'
    default:
      return 'info'
  }
})

/** Hint shown in the status card, written for the requester or the approver. */
const statusHint = computed(() => {
  const r = request.value
  if (!r) return ''
  if (!isOwner.value && (r.status === 'submitted' || r.status === 'in_review')) return t('detail.waitingForDecision')
  return t(`statusHints.${r.status}`)
})

const facts = computed(() => {
  const r = request.value
  if (!r) return []
  const rows: { label: string; value: string }[] = []
  if (r.type === 'vacation' || r.type === 'home_office') {
    rows.push({ label: t('detail.period'), value: formatPeriod(r.start_date, r.end_date) })
    if (r.working_days !== null) rows.push({ label: t('form.workingDays'), value: r.working_days === 1 ? t('form.workingDaysOne') : t('form.workingDaysValue', { count: r.working_days }) })
  }
  if (r.type === 'expense') {
    rows.push({ label: t('form.amount'), value: formatMoney(r.amount, r.currency) })
    rows.push({ label: t('form.expenseDate'), value: formatDate(r.start_date) })
    if (r.category) rows.push({ label: t('form.category'), value: t(`expenseCategories.${r.category}`) })
  }
  if (r.type === 'equipment') {
    rows.push({ label: t('form.item'), value: r.item ?? '' })
    if (r.category) rows.push({ label: t('form.category'), value: t(`equipmentCategories.${r.category}`) })
  }
  if (r.type === 'it_access') {
    rows.push({ label: t('form.system'), value: r.item ?? '' })
    if (r.access_level) rows.push({ label: t('form.accessLevel'), value: t(`accessLevels.${r.access_level}`) })
  }
  if (r.needed_by) rows.push({ label: t('form.neededBy'), value: formatDate(r.needed_by) })
  rows.push({ label: t('detail.requestedBy'), value: `${r.requester.full_name} · ${r.requester.department}` })
  rows.push({ label: t('detail.created'), value: formatDateTime(r.created_at) })
  rows.push({ label: t('detail.updated'), value: formatDateTime(r.updated_at) })
  return rows
})

async function load() {
  loading.value = true
  error.value = null
  try {
    request.value = await api.get<RequestDetail>(`/api/requests/${props.id}`)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

function openModal(kind: 'cancel' | 'approve' | 'reject') {
  decisionComment.value = ''
  modalError.value = ''
  modal.value = kind
}

async function run(action: () => Promise<RequestDetail>, message: string) {
  busy.value = true
  modalError.value = ''
  try {
    request.value = await action()
    modal.value = null
    showToast(message)
  } catch (e) {
    modalError.value = errorText(e)
    if (!modal.value) showToast(errorText(e), 'error')
  } finally {
    busy.value = false
  }
}

function confirmModal() {
  const id = props.id
  const body = { comment: decisionComment.value.trim() || null }
  if (modal.value === 'cancel') run(() => api.patch(`/api/requests/${id}`, { status: 'cancelled' }), t('detail.cancelled'))
  if (modal.value === 'approve') run(() => api.post(`/api/requests/${id}/approve`, body), t('detail.approved'))
  if (modal.value === 'reject') run(() => api.post(`/api/requests/${id}/reject`, body), t('detail.rejected'))
}

function submitDraft() {
  run(() => api.patch(`/api/requests/${props.id}`, { status: 'submitted' }), t('detail.draftSubmitted'))
}

function startReview() {
  run(() => api.patch(`/api/requests/${props.id}`, { status: 'in_review' }), t('detail.reviewStarted'))
}

async function sendComment() {
  commentError.value = comment.value.trim() ? '' : t('validation.comment_required')
  if (commentError.value) return
  await run(() => api.post(`/api/requests/${props.id}/comments`, { body: comment.value.trim() }), t('detail.commentAdded'))
  if (!modalError.value) comment.value = ''
}

async function onReceiptSelected(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  const data = new FormData()
  data.append('file', file)
  await run(() => api.post(`/api/requests/${props.id}/attachment`, data), t('detail.receiptUploaded'))
  if (receiptInput.value) receiptInput.value.value = ''
}

const modalConfig = computed(() => {
  const r = request.value
  const params = { title: r?.title ?? '', name: r?.requester.full_name ?? '' }
  switch (modal.value) {
    case 'cancel':
      return { title: t('detail.cancelTitle'), text: t('detail.cancelText', params), confirm: t('detail.cancelConfirm'), cancel: t('detail.keep'), tone: 'danger' as const }
    case 'approve':
      return { title: t('detail.approveTitle'), text: t('detail.approveText', params), confirm: t('detail.approveConfirm'), cancel: t('app.cancel'), tone: 'primary' as const }
    case 'reject':
      return { title: t('detail.rejectTitle'), text: t('detail.rejectText', params), confirm: t('detail.rejectConfirm'), cancel: t('app.cancel'), tone: 'danger' as const }
    default:
      return { title: '', text: '', confirm: '', cancel: '', tone: 'primary' as const }
  }
})

watch(() => props.id, load)
onMounted(load)
</script>

<template>
  <div class="page detail-page">
    <LoadState :loading="loading" :error="error" @retry="load">
      <template v-if="request">
        <PageHeader :title="request.title" :back-to="backTo">
          <template #actions>
            <StatusBadge :status="request.status" />
          </template>
        </PageHeader>

        <!-- Status card -->
        <section class="notice status-card" :class="statusTone" aria-live="polite">
          <AppIcon :name="statusIcon" :size="24" />
          <div class="stack-sm grow">
            <p class="status-title">{{ t(`statuses.${request.status}`) }}</p>
            <p>{{ statusHint }}</p>
            <template v-if="request.decided_by && request.decided_at">
              <p class="small muted">{{ t('detail.decidedBy', { name: request.decided_by.full_name, date: formatDate(request.decided_at) }) }}</p>
              <blockquote v-if="request.decision_comment" class="decision prewrap">{{ request.decision_comment }}</blockquote>
            </template>
          </div>
        </section>

        <!-- Actions -->
        <div v-if="Object.values(request.permissions).some(Boolean)" class="row actions">
          <template v-if="request.permissions.can_decide">
            <button type="button" class="btn btn-primary" :disabled="busy" @click="openModal('approve')"><AppIcon name="check" />{{ t('detail.approve') }}</button>
            <button type="button" class="btn btn-danger-outline" :disabled="busy" @click="openModal('reject')">{{ t('detail.reject') }}</button>
            <button v-if="request.permissions.can_start_review" type="button" class="btn btn-ghost" :disabled="busy" @click="startReview">{{ t('detail.startReview') }}</button>
          </template>
          <template v-if="request.permissions.can_submit">
            <button type="button" class="btn btn-primary" :disabled="busy" @click="submitDraft">{{ t('detail.submitDraft') }}</button>
            <RouterLink :to="`/requests/${request.id}/edit`" class="btn btn-secondary"><AppIcon name="edit" />{{ t('app.edit') }}</RouterLink>
          </template>
          <button v-if="request.permissions.can_cancel" type="button" class="btn btn-ghost danger-text" :disabled="busy" @click="openModal('cancel')">
            {{ t('detail.cancelRequest') }}
          </button>
        </div>

        <!-- Details -->
        <section class="card stack" aria-labelledby="details-title">
          <div class="row">
            <span class="type-icon"><AppIcon :name="TYPE_ICONS[request.type]" /></span>
            <h2 id="details-title">{{ t(`requestTypes.${request.type}`) }}</h2>
          </div>
          <dl class="facts">
            <div v-for="row in facts" :key="row.label">
              <dt>{{ row.label }}</dt>
              <dd>{{ row.value }}</dd>
            </div>
          </dl>
          <div v-if="request.description" class="stack-sm">
            <h3 class="small muted">{{ request.type === 'general' ? t('form.description') : t('detail.details') }}</h3>
            <p class="prewrap">{{ request.description }}</p>
          </div>
          <div v-if="request.type === 'expense'" class="stack-sm">
            <h3 class="small muted">{{ t('detail.receipt') }}</h3>
            <div class="row">
              <a v-if="request.attachment_name" :href="`/api/requests/${request.id}/attachment`" target="_blank" rel="noopener" class="btn btn-secondary">
                <AppIcon name="paperclip" />{{ request.attachment_name }}
              </a>
              <span v-else class="muted">{{ t('detail.noReceipt') }}</span>
              <template v-if="request.permissions.can_attach">
                <button type="button" class="btn btn-ghost" :disabled="busy" @click="receiptInput?.click()">
                  <AppIcon name="upload" />{{ request.attachment_name ? t('detail.replaceReceipt') : t('detail.uploadReceipt') }}
                </button>
                <input ref="receiptInput" class="visually-hidden" type="file" tabindex="-1" aria-hidden="true" accept=".pdf,.png,.jpg,.jpeg" @change="onReceiptSelected" />
              </template>
            </div>
          </div>
        </section>

        <!-- Comments (expandable) -->
        <details class="disclosure" :open="request.comments.length > 0 || undefined">
          <summary>{{ t('detail.comments', { count: request.comments.length }) }}</summary>
          <div class="disclosure-body stack">
            <ul v-if="request.comments.length" class="comments">
              <li v-for="c in request.comments" :key="c.id" class="comment" :class="{ mine: c.author.id === currentUser?.id }">
                <p class="small"><strong>{{ c.author.full_name }}</strong> <span class="muted">· {{ formatDateTime(c.created_at) }}</span></p>
                <p class="prewrap">{{ c.body }}</p>
              </li>
            </ul>
            <p v-else class="muted">{{ t('detail.noComments') }}</p>
            <form v-if="request.permissions.can_comment" class="stack-sm" novalidate @submit.prevent="sendComment">
              <FormField id="comment" :label="t('detail.addComment')" :error="commentError">
                <template #default="{ attrs }">
                  <textarea v-bind="attrs" v-model="comment" class="textarea" rows="3" maxlength="2000" :placeholder="t('detail.commentPlaceholder')" />
                </template>
              </FormField>
              <div><button type="submit" class="btn btn-secondary" :disabled="busy"><AppIcon name="message" />{{ t('detail.sendComment') }}</button></div>
            </form>
          </div>
        </details>

        <!-- History (expandable) -->
        <details class="disclosure">
          <summary>{{ t('detail.history') }}</summary>
          <div class="disclosure-body">
            <ol class="history">
              <li v-for="event in request.events" :key="event.id">
                <span>{{ t(`detail.events.${event.action}`, { name: event.actor.full_name }) }}</span>
                <span class="muted small">{{ formatDateTime(event.created_at) }}</span>
              </li>
            </ol>
          </div>
        </details>

        <BaseModal
          :open="modal !== null"
          :title="modalConfig.title"
          :description="modalConfig.text"
          :confirm-label="modalConfig.confirm"
          :cancel-label="modalConfig.cancel"
          :tone="modalConfig.tone"
          :busy="busy"
          @close="modal = null"
          @confirm="confirmModal"
        >
          <FormField v-if="modal === 'approve' || modal === 'reject'" id="decision-comment" :label="t('detail.decisionCommentLabel', { name: request.requester.full_name })" optional>
            <template #default="{ attrs }"><textarea v-bind="attrs" v-model="decisionComment" class="textarea" rows="3" maxlength="2000" /></template>
          </FormField>
          <p v-if="modalError" class="notice notice-danger small" role="alert">{{ modalError }}</p>
        </BaseModal>
      </template>
    </LoadState>
  </div>
</template>

<style scoped>
.detail-page {
  max-width: 860px;
}

.grow {
  flex: 1;
}

.status-card {
  padding: var(--space-5);
}

.status-title {
  font-weight: 650;
  font-size: var(--text-lg);
}

.decision {
  margin: var(--space-2) 0 0;
  padding: var(--space-3) var(--space-4);
  border-left: 3px solid currentColor;
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  background: var(--color-surface);
  color: var(--color-text);
}

.type-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
}

.danger-text {
  color: var(--color-danger);
}

.danger-text:hover:not(:disabled) {
  background: var(--color-danger-soft);
}

.comments {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-3);
}

.comment {
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
}

.comment.mine {
  background: var(--color-primary-soft);
}

.history {
  margin: 0;
  padding: 0 0 0 var(--space-5);
  display: grid;
  gap: var(--space-3);
}

.history li {
  display: grid;
}
</style>
