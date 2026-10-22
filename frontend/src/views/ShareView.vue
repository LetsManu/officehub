<script setup lang="ts">
/**
 * What another app shared with the installed portal (photos, documents, a link or text). The service worker
 * keeps it until the person decides where it goes: files into a space, text into a chat.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import FormField from '@/components/FormField.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api } from '@/lib/api'
import { appKind } from '@/lib/native'
import { errorText, formatFileSize, t } from '@/lib/i18n'
import { showToast } from '@/lib/toast'
import type { Conversation, Space } from '@/lib/types'

const CACHE = 'officehub-share'

interface SharedMeta {
  title: string
  text: string
  url: string
  files: { name: string; type: string; size: number }[]
}

const router = useRouter()
const route = useRoute()
const loading = ref(true)
const files = ref<File[]>([])
const text = ref('')
const spaces = ref<Space[]>([])
const conversations = ref<Conversation[]>([])
const spaceId = ref<number | null>(null)
const chatId = ref<number | null>(null)
const busy = ref(false)
const error = ref('')

const empty = computed(() => !files.value.length && !text.value)

/** The Android app keeps what was shared with it until this page asks (only its WebView answers /__app/). */
async function fromApp() {
  if (route.query.from !== 'app' || appKind() !== 'android' || !('caches' in window)) return
  const meta = await fetch('/__app/share/meta', { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).catch(() => null)
  if (!meta) return
  const cache = await caches.open(CACHE)
  for (const key of await cache.keys()) await cache.delete(key)
  for (const [i] of (meta as SharedMeta).files.entries()) {
    const file = await fetch(`/__app/share/file/${i}`, { cache: 'no-store' }).catch(() => null)
    if (file?.ok) await cache.put(`/share/file/${i}`, new Response(await file.blob(), { headers: { 'Content-Type': file.headers.get('Content-Type') || 'application/octet-stream' } }))
  }
  await cache.put('/share/meta', new Response(JSON.stringify(meta), { headers: { 'Content-Type': 'application/json' } }))
}

async function load() {
  if (!('caches' in window)) return
  const cache = await caches.open(CACHE)
  const meta = await cache.match('/share/meta')
  if (!meta) return
  const shared = (await meta.json()) as SharedMeta
  // A link usually comes as text and url at once; show each part only once.
  const parts = [...new Set([shared.title, shared.text, shared.url].map((p) => p.trim()).filter(Boolean))]
  text.value = parts.filter((p) => !parts.some((q) => q !== p && q.includes(p))).join('\n')
  const found: File[] = []
  for (const [i, f] of shared.files.entries()) {
    const hit = await cache.match(`/share/file/${i}`)
    if (hit) found.push(new File([await hit.blob()], f.name, { type: f.type }))
  }
  files.value = found
}

async function clear() {
  if ('caches' in window) await caches.delete(CACHE)
}

onMounted(async () => {
  try {
    await fromApp()
    await load()
    const [s, c] = await Promise.all([api.get<Space[]>('/api/spaces'), api.get<Conversation[]>('/api/chat')])
    spaces.value = s.filter((x) => x.my_role && !x.archived)
    conversations.value = c
    spaceId.value = spaces.value[0]?.id ?? null
    chatId.value = conversations.value[0]?.id ?? null
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
})

/** Keep only what is still left to hand on (so coming back here does not offer done things again). */
async function finish() {
  await clear()
  if ((!files.value.length && !text.value) || !('caches' in window)) return
  const cache = await caches.open(CACHE)
  await Promise.all(files.value.map((f, i) => cache.put(`/share/file/${i}`, new Response(f, { headers: { 'Content-Type': f.type } }))))
  const meta: SharedMeta = { title: '', text: text.value, url: '', files: files.value.map((f) => ({ name: f.name, type: f.type, size: f.size })) }
  await cache.put('/share/meta', new Response(JSON.stringify(meta), { headers: { 'Content-Type': 'application/json' } }))
}

async function upload() {
  if (!spaceId.value) return
  busy.value = true
  error.value = ''
  try {
    for (const file of files.value) {
      const form = new FormData()
      form.append('file', file)
      await api.post(`/api/spaces/${spaceId.value}/files`, form)
    }
    showToast(t('share.uploaded', { n: files.value.length }))
    files.value = []
    await finish()
    router.push(`/spaces/${spaceId.value}/files`)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    busy.value = false
  }
}

async function send() {
  if (!chatId.value || !text.value.trim()) return
  busy.value = true
  error.value = ''
  try {
    await api.post(`/api/chat/${chatId.value}/messages`, { body: text.value.trim() })
    showToast(t('share.sent'))
    const id = chatId.value
    text.value = ''
    await finish()
    if (!files.value.length) router.push(`/chat/${id}`)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    busy.value = false
  }
}

async function discard() {
  files.value = []
  text.value = ''
  await clear()
  router.push('/')
}

function chatName(c: Conversation): string {
  return c.space_name ? `${c.space_name} · ${c.name}` : c.name
}
</script>

<template>
  <div class="page share-page stack">
    <PageHeader :title="t('share.title')" :subtitle="t('share.subtitle')" back-to="/" />

    <p v-if="loading" class="muted">{{ t('app.loading') }}</p>
    <EmptyState v-else-if="empty" icon="upload" :message="t('share.empty')" :action-label="t('share.toStart')" action-to="/" />

    <template v-else>
      <div v-if="error" class="notice notice-danger" role="alert">
        <AppIcon name="alert" />
        <span>{{ error }}</span>
      </div>

      <section v-if="files.length" class="card stack">
        <h2>{{ t('share.filesTitle', { n: files.length }) }}</h2>
        <ul class="list">
          <li v-for="f in files" :key="f.name" class="file">
            <AppIcon name="file" />
            <span class="grow">{{ f.name }}</span>
            <span class="muted small">{{ formatFileSize(f.size) }}</span>
          </li>
        </ul>
        <p v-if="!spaces.length" class="muted">{{ t('share.noSpaces') }}</p>
        <template v-else>
          <FormField id="share-space" :label="t('share.space')" :hint="t('share.spaceHint')">
            <template #default="{ attrs }">
              <select v-bind="attrs" v-model="spaceId" class="select">
                <option v-for="s in spaces" :key="s.id" :value="s.id">{{ s.name }}</option>
              </select>
            </template>
          </FormField>
          <div class="actions">
            <button type="button" class="btn btn-primary" :disabled="busy || !spaceId" @click="upload">
              <AppIcon name="upload" />
              {{ t('share.upload') }}
            </button>
          </div>
        </template>
      </section>

      <section v-if="text" class="card stack">
        <h2>{{ t('share.textTitle') }}</h2>
        <FormField id="share-text" :label="t('share.message')">
          <template #default="{ attrs }">
            <textarea v-bind="attrs" v-model="text" class="textarea" rows="4" />
          </template>
        </FormField>
        <p v-if="!conversations.length" class="muted">{{ t('share.noChats') }}</p>
        <template v-else>
          <FormField id="share-chat" :label="t('share.chat')">
            <template #default="{ attrs }">
              <select v-bind="attrs" v-model="chatId" class="select">
                <option v-for="c in conversations" :key="c.id" :value="c.id">{{ chatName(c) }}</option>
              </select>
            </template>
          </FormField>
          <div class="actions">
            <button type="button" class="btn btn-primary" :disabled="busy || !chatId || !text.trim()" @click="send">
              <AppIcon name="send" />
              {{ t('share.send') }}
            </button>
          </div>
        </template>
      </section>

      <div>
        <button type="button" class="btn btn-ghost" :disabled="busy" @click="discard">{{ t('share.discard') }}</button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.share-page {
  max-width: 760px;
}

.file {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.grow {
  flex: 1;
  overflow-wrap: anywhere;
}

.actions {
  display: flex;
  justify-content: flex-end;
}
</style>
