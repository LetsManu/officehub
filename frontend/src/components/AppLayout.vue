<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from './AppIcon.vue'
import CommandPalette from './CommandPalette.vue'
import IncomingCall from './IncomingCall.vue'
import MeetingReminders from './MeetingReminders.vue'
import NotificationBell from './NotificationBell.vue'
import StatusMenu from './StatusMenu.vue'
import UserAvatar from './UserAvatar.vue'
import { branding, logoUrl } from '@/lib/branding'
import { listenForNotificationClicks } from '@/lib/desktop'
import { canInstall, installApp } from '@/lib/install'
import { isStandalone, online, reload, updateReady } from '@/lib/pwa'
import { currentUser, publicConfig, signOut } from '@/lib/session'
import { quickLinks, resetPortal } from '@/lib/portal'
import { language, t } from '@/lib/i18n'
import { allPages, navGroups, type NavGroup } from '@/lib/navigation'
import { myDevice, type Device } from '@/lib/e2ee/identity'
import { appPlace, appSignedIn, appTexts, inApp, onAppEvent } from '@/lib/native'
import { refreshSummary, startSummary, stopSummary, summary } from '@/lib/summary'
import { applyTheme, theme } from '@/lib/theme'
import { showToast } from '@/lib/toast'
import { trapTab } from '@/lib/focus'

const route = useRoute()
const router = useRouter()
const menuOpen = ref(false)
const searchOpen = ref(false)
const drawer = ref<HTMLElement | null>(null)
const menuButton = ref<HTMLButtonElement | null>(null)
const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)
// Outside the installed app there is always a way to install it: the browser's own prompt where it offers one,
// otherwise the steps for this device.
const showInstall = !isStandalone() && !inApp()
function install() {
  if (canInstall.value) installApp()
  else router.push('/install')
}

/** The most specific menu entry that matches the current page (so /admin/audit does not also mark /admin). */
const activePath = computed(() => {
  const matches = [...allPages.value.map((p) => p.to), '/profile'].filter((to) =>
    to === '/' ? route.path === '/' : route.path === to || route.path.startsWith(`${to}/`),
  )
  return matches.sort((a, b) => b.length - a.length)[0] ?? null
})

function isActive(to: string): boolean {
  return activePath.value === to
}

// ---------- menu: full with groups, or a slim icon bar like Teams (remembered per browser) ----------

function remembered<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw === null ? fallback : (JSON.parse(raw) as T)
  } catch {
    return fallback
  }
}

function remember(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* private window */
  }
}

const compact = ref(remembered('officehub-nav-compact', false))
const folded = ref<string[]>(remembered('officehub-nav-folded', []))
const moreOpen = ref(false)
const moreButton = ref<HTMLButtonElement | null>(null)
const morePanel = ref<HTMLElement | null>(null)
const dailyItems = computed(() => navGroups.value[0]?.items ?? [])
const otherGroups = computed(() => navGroups.value.slice(1))
const moreActive = computed(() => otherGroups.value.some((g) => g.items.some((i) => isActive(i.to))))
const moreCount = computed(() => otherGroups.value.reduce((sum, g) => sum + g.items.reduce((n, i) => n + (i.count ?? 0), 0), 0))

function toggleCompact() {
  compact.value = !compact.value
  moreOpen.value = false
  remember('officehub-nav-compact', compact.value)
}

function isFolded(group: NavGroup) {
  // A folded group still opens when you are on one of its pages
  return !!group.collapsible && folded.value.includes(group.key) && !group.items.some((i) => isActive(i.to))
}

function toggleGroup(key: string) {
  folded.value = folded.value.includes(key) ? folded.value.filter((k) => k !== key) : [...folded.value, key]
  remember('officehub-nav-folded', folded.value)
}

function onDocumentClick(event: MouseEvent) {
  const target = event.target as Node
  if (moreOpen.value && !morePanel.value?.contains(target) && !moreButton.value?.contains(target)) moreOpen.value = false
}

function toggleTheme() {
  applyTheme(theme.value === 'dark' ? 'light' : 'dark')
}

async function logout() {
  await signOut().catch(() => undefined)
  resetPortal()
  stopSummary()
  showToast(t('app.signedOutToast'), 'info')
  router.push('/login')
}

function onDrawerKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape' && drawer.value) trapTab(event, drawer.value)
}

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  return Boolean(el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)))
}

