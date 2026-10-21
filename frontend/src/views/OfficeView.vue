<script setup lang="ts">
/**
 * Edit a Word, Excel or PowerPoint file in the browser with the company's own Collabora Online or
 * ONLYOFFICE server. Both are reached through the portal's own address, so the page never loads
 * anything from outside. While WordCraft / DeckCraft run (and HR did not choose otherwise), Word and
 * PowerPoint files go there instead.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter, type RouteLocationRaw } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import { api } from '@/lib/api'
import { errorText, t } from '@/lib/i18n'
import { craftApp, loadCraftConfig, loadOfficeConfig } from '@/lib/spaces'
import type { OfficeConfig, OfficeOpen, SpaceFileDetail } from '@/lib/types'
import { setActivity } from '@/lib/summary'
import { showToast } from '@/lib/toast'

declare global {
  interface Window {
    DocsAPI?: { DocEditor: new (id: string, config: Record<string, unknown>) => { destroyEditor: () => void } }
  }
}

const props = defineProps<{ id: string }>()
const route = useRoute()
const router = useRouter()
// "Edit together": stay in the office editor even where WordCraft / DeckCraft would open, so several people can
// work in the file at the same time
const together = route.query.together === '1'

const file = ref<SpaceFileDetail | null>(null)
const office = ref<OfficeConfig>({ engines: [], default: null, editable: {} })
const engine = ref<'collabora' | 'onlyoffice' | null>(null)
const session = ref<OfficeOpen | null>(null)
const error = ref<string | null>(null)
const loading = ref(true)
const form = ref<HTMLFormElement | null>(null)
let editor: { destroyEditor: () => void } | null = null

// ---------- WordCraft / DeckCraft, shown inside the portal (with this bar and its way back) ----------

interface CraftOpen {
  app: 'wordcraft' | 'deckcraft'
  url: string
  can_write: boolean
  /** While we may save: the lock that keeps others read-only. Renewed every minute, given back on leaving. */
  lock: string | null
  editing_by: string | null
}

const craft = ref<CraftOpen | null>(null)
const craftFrame = ref<HTMLIFrameElement | null>(null)
const leaveTo = ref<RouteLocationRaw | null>(null)
let leaving = false
let lockTimer: number | undefined

/** Someone else has the file open for editing: their name ('' when the office editor has it open), else null */
const editingBy = computed(() => craft.value?.editing_by ?? session.value?.editing_by ?? null)

async function renewLock() {
  const c = craft.value
  if (!c?.lock) return
  try {
    await api.post(`/api/craft/lock/${props.id}`, { lock: c.lock })
  } catch (e) {
    if ((e as { code?: string }).code !== 'file_locked') return // offline for a moment: try again next minute
    window.clearInterval(lockTimer)
    c.lock = null
    showToast(t('office.lockLost'), 'error')
  }
}

function releaseLock() {
  window.clearInterval(lockTimer)
  const lock = craft.value?.lock
  if (!lock) return
  craft.value!.lock = null
  // keepalive: the request still goes out when the tab is being closed
  void fetch(`/api/craft/lock/${props.id}?lock=${encodeURIComponent(lock)}`, {
    method: 'DELETE', keepalive: true, credentials: 'same-origin', headers: { 'X-Requested-With': 'OfficeHub' },
  }).catch(() => undefined)
}

/** Does the program have changes that are not saved yet? WordCraft says so to the browser's "leave page?"
 * check (same site, so we can ask it); DeckCraft cannot tell, so we ask the person. */
function maybeUnsaved(): boolean {
  if (!craft.value?.can_write) return false
  if (craft.value.app === 'deckcraft') return true
  try {
    const check = new Event('beforeunload', { cancelable: true })
    craftFrame.value?.contentWindow?.dispatchEvent(check)
    return check.defaultPrevented
  } catch {
    return true
  }
}

onBeforeRouteLeave((to) => {
  if (leaving || !craft.value || !maybeUnsaved()) return true
  leaveTo.value = to.fullPath
  return false
})

