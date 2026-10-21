<script setup lang="ts">
/**
 * One search box for everything: pages, common actions, people, documents,
 * news, requests and tools. Opens with Ctrl+K (⌘K) or "/".
 */
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from './AppIcon.vue'
import { api } from '@/lib/api'
import { trapTab } from '@/lib/focus'
import { t } from '@/lib/i18n'
import { allPages } from '@/lib/navigation'
import { quickLinks } from '@/lib/portal'
import { TILES } from '@/lib/tiles'
import type { SearchResults } from '@/lib/types'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()

interface Option {
  id: string
  group: string
  icon: string
  title: string
  subtitle?: string
  to: string
  external?: boolean
}

const RECENT_KEY = 'officehub.recentSearches'
const router = useRouter()
const query = ref('')
const results = ref<SearchResults | null>(null)
const searching = ref(false)
const active = ref(0)
const input = ref<HTMLInputElement | null>(null)
const dialog = ref<HTMLElement | null>(null)
const recent = ref<string[]>(readRecent())
let returnFocusTo: HTMLElement | null = null
let timer: number | undefined
let requestNumber = 0

function readRecent(): string[] {
  try {
    const value = JSON.parse(localStorage.getItem(RECENT_KEY) ?? '[]')
    return Array.isArray(value) ? value.filter((v) => typeof v === 'string').slice(0, 5) : []
  } catch {
    return []
  }
}

function remember(term: string) {
  const clean = term.trim()
  if (clean.length < 2) return
  recent.value = [clean, ...recent.value.filter((v) => v.toLowerCase() !== clean.toLowerCase())].slice(0, 5)
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(recent.value))
  } catch {
    /* not remembered */
  }
}

function clearRecent() {
  recent.value = []
  try {
    localStorage.removeItem(RECENT_KEY)
  } catch {
    /* ignore */
  }
  input.value?.focus()
}

function matches(text: string, term: string): boolean {
  return text.toLowerCase().includes(term.toLowerCase())
}

const options = computed<Option[]>(() => {
  const term = query.value.trim()
  const list: Option[] = []
  const actions = TILES.filter((tile) => tile.to.startsWith('/requests/new')).map((tile) => ({
    id: `action-${tile.key}`,
    group: 'actions',
    icon: tile.icon,
    title: t(tile.label),
    to: tile.to,
  }))
  const pages = allPages.value.map((page) => ({ id: `page-${page.to}`, group: 'pages', icon: page.icon, title: page.label, to: page.to }))

  if (!term) {
    return [...actions.slice(0, 4), ...pages.slice(0, 6)]
  }
  list.push(...actions.filter((o) => matches(o.title, term)))
  list.push(...pages.filter((o) => matches(o.title, term)))
  const r = results.value
  if (r) {
    for (const p of r.people) {
      list.push({ id: `person-${p.id}`, group: 'people', icon: 'user', title: p.full_name, subtitle: [p.job_title, p.department].filter(Boolean).join(' · '), to: `/people?q=${encodeURIComponent(p.full_name)}` })
    }
    for (const d of r.documents) list.push({ id: `doc-${d.id}`, group: 'documents', icon: 'file', title: d.title, subtitle: t(`documents.categories.${d.subtitle}`), to: d.link })
    for (const a of r.announcements) list.push({ id: `news-${a.id}`, group: 'announcements', icon: 'megaphone', title: a.title, to: a.link })
    for (const q of r.requests) {
      const [type, status] = q.subtitle.split(':')
      list.push({ id: `req-${q.id}`, group: 'requests', icon: 'inbox', title: q.title, subtitle: `${t(`requestTypes.${type}`)} · ${t(`statuses.${status}`)}`, to: q.link })
    }
    for (const l of r.links) list.push({ id: `link-${l.id}`, group: 'links', icon: 'external', title: l.title, subtitle: l.subtitle, to: l.link, external: true })
    for (const w of r.workspace ?? []) {
      const [kind, space] = w.subtitle.split(':')
      const icon = kind === 'file' ? 'folder' : kind === 'page' ? 'book' : 'kanban'
      list.push({ id: `ws-${kind}-${w.id}`, group: 'workspace', icon, title: w.title, subtitle: `${t(`search.kinds.${kind}`)} · ${space}`, to: w.link })
    }
  } else {
    for (const l of quickLinks.value.filter((link) => matches(link.title, term))) {
      list.push({ id: `link-${l.id}`, group: 'links', icon: 'external', title: l.title, subtitle: l.description, to: l.url, external: true })
    }
  }
  list.push({ id: 'all-documents', group: 'more', icon: 'search', title: t('search.inDocuments', { query: term }), to: `/documents?q=${encodeURIComponent(term)}` })
  return list
})