/** Ctrl+K / ⌘K anywhere, or "/" when not typing, opens the search. */
function onGlobalKeydown(event: KeyboardEvent) {
  // The phone menu also closes with Esc when focus is outside it.
  if (event.key === 'Escape' && menuOpen.value && !searchOpen.value) {
    menuOpen.value = false
    return
  }
  if (event.key === 'Escape' && moreOpen.value) {
    moreOpen.value = false
    moreButton.value?.focus()
    return
  }
  if (searchOpen.value || document.querySelector('[aria-modal="true"]')) return
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    searchOpen.value = true
  } else if (event.key === '/' && !event.ctrlKey && !event.metaKey && !event.altKey && !isTyping(event.target)) {
    event.preventDefault()
    searchOpen.value = true
  }
}

// This browser's key for encrypted meetings (made the first time): a new device of mine waits for this one
const device = ref<Device | null>(null)
const deviceWaiting = computed(
  () => !!device.value && !device.value.pending && (summary.value.devices_pending ?? 0) > 0 && route.path !== '/profile',
)

// In the Windows / Android app: a click on one of its notifications opens the page here
const stopAppEvents = onAppEvent((e) => {
  if (e.navigate?.startsWith('/')) router.push(e.navigate)
})
watch(language, () => appTexts())
watch(() => route.path, (path) => appPlace(path), { immediate: true })

onMounted(() => {
  appSignedIn(true)
  appTexts()
  window.addEventListener('keydown', onGlobalKeydown)
  document.addEventListener('click', onDocumentClick)
  listenForNotificationClicks()
  startSummary()
})

watch(
  () => [publicConfig.value?.meetings_enabled, currentUser.value?.id, summary.value.devices_pending] as const,
  ([enabled, id]) => {
    if (enabled && id) void myDevice(String(id), !!device.value).then((d) => (device.value = d))
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  stopAppEvents()
  window.removeEventListener('keydown', onGlobalKeydown)
  document.removeEventListener('click', onDocumentClick)
  stopSummary()
})

let closedByNavigation = false

watch(menuOpen, async (open) => {
  await nextTick()
  if (open) drawer.value?.querySelector<HTMLElement>('a, button')?.focus()
  else if (!closedByNavigation) menuButton.value?.focus()
  closedByNavigation = false
})

watch(
  () => route.fullPath,
  () => {
    refreshSummary()
    moreOpen.value = false
    if (menuOpen.value) {
      // Focus moves to the new page content instead (see router.afterEach).
      closedByNavigation = true
      menuOpen.value = false
    }
  },
)
</script>