function leaveAnyway() {
  const to = leaveTo.value
  leaveTo.value = null
  if (!to) return
  leaving = true
  router.push(to)
}

const backTo = computed(() => {
  if (!file.value) return '/spaces'
  const folder = file.value.folder_id ? `?folder=${file.value.folder_id}` : ''
  return `/spaces/${file.value.space_id}/files${folder}`
})

function loadScript(src: string): Promise<void> {
  const existing = document.querySelector<HTMLScriptElement>(`script[data-office="${src}"]`)
  if (existing && window.DocsAPI) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = src
    script.dataset.office = src
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('script'))
    document.head.appendChild(script)
  })
}

function close() {
  router.push(backTo.value)
}

function onMessage(event: MessageEvent) {
  if (event.origin !== window.location.origin || typeof event.data !== 'string') return
  try {
    const message = JSON.parse(event.data) as { MessageId?: string; Values?: { Status?: string } }
    if (message.MessageId === 'App_LoadingStatus' && message.Values?.Status === 'Document_Loaded') loading.value = false
    if (message.MessageId === 'UI_Close') close()
  } catch {
    /* not a message from the editor */
  }
}

async function start() {
  editor?.destroyEditor()
  editor = null
  loading.value = true
  error.value = null
  session.value = null
  try {
    session.value = await api.post<OfficeOpen>(`/api/office/open/${props.id}`, { engine: engine.value, origin: window.location.origin })
    await nextTick()
    if (session.value.engine === 'collabora') {
      form.value?.submit()
      window.setTimeout(() => (loading.value = false), 8000) // older servers do not report when they are ready
    } else {
      await loadScript(session.value.script!)
      if (!window.DocsAPI) throw new Error('script')
      editor = new window.DocsAPI.DocEditor('office-onlyoffice', {
        ...session.value.config,
        events: {
          onDocumentReady: () => (loading.value = false),
          onRequestClose: close,
        },
      })
      window.setTimeout(() => (loading.value = false), 8000)
    }
  } catch (e) {
    loading.value = false
    error.value = e instanceof Error && e.message === 'script' ? t('office.unreachable') : errorText(e)
  }
}

async function switchEngine(value: 'collabora' | 'onlyoffice') {
  if (engine.value === value) return
  engine.value = value
  await start()
}