const groups = computed(() => {
  const out: { key: string; options: (Option & { index: number })[] }[] = []
  options.value.forEach((option, index) => {
    let group = out.find((g) => g.key === option.group)
    if (!group) out.push((group = { key: option.group, options: [] }))
    group.options.push({ ...option, index })
  })
  return out
})

const activeId = computed(() => (options.value[active.value] ? `cmd-${options.value[active.value].id}` : undefined))
const noMatches = computed(() => query.value.trim().length >= 2 && !searching.value && options.value.length <= 1)

async function search() {
  const term = query.value.trim()
  const current = ++requestNumber
  if (term.length < 2) {
    results.value = null
    searching.value = false
    return
  }
  searching.value = true
  try {
    const found = await api.get<SearchResults>(`/api/search?q=${encodeURIComponent(term)}`)
    if (current === requestNumber) results.value = found
  } catch {
    if (current === requestNumber) results.value = null
  } finally {
    if (current === requestNumber) searching.value = false
  }
}

watch(query, () => {
  active.value = 0
  window.clearTimeout(timer)
  timer = window.setTimeout(search, 200)
})

watch(options, () => {
  if (active.value >= options.value.length) active.value = Math.max(0, options.value.length - 1)
})

function choose(option: Option | undefined) {
  if (!option) return
  remember(query.value)
  emit('close')
  if (option.external) window.open(option.to, '_blank', 'noopener,noreferrer')
  else router.push(option.to)
}

function scrollActive() {
  nextTick(() => dialog.value?.querySelector(`#${CSS.escape(activeId.value ?? '')}`)?.scrollIntoView({ block: 'nearest' }))
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    emit('close')
  } else if (event.key === 'ArrowDown') {
    event.preventDefault()
    active.value = (active.value + 1) % Math.max(1, options.value.length)
    scrollActive()
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    active.value = (active.value - 1 + options.value.length) % Math.max(1, options.value.length)
    scrollActive()
  } else if (event.key === 'Enter' && event.target === input.value) {
    event.preventDefault()
    choose(options.value[active.value])
  } else if (dialog.value) {
    trapTab(event, dialog.value)
  }
}

watch(
  () => props.open,
  async (open) => {
    if (open) {
      returnFocusTo = document.activeElement as HTMLElement | null
      query.value = ''
      results.value = null
      active.value = 0
      recent.value = readRecent()
      document.body.style.overflow = 'hidden'
      await nextTick()
      input.value?.focus()
    } else {
      document.body.style.overflow = ''
      returnFocusTo?.focus?.()
    }
  },
)
</script>