<template>
  <a href="#main" class="skip-link">{{ t('app.skipToContent') }}</a>
  <div class="shell" :class="{ compact: compact && !menuOpen }">
    <div v-if="menuOpen" class="drawer-backdrop" @click="menuOpen = false" />

    <aside
      id="sidebar"
      ref="drawer"
      class="sidebar"
      :class="{ open: menuOpen }"
      @keydown="menuOpen && onDrawerKeydown($event)"
    >
      <div class="sidebar-top">
        <RouterLink to="/" class="brand">
          <img v-if="branding.logo_version" :src="logoUrl()" alt="" class="logo-img" />
          <span v-else class="logo" aria-hidden="true"><AppIcon name="home" :size="18" /></span>
          <span class="brand-text">{{ branding.company_name || 'OfficeHub' }}</span>
        </RouterLink>
        <button v-if="menuOpen" type="button" class="btn btn-ghost btn-icon" :aria-label="t('app.closeMenu')" @click="menuOpen = false">
          <AppIcon name="close" />
        </button>
        <button
          v-else
          type="button"
          class="btn btn-ghost btn-icon collapse-btn desktop-only"
          :aria-label="compact ? t('nav.expand') : t('nav.collapse')"
          :title="compact ? t('nav.expand') : t('nav.collapse')"
          :aria-pressed="compact"
          @click="toggleCompact"
        >
          <AppIcon :name="compact ? 'chevronRight' : 'chevronLeft'" :size="18" />
        </button>
      </div>

      <!-- Slim icon bar: the everyday tools, everything else under "More" -->
      <nav v-if="compact && !menuOpen" class="rail" :aria-label="t('nav.main')">
        <ul class="rail-list">
          <li v-for="item in dailyItems" :key="item.to">
            <RouterLink :to="item.to" class="rail-link" :class="{ active: isActive(item.to) }" :aria-current="isActive(item.to) ? 'page' : undefined">
              <span class="rail-icon">
                <AppIcon :name="item.icon" />
                <span v-if="item.count" class="rail-badge">{{ item.count > 99 ? '99+' : item.count }}<span class="visually-hidden"> {{ t('nav.countOpen') }}</span></span>
              </span>
              <span class="rail-label">{{ item.label }}</span>
            </RouterLink>
          </li>
          <li>
            <button ref="moreButton" type="button" class="rail-link" :class="{ active: moreActive || moreOpen }" aria-haspopup="true" :aria-expanded="moreOpen" aria-controls="nav-more" @click="moreOpen = !moreOpen">
              <span class="rail-icon">
                <AppIcon name="dots" />
                <span v-if="moreCount" class="rail-badge">{{ moreCount > 99 ? '99+' : moreCount }}<span class="visually-hidden"> {{ t('nav.countOpen') }}</span></span>
              </span>
              <span class="rail-label">{{ t('nav.more') }}</span>
            </button>
          </li>
        </ul>
        <div v-if="moreOpen" id="nav-more" ref="morePanel" class="more-panel">
          <template v-for="group in otherGroups" :key="group.key">
            <p class="nav-heading">{{ group.label }}</p>
            <ul class="nav-list">
              <li v-for="item in group.items" :key="item.to">
                <RouterLink :to="item.to" class="nav-link" :class="{ active: isActive(item.to) }" :aria-current="isActive(item.to) ? 'page' : undefined">
                  <AppIcon :name="item.icon" />
                  <span class="grow">{{ item.label }}</span>
                  <span v-if="item.count" class="count-badge">{{ item.count }}<span class="visually-hidden"> {{ t('nav.countOpen') }}</span></span>
                </RouterLink>
              </li>
            </ul>
          </template>
          <template v-if="quickLinks.length">
            <p class="nav-heading">{{ t('nav.moreTools') }}</p>
            <ul class="nav-list">
              <li v-for="link in quickLinks" :key="link.id">
                <a :href="link.url" target="_blank" rel="noopener noreferrer" class="nav-link">
                  <AppIcon :name="link.icon" />
                  <span class="grow">{{ link.title }}</span>
                  <AppIcon name="external" :size="16" :label="t('nav.opensNewTab')" />
                </a>
              </li>
            </ul>
          </template>
        </div>
      </nav>

      <nav v-else class="nav" :aria-label="t('nav.main')">
        <template v-for="group in navGroups" :key="group.key">
          <p v-if="group.label && !group.collapsible" :id="`nav-${group.key}`" class="nav-heading">{{ group.label }}</p>
          <p v-else-if="group.label" :id="`nav-${group.key}`" class="nav-heading">
            <button type="button" class="fold" :aria-expanded="!isFolded(group)" :aria-controls="`navlist-${group.key}`" @click="toggleGroup(group.key)">
              {{ group.label }}<AppIcon :name="isFolded(group) ? 'chevronRight' : 'chevronDown'" :size="14" />
            </button>
          </p>
          <ul v-show="!isFolded(group)" :id="`navlist-${group.key}`" class="nav-list" :aria-labelledby="group.label ? `nav-${group.key}` : undefined">
            <li v-for="item in group.items" :key="item.to">
              <RouterLink :to="item.to" class="nav-link" :class="{ active: isActive(item.to) }" :aria-current="isActive(item.to) ? 'page' : undefined">
                <AppIcon :name="item.icon" />
                <span class="grow">{{ item.label }}</span>
                <span v-if="item.count" class="count-badge">
                  {{ item.count }}<span class="visually-hidden"> {{ t('nav.countOpen') }}</span>
                </span>
              </RouterLink>
            </li>
          </ul>
        </template>
        <template v-if="quickLinks.length">
          <p id="nav-tools" class="nav-heading">{{ t('nav.moreTools') }}</p>
          <ul class="nav-list" aria-labelledby="nav-tools">
            <li v-for="link in quickLinks" :key="link.id">
              <a :href="link.url" target="_blank" rel="noopener noreferrer" class="nav-link" :title="link.description || undefined">
                <AppIcon :name="link.icon" />
                <span class="grow">{{ link.title }}</span>
                <AppIcon name="external" :size="16" :label="t('nav.opensNewTab')" />
              </a>
            </li>
          </ul>
        </template>
      </nav>

      <div class="sidebar-bottom">
        <RouterLink
          v-if="currentUser"
          to="/profile"
          class="who"
          :class="{ active: isActive('/profile') }"
          :aria-current="isActive('/profile') ? 'page' : undefined"
          :aria-label="`${currentUser.full_name}, ${t('nav.profile')}`"
        >
          <UserAvatar :id="currentUser.id" :name="currentUser.full_name" :photo-version="currentUser.photo_version" status />
          <span class="who-text">
            <span class="who-name">{{ currentUser.full_name }}</span>
            <span class="who-role">{{ t(`roles.${currentUser.role}`) }}</span>
          </span>
        </RouterLink>
        <div class="bottom-actions">
          <button type="button" class="btn btn-ghost nav-action mobile-only" @click="toggleTheme">
            <AppIcon :name="theme === 'dark' ? 'sun' : 'moon'" />
            {{ theme === 'dark' ? t('app.lightMode') : t('app.darkMode') }}
          </button>
          <button v-if="showInstall" type="button" class="btn btn-ghost nav-action" :title="t('app.install')" @click="install">
            <AppIcon name="download" />
            <span class="action-label">{{ t('app.install') }}</span>
          </button>
          <button type="button" class="btn btn-ghost nav-action" :title="t('app.signOut')" @click="logout">
            <AppIcon name="logout" />
            <span class="action-label">{{ t('app.signOut') }}</span>
          </button>
          <RouterLink v-if="publicConfig?.version" to="/whats-new" class="version">
            {{ t('nav.whatsNew', { version: publicConfig.version }) }}
          </RouterLink>
        </div>
      </div>
    </aside>

    <div class="main-col">
      <header class="topbar">
        <button
          ref="menuButton"
          type="button"
          class="btn btn-ghost btn-icon menu-btn"
          :aria-label="t('app.openMenu')"
          aria-controls="sidebar"
          :aria-expanded="menuOpen"
          @click="menuOpen = true"
        >
          <AppIcon name="menu" :size="24" />
        </button>
        <RouterLink to="/" class="brand mobile-brand">
          <img v-if="branding.logo_version" :src="logoUrl()" alt="" class="logo-img" />
          <span v-else class="logo" aria-hidden="true"><AppIcon name="home" :size="18" /></span>
          <span class="brand-text">{{ branding.company_name || 'OfficeHub' }}</span>
        </RouterLink>

        <button type="button" class="search-trigger" aria-haspopup="dialog" :aria-label="t('search.trigger')" @click="searchOpen = true">
          <AppIcon name="search" :size="20" />
          <span class="search-label">{{ t('search.trigger') }}</span>
          <span class="shortcut" aria-hidden="true"><kbd>{{ isMac ? '⌘' : 'Ctrl' }}</kbd><kbd>K</kbd></span>
        </button>

        <div class="header-actions">
          <button
            type="button"
            class="btn btn-ghost btn-icon header-btn desktop-only"
            :aria-label="theme === 'dark' ? t('app.lightMode') : t('app.darkMode')"
            :title="theme === 'dark' ? t('app.lightMode') : t('app.darkMode')"
            @click="toggleTheme"
          >
            <AppIcon :name="theme === 'dark' ? 'sun' : 'moon'" />
          </button>
          <NotificationBell />
          <StatusMenu />
        </div>
      </header>

      <main id="main" class="content" :class="{ full: route.meta.full, wide: route.meta.wide }" tabindex="-1">
        <div v-if="!online" class="notice notice-warning app-banner" role="status">
          <AppIcon name="alert" />
          <span>{{ t('pwa.offline') }}</span>
        </div>
        <div v-else-if="updateReady" class="notice notice-info app-banner" role="status">
          <AppIcon name="download" />
          <span class="grow">{{ t('pwa.updated') }}</span>
          <button type="button" class="btn btn-primary" @click="reload">{{ t('pwa.reload') }}</button>
        </div>
        <div v-else-if="deviceWaiting" class="notice notice-info app-banner" role="status">
          <AppIcon name="shield" />
          <span class="grow">{{ t('keys.waitingBanner') }}</span>
          <RouterLink to="/profile#keys" class="btn btn-primary">{{ t('keys.waitingOpen') }}</RouterLink>
        </div>
        <slot />
      </main>
    </div>

    <CommandPalette :open="searchOpen" @close="searchOpen = false" />
    <IncomingCall v-if="publicConfig?.meetings_enabled" />
    <MeetingReminders />
  </div>