onMounted(async () => {
  window.addEventListener('message', onMessage)
  try {
    ;[file.value, office.value] = await Promise.all([api.get<SpaceFileDetail>(`/api/spaces/files/${props.id}`), loadOfficeConfig()])
    if (!together && office.value.prefer_craft && craftApp(await loadCraftConfig(), file.value.file_type)) {
      craft.value = await api.post<CraftOpen>(`/api/craft/open/${props.id}`)
      if (craft.value.lock) {
        lockTimer = window.setInterval(renewLock, 60_000)
        window.addEventListener('pagehide', releaseLock)
      }
      loading.value = false
      setActivity(`file:${props.id}`)
      return
    }
    engine.value = office.value.default
    if (!engine.value) {
      loading.value = false
      error.value = t('files.noOffice')
      return
    }
    await start()
    setActivity(`file:${props.id}`)
  } catch (e) {
    loading.value = false
    error.value = errorText(e)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('message', onMessage)
  window.removeEventListener('pagehide', releaseLock)
  releaseLock()
  editor?.destroyEditor()
  setActivity('')
})
</script>

<template>
  <div class="office-page">
    <header class="bar">
      <RouterLink :to="backTo" class="btn btn-ghost back"><AppIcon name="chevronLeft" :size="18" />{{ t('office.back') }}</RouterLink>
      <h1 class="title">
        <span>{{ file?.name ?? '…' }}</span>
        <span v-if="(session && !session.can_write) || (craft && !craft.can_write)" class="tag">{{ t('office.readOnly') }}</span>
        <span v-if="craft" class="tag">{{ t(`office.craft.${craft.app}`) }}</span>
      </h1>
      <div class="row">
        <RouterLink v-if="craft && office.default && (office.editable[office.default] ?? []).includes(file?.file_type ?? '')" :to="`/office/${props.id}?together=1`" class="btn btn-ghost" :title="t('files.editTogetherHint')"><AppIcon name="users" :size="18" /><span class="hide-sm">{{ t('files.editTogether') }}</span></RouterLink>
        <div v-if="office.engines.length > 1" class="segmented" role="group" :aria-label="t('office.openWith')">
          <button v-for="e in office.engines" :key="e" type="button" :aria-pressed="engine === e" @click="switchEngine(e)">{{ t(`office.engines.${e}`) }}</button>
        </div>
        <a v-if="file" class="btn btn-ghost" :href="`/api/spaces/files/${file.id}/download`" download><AppIcon name="download" :size="18" /><span class="hide-sm">{{ t('files.download') }}</span></a>
      </div>
    </header>

    <div class="stage">
      <div v-if="error" class="notice notice-warning" role="alert">
        <p>{{ error }}</p>
        <RouterLink :to="backTo" class="btn btn-secondary">{{ t('office.back') }}</RouterLink>
      </div>
      <template v-else>
        <div v-if="editingBy !== null" class="notice notice-info editing" role="status">
          <AppIcon name="edit" :size="18" />{{ editingBy ? t('office.editingBy', { name: editingBy }) : t('office.editingBySomeone') }}
        </div>
        <div v-if="loading" class="loading" role="status"><span class="spinner" aria-hidden="true" />{{ t('office.loading') }}</div>
        <template v-if="session?.engine === 'collabora'">
          <form ref="form" :action="session.action_url ?? ''" method="post" target="office-frame" class="visually-hidden">
            <input type="hidden" name="access_token" :value="session.access_token ?? ''" />
            <input type="hidden" name="access_token_ttl" :value="String(session.access_token_ttl ?? 0)" />
          </form>
          <iframe name="office-frame" class="frame" :title="file?.name ?? t('office.editor')" allow="clipboard-read *; clipboard-write *; fullscreen" allowfullscreen />
        </template>
        <div v-else-if="session?.engine === 'onlyoffice'" class="frame"><div id="office-onlyoffice" /></div>
        <iframe v-else-if="craft" ref="craftFrame" class="frame" :src="craft.url" :title="file?.name ?? t('office.editor')" allow="clipboard-read; clipboard-write; fullscreen; local-fonts" allowfullscreen />
      </template>
    </div>

    <BaseModal :open="leaveTo !== null" :title="t('office.leaveTitle')" :description="t(`office.leaveText.${craft?.app ?? 'wordcraft'}`)" :confirm-label="t('office.leaveAnyway')" :cancel-label="t('office.stay')" tone="danger" @close="leaveTo = null" @confirm="leaveAnyway" />
  </div>
</template>

<style scoped>
.office-page {
  display: grid;
  grid-template-rows: auto 1fr;
  height: calc(100dvh - var(--header-height, 64px));
}

.bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}

.title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 1;
  min-width: 0;
  font-size: var(--text-md);
}

.title > span:first-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag {
  padding: 1px 8px;
  border-radius: 99px;
  background: var(--color-neutral-soft);
  font-size: 0.75rem;
  font-weight: 600;
}

.stage {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--color-surface-muted);
}

.notice.editing {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  max-width: none;
  margin: 0;
  padding: var(--space-2) var(--space-4);
  border-width: 0 0 1px;
  border-radius: 0;
  font-size: var(--text-sm);
}

.frame,
.frame > :deep(*) {
  display: block;
  width: 100%;
  height: 100%;
  border: 0;
}

.frame {
  flex: 1;
  min-height: 0;
  height: auto;
}

.loading {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  background: var(--color-surface-muted);
  color: var(--color-text-muted);
  font-weight: 600;
  pointer-events: none;
}

.spinner {
  width: 22px;
  height: 22px;
  border: 3px solid var(--color-border);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: spin 800ms linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.notice {
  display: grid;
  gap: var(--space-3);
  justify-items: start;
  max-width: 560px;
  margin: var(--space-8) auto;
}

@media (max-width: 720px) {
  .hide-sm {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .spinner {
    animation-duration: 2s;
  }
}
</style>