<template>
  <Teleport to="body">
    <Transition name="palette">
      <div v-if="open" class="palette-backdrop" @mousedown.self="emit('close')">
        <div ref="dialog" class="palette" role="dialog" aria-modal="true" :aria-label="t('search.title')" @keydown="onKeydown">
          <div class="search-row">
            <AppIcon name="search" class="lead" />
            <input
              ref="input"
              v-model="query"
              class="search-input"
              type="text"
              role="combobox"
              aria-autocomplete="list"
              aria-expanded="true"
              aria-controls="cmd-list"
              :aria-activedescendant="activeId"
              :aria-label="t('search.title')"
              :placeholder="t('search.placeholder')"
              autocomplete="off"
              spellcheck="false"
            />
            <span v-if="searching" class="spinner" aria-hidden="true" />
            <button type="button" class="btn btn-ghost esc" @click="emit('close')">
              <kbd>Esc</kbd><span class="visually-hidden">{{ t('app.close') }}</span>
            </button>
          </div>

          <div v-if="!query.trim() && recent.length" class="recent">
            <div class="row-between">
              <p class="group-label">{{ t('search.recent') }}</p>
              <button type="button" class="btn btn-ghost clear" @click="clearRecent">{{ t('search.clearRecent') }}</button>
            </div>
            <div class="row chips">
              <button v-for="term in recent" :key="term" type="button" class="chip" @click="query = term; input?.focus()">
                <AppIcon name="clock" :size="14" />{{ term }}
              </button>
            </div>
          </div>

          <div id="cmd-list" class="results" role="listbox" :aria-label="t('search.results')">
            <div v-for="group in groups" :key="group.key" role="group" :aria-labelledby="`cmd-group-${group.key}`">
              <p :id="`cmd-group-${group.key}`" class="group-label">{{ t(`search.groups.${group.key}`) }}</p>
              <div
                v-for="option in group.options"
                :id="`cmd-${option.id}`"
                :key="option.id"
                role="option"
                class="option"
                :class="{ active: option.index === active }"
                :aria-selected="option.index === active"
                @mousemove="active = option.index"
                @click="choose(option)"
              >
                <span class="option-icon"><AppIcon :name="option.icon" :size="18" /></span>
                <span class="option-text">
                  <span class="option-title">{{ option.title }}</span>
                  <span v-if="option.subtitle" class="muted small">{{ option.subtitle }}</span>
                </span>
                <AppIcon v-if="option.external" name="external" :size="16" :label="t('nav.opensNewTab')" />
                <AppIcon v-else-if="option.index === active" name="chevronRight" :size="16" />
              </div>
            </div>
            <p v-if="noMatches" class="no-results muted" role="status">{{ t('search.noResults', { query: query.trim() }) }}</p>
          </div>

          <footer class="palette-foot muted small">
            <span><kbd>↑</kbd><kbd>↓</kbd> {{ t('search.hintMove') }}</span>
            <span><kbd>↵</kbd> {{ t('search.hintOpen') }}</span>
            <span><kbd>Esc</kbd> {{ t('search.hintClose') }}</span>
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.palette-backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal);
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding: 10vh var(--space-3) var(--space-3);
  background: var(--backdrop);
}

.palette {
  display: flex;
  flex-direction: column;
  width: min(640px, 100%);
  max-height: min(620px, 80vh);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface-raised);
  box-shadow: var(--shadow-overlay);
  overflow: hidden;
}

.search-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-2) var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.lead {
  color: var(--color-text-muted);
  flex-shrink: 0;
}

.search-input {
  flex: 1;
  min-width: 0;
  min-height: 52px;
  border: 0;
  background: transparent;
  color: var(--color-text);
  font: inherit;
  font-size: var(--text-lg);
}

.search-input:focus {
  outline: none;
}

.esc {
  min-height: 36px;
  padding: 0 var(--space-2);
}

.spinner {
  width: 18px;
  height: 18px;
  border: 2px solid var(--color-border-strong);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.recent {
  padding: var(--space-3) var(--space-4) 0;
}

.chips {
  gap: var(--space-2);
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 36px;
  padding: 0 var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-surface);
  color: var(--color-text);
  font: inherit;
  font-size: var(--text-sm);
  cursor: pointer;
}

.chip:hover {
  border-color: var(--color-primary);
}

.clear {
  min-height: 32px;
  padding: 0 var(--space-2);
  font-size: var(--text-xs);
}

.results {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-2);
}

.group-label {
  margin: var(--space-3) var(--space-3) var(--space-1);
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--color-text-subtle);
}

.recent .group-label {
  margin: 0;
}

.option {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-height: 48px;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
}

.option.active {
  background: var(--color-primary-soft);
}

.option-icon {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  background: var(--color-neutral-soft);
  color: var(--color-text-muted);
  flex-shrink: 0;
}

.option.active .option-icon {
  background: var(--color-surface);
  color: var(--color-primary-text);
}

.option-text {
  display: grid;
  flex: 1;
  min-width: 0;
}

.option-title {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.no-results {
  padding: var(--space-4) var(--space-3);
}

.palette-foot {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  padding: var(--space-2) var(--space-4);
  border-top: 1px solid var(--color-border);
  background: var(--color-surface-muted);
}

.palette-foot span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.palette-enter-active {
  transition: opacity var(--t-med) ease;
}

.palette-enter-active .palette {
  transition: transform var(--t-med) var(--ease);
}

.palette-leave-active {
  transition: opacity var(--t-fast) ease;
}

.palette-enter-from,
.palette-leave-to {
  opacity: 0;
}

.palette-enter-from .palette {
  transform: translateY(-8px) scale(0.98);
}

@media (max-width: 640px) {
  .palette-backdrop {
    padding: 0;
  }

  .palette {
    max-height: 100vh;
    height: 100%;
    border-radius: 0;
  }

  .palette-foot {
    display: none;
  }
}
</style>