</template>

<style scoped>
.skip-link {
  position: absolute;
  left: var(--space-4);
  top: -100px;
  z-index: 300;
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  background: var(--color-primary);
  color: var(--color-on-primary);
  font-weight: 600;
}

.skip-link:focus {
  top: var(--space-4);
}

.shell {
  min-height: 100vh;
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-height: var(--touch);
  color: var(--color-text);
  font-family: var(--font-heading);
  font-weight: 600;
  font-size: var(--text-lg);
  letter-spacing: -0.01em;
  text-decoration: none;
}

.logo-img {
  width: 32px;
  height: 32px;
  object-fit: contain;
  border-radius: 8px;
}

.brand-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 170px;
}

.logo {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 9px;
  background: var(--color-highlight);
  color: #fff;
  box-shadow: 0 2px 6px rgb(29 78 216 / 0.3);
}

/* ---------- Sidebar ---------- */

.sidebar {
  position: fixed;
  inset: 0 auto 0 0;
  z-index: var(--z-drawer);
  display: flex;
  flex-direction: column;
  width: var(--sidebar-width);
  padding: var(--space-3) var(--space-3) var(--space-4);
  border-right: 1px solid var(--color-border);
  background: var(--color-surface);
  overflow-y: auto;
}

.sidebar-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: calc(var(--header-height) - var(--space-3));
  padding: 0 var(--space-2) var(--space-3);
}

.nav {
  flex: 1;
}

.nav-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 2px;
}

.nav-heading {
  margin: var(--space-5) var(--space-3) var(--space-2);
  font-size: var(--text-xs);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--color-text-subtle);
}

.nav-link,
.nav-action {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: var(--space-3);
  width: 100%;
  min-height: var(--touch);
  padding: 0 var(--space-3);
  border-radius: var(--radius-md);
  color: var(--color-text-muted);
  font-weight: 500;
  font-size: var(--text-sm);
  text-decoration: none;
  transition: background-color var(--t-fast) ease, color var(--t-fast) ease;
}

.nav-link:hover,
.nav-action:hover {
  background: var(--color-surface-muted);
  color: var(--color-text);
}

.nav-link.active {
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
  font-weight: 600;
}

/* Active marker: a short bar on the left edge */
.nav-link.active::before {
  content: '';
  position: absolute;
  left: -12px;
  top: 10px;
  bottom: 10px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--color-primary);
}

.sidebar-bottom {
  display: grid;
  gap: var(--space-2);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
}

.who {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-height: var(--touch);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  color: inherit;
  text-decoration: none;
}

.who:hover {
  background: var(--color-surface-muted);
}

.who.active {
  background: var(--color-primary-soft);
}

.avatar {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
  font-size: var(--text-sm);
  font-weight: 700;
}

.who-text {
  display: grid;
  min-width: 0;
}

.who-name {
  font-weight: 600;
  font-size: var(--text-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.who-role {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.bottom-actions {
  display: grid;
}

.grow {
  flex: 1;
}

.version {
  display: flex;
  align-items: center;
  min-height: var(--touch);
  padding: 0 var(--space-3);
  font-size: var(--text-xs);
  color: var(--color-text-subtle);
}

/* ---------- Header ---------- */

.main-col {
  margin-left: var(--sidebar-width);
  min-width: 0;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  height: var(--header-height);
  padding: 0 var(--space-6);
  border-bottom: 1px solid var(--color-border);
  background: color-mix(in srgb, var(--color-bg) 85%, transparent);
  backdrop-filter: blur(10px);
}

.menu-btn,
.mobile-brand,
.mobile-only {
  display: none;
}

.search-trigger {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex: 1;
  max-width: 520px;
  min-height: var(--touch);
  padding: 0 var(--space-2) 0 var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-text-subtle);
  font: inherit;
  font-size: var(--text-sm);
  text-align: left;
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition: border-color var(--t-fast) ease;
}

.search-trigger:hover {
  border-color: var(--color-border-strong);
}

.search-label {
  flex: 1;
}

.shortcut {
  display: inline-flex;
  gap: 4px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  margin-left: auto;
}

.header-btn {
  color: var(--color-text-muted);
}

.header-btn:hover {
  color: var(--color-text);
}


.content {
  padding: var(--space-6) var(--space-6) var(--space-7);
  max-width: 1180px;
}

.app-banner {
  align-items: center;
  margin-bottom: var(--space-4);
}

.app-banner .grow {
  flex: 1;
}

.content:focus {
  outline: none;
}

.content.wide {
  max-width: none;
}

.content.full {
  max-width: none;
  padding: 0;
}

.drawer-backdrop {
  display: none;
}

/* ---------- Foldable groups ---------- */

.fold {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  letter-spacing: inherit;
  text-transform: inherit;
  cursor: pointer;
}

.fold:hover {
  color: var(--color-text);
}

.collapse-btn {
  flex: none;
  color: var(--color-text-subtle);
}

/* ---------- Slim icon bar (like Teams) ---------- */

.shell.compact {
  --sidebar-width: 84px;
}

.compact .sidebar {
  align-items: center;
  padding: var(--space-3) var(--space-2) var(--space-4);
  overflow: visible;
}

.compact .sidebar-top {
  flex-direction: column;
  gap: var(--space-2);
  padding: 0 0 var(--space-3);
}

.compact .brand-text,
.compact .who-text,
.compact .action-label,
.compact .version {
  display: none;
}

.compact .who,
.compact .nav-action {
  justify-content: center;
  padding: var(--space-2);
}

.rail {
  position: relative;
  flex: 1;
  width: 100%;
}

.rail-list {
  display: grid;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.rail-link {
  position: relative;
  display: grid;
  justify-items: center;
  gap: 2px;
  width: 100%;
  padding: var(--space-2) 2px;
  border: 0;
  border-radius: var(--radius-md);
  background: none;
  color: var(--color-text-muted);
  font: inherit;
  font-size: 0.7rem;
  font-weight: 500;
  text-align: center;
  text-decoration: none;
  cursor: pointer;
}

.rail-link:hover {
  background: var(--color-surface-muted);
  color: var(--color-text);
}

.rail-link.active {
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
  font-weight: 600;
}

.rail-link.active::before {
  content: '';
  position: absolute;
  left: -8px;
  top: 12px;
  bottom: 12px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--color-primary);
}

.rail-icon {
  position: relative;
  display: grid;
}

.rail-badge {
  position: absolute;
  top: -6px;
  right: -12px;
  min-width: 18px;
  padding: 0 5px;
  border-radius: 99px;
  background: var(--color-badge);
  color: var(--color-on-badge);
  font-size: 0.68rem;
  font-weight: 700;
  line-height: 18px;
}

.rail-label {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.more-panel {
  position: absolute;
  z-index: calc(var(--z-drawer) + 1);
  top: 0;
  left: calc(100% + var(--space-3));
  width: 260px;
  max-height: calc(100vh - var(--header-height) - var(--space-4));
  padding: var(--space-2) var(--space-3) var(--space-3);
  overflow-y: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg, 14px);
  background: var(--color-surface-raised);
  box-shadow: var(--shadow-overlay);
}

.more-panel .nav-heading:first-child {
  margin-top: var(--space-2);
}

@media (max-width: 899px) {
  .main-col {
    margin-left: 0;
  }

  .topbar {
    gap: var(--space-2);
    padding: 0 var(--space-2);
    background: var(--color-surface);
    backdrop-filter: none;
  }

  .menu-btn,
  .mobile-brand {
    display: inline-flex;
  }

  .mobile-only {
    display: flex;
  }

  .desktop-only {
    display: none;
  }

  .search-trigger {
    flex: 0 0 var(--touch);
    justify-content: center;
    width: var(--touch);
    padding: 0;
    margin-left: auto;
    border-color: transparent;
    background: transparent;
    box-shadow: none;
    color: var(--color-text-muted);
  }

  .search-label,
  .shortcut {
    display: none;
  }

  .header-actions {
    margin-left: 0;
  }

  .sidebar {
    width: min(86vw, 320px);
    transform: translateX(-100%);
    visibility: hidden;
    transition: transform var(--t-med) var(--ease), visibility var(--t-med);
  }

  .sidebar.open {
    transform: none;
    visibility: visible;
    box-shadow: var(--shadow-overlay);
  }

  .drawer-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    z-index: calc(var(--z-drawer) - 1);
    background: var(--backdrop);
  }

  .content {
    padding: var(--space-5) var(--space-4) var(--space-7);
  }
}
</style>
