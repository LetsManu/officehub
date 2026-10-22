<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from './AppIcon.vue'
import CommandPalette from './CommandPalette.vue'
import IncomingCall from './IncomingCall.vue'
import MeetingReminders from './MeetingReminders.vue'
import StatusMenu from './StatusMenu.vue'
import UserAvatar from './UserAvatar.vue'
import { branding, logoUrl } from '@/lib/branding'
import { listenForNotificationClicks } from '@/lib/desktop'
import { canInstall, installApp } from '@/lib/install'
import { isStandalone, online, reload, updateReady } from '@/lib/pwa'
import { currentUser, publicConfig, roleNames, signOut } from '@/lib/session'
import { quickLinks, resetPortal } from '@/lib/portal'
import { language, t } from '@/lib/i18n'
import { allPages, navGroups, type NavGroup } from '@/lib/navigation'
import { RAIL_PATHS, appGroups, isPinned, notePlace, pinnedItems, railItems, railTarget, sectionOf, togglePin } from '@/lib/rail'
import { myDevice, type Device } from '@/lib/e2ee/identity'
import { appCounts, appKind, appPlace, appScrolled, appSignedIn, appSyncCredentials, appTexts, inApp, onAppEvent } from '@/lib/native'
import { changeMyPresence, myPresence } from '@/lib/presence'
import { api } from '@/lib/api'
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
const pagePaths = computed(() => [...allPages.value.map((p) => p.to), '/profile'])
const activePath = computed(() => sectionOf(route.path, pagePaths.value))

function isActive(to: string): boolean {
  return activePath.value === to
}

/** Rail click: back to where you were in that tool, like Teams. */
function target(to: string): string {
  return railTarget(to, activePath.value)
}

// ---------- groups in the phone menu can be folded (remembered per browser) ----------

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

const folded = ref<string[]>(remembered('officehub-nav-folded', []))

function isFolded(group: NavGroup) {
  // A folded group still opens when you are on one of its pages
  return !!group.collapsible && folded.value.includes(group.key) && !group.items.some((i) => isActive(i.to))
}

function toggleGroup(key: string) {
  folded.value = folded.value.includes(key) ? folded.value.filter((k) => k !== key) : [...folded.value, key]
  remember('officehub-nav-folded', folded.value)
}

// ---------- "Apps" flyout with everything else (pin to the bar), and the "…" settings menu ----------

const appsOpen = ref(false)
const appsButton = ref<HTMLButtonElement | null>(null)
const appsPanel = ref<HTMLElement | null>(null)
const pinnedPaths = computed(() => pinnedItems.value.map((i) => i.to))
const appsActive = computed(() => {
  const here = activePath.value
  return !!here && !RAIL_PATHS.includes(here) && !pinnedPaths.value.includes(here) && here !== '/help' && here !== '/profile'
})
const appsCount = computed(() =>
  appGroups.value.reduce((sum, g) => sum + g.items.reduce((n, i) => n + (pinnedPaths.value.includes(i.to) ? 0 : i.count ?? 0), 0), 0),
)
const settingsOpen = ref(false)
const settingsButton = ref<HTMLButtonElement | null>(null)
const settingsPanel = ref<HTMLElement | null>(null)

watch(appsOpen, async (open) => {
  if (!open) return
  settingsOpen.value = false
  await nextTick()
  appsPanel.value?.querySelector<HTMLElement>('a, button')?.focus({ preventScroll: true })
})

watch(settingsOpen, async (open) => {
  if (!open) return
  appsOpen.value = false
  await nextTick()
  settingsPanel.value?.querySelector<HTMLElement>('a, button')?.focus()
})

function onDocumentClick(event: MouseEvent) {
  const target = event.target as Node
  if (appsOpen.value && !appsPanel.value?.contains(target) && !appsButton.value?.contains(target)) appsOpen.value = false
  if (settingsOpen.value && !settingsPanel.value?.contains(target) && !settingsButton.value?.contains(target)) settingsOpen.value = false
}

// Phones in the browser get Teams' tab bar at the bottom (the Android app has its own)
const showTabs = appKind() !== 'android'
const tabItems = computed(() => railItems.value.filter((i) => ['/', '/activity', '/chat', '/calendar'].includes(i.to)))
const tabsMoreActive = computed(() => !!activePath.value && !tabItems.value.some((i) => i.to === activePath.value))

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
  if (event.key === 'Escape' && appsOpen.value) {
    appsOpen.value = false
    appsButton.value?.focus()
    return
  }
  if (event.key === 'Escape' && settingsOpen.value) {
    settingsOpen.value = false
    settingsButton.value?.focus()
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
  if (e.menu) menuOpen.value = true
  if (e.status) void changeMyPresence(e.status, myPresence.value.text, currentUser.value?.id).catch(() => undefined)
  if (e.syncSetup) void setUpFolder(e.syncSetup.device)
})
watch(() => [summary.value.unread, summary.value.chat_unread] as const, ([activity, chat]) => appCounts(activity, chat), { immediate: true })
// Android: pull to refresh only when the page and the list under the finger are at their very top (a chat scrolled
// up must scroll, not reload)
let atTop = true
let touched: EventTarget | null = null
function canPull(): boolean {
  if (window.scrollY > 0) return false
  for (let el = touched instanceof Element ? touched : null; el && el !== document.body; el = el.parentElement) {
    if (el.scrollTop > 0) return false
  }
  return true
}
function onScroll() {
  const top = canPull()
  if (top !== atTop) appScrolled((atTop = top))
}
function onTouch(event: TouchEvent) {
  touched = event.target
  onScroll()
}
if (appKind() === 'android') {
  window.addEventListener('scroll', onScroll, { passive: true, capture: true })
  window.addEventListener('touchstart', onTouch, { passive: true, capture: true })
}

/** Windows app: the OfficeHub folder in Explorer signs in with its own app password (listed under Profile). */
let settingUp = false
async function setUpFolder(device: string) {
  if (settingUp || !currentUser.value) return
  settingUp = true
  try {
    const name = t('install.folderPassword', { device: device || 'Windows' }).slice(0, 80)
    const created = await api.post<{ password: string }>('/api/profile/app-passwords', { name })
    appSyncCredentials(currentUser.value.email, created.password)
  } catch {
    // Too many app passwords or offline: asked again at the next start
  } finally {
    settingUp = false
  }
}
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
  window.removeEventListener('scroll', onScroll, { capture: true })
  window.removeEventListener('touchstart', onTouch, { capture: true })
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
    appsOpen.value = false
    settingsOpen.value = false
    // A full-screen page (a meeting) is not a place to come back to with a click
    if (!route.meta.full) notePlace(sectionOf(route.path, pagePaths.value), route.fullPath)
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
  <div class="shell" :class="{ 'with-tabs': showTabs }">
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
      <RouterLink to="/" class="brand">
        <img v-if="branding.logo_version" :src="logoUrl()" alt="" class="logo-img" />
        <span v-else class="logo" aria-hidden="true"><AppIcon name="home" :size="16" /></span>
        <span class="brand-text">{{ branding.company_name || 'OfficeHub' }}</span>
      </RouterLink>

      <button type="button" class="search-trigger" aria-haspopup="dialog" :aria-label="t('search.trigger')" @click="searchOpen = true">
        <AppIcon name="search" :size="18" />
        <span class="search-label">{{ t('search.trigger') }}</span>
        <span class="shortcut" aria-hidden="true"><kbd>{{ isMac ? '⌘' : 'Ctrl' }}</kbd><kbd>K</kbd></span>
      </button>

      <div class="header-actions">
        <div class="settings">
          <button
            ref="settingsButton"
            type="button"
            class="btn btn-ghost btn-icon header-btn"
            :aria-label="t('nav.settings')"
            :title="t('nav.settings')"
            aria-haspopup="menu"
            :aria-expanded="settingsOpen"
            aria-controls="settings-menu"
            @click="settingsOpen = !settingsOpen"
          >
            <AppIcon name="dots" />
          </button>
          <div v-if="settingsOpen" id="settings-menu" ref="settingsPanel" class="menu-panel" role="menu" :aria-label="t('nav.settings')">
            <button type="button" class="menu-item" role="menuitem" @click="toggleTheme(); settingsOpen = false">
              <AppIcon :name="theme === 'dark' ? 'sun' : 'moon'" :size="18" />
              {{ theme === 'dark' ? t('app.lightMode') : t('app.darkMode') }}
            </button>
            <RouterLink to="/profile" class="menu-item" role="menuitem">
              <AppIcon name="settings" :size="18" />{{ t('nav.profile') }}
            </RouterLink>
            <button v-if="showInstall" type="button" class="menu-item" role="menuitem" @click="settingsOpen = false; install()">
              <AppIcon name="download" :size="18" />{{ t('app.install') }}
            </button>
            <RouterLink v-if="publicConfig?.version" to="/whats-new" class="menu-item" role="menuitem">
              <AppIcon name="star" :size="18" />{{ t('nav.whatsNew', { version: publicConfig.version }) }}
            </RouterLink>
            <hr class="menu-sep" />
            <button type="button" class="menu-item" role="menuitem" @click="logout">
              <AppIcon name="logout" :size="18" />{{ t('app.signOut') }}
            </button>
          </div>
        </div>
        <StatusMenu />
      </div>
    </header>

    <!-- The app bar like Teams: everyday tools, pinned apps, "Apps" with everything else -->
    <nav class="rail" :aria-label="t('nav.main')">
      <ul class="rail-list">
        <li v-for="item in railItems" :key="item.to">
          <RouterLink :to="target(item.to)" :title="item.label" class="rail-link" :class="{ active: isActive(item.to) }" :aria-current="isActive(item.to) ? 'page' : undefined">
            <span class="rail-icon">
              <AppIcon :name="item.icon" :size="22" />
              <span v-if="item.count" class="rail-badge">{{ item.count > 99 ? '99+' : item.count }}<span class="visually-hidden"> {{ t('nav.countOpen') }}</span></span>
            </span>
            <span class="rail-label">{{ item.short ?? item.label }}</span>
          </RouterLink>
        </li>
      </ul>
      <ul v-if="pinnedItems.length" class="rail-list pinned" :aria-label="t('nav.pinned')">
        <li v-for="item in pinnedItems" :key="item.to">
          <RouterLink :to="target(item.to)" :title="item.label" class="rail-link" :class="{ active: isActive(item.to) }" :aria-current="isActive(item.to) ? 'page' : undefined">
            <span class="rail-icon">
              <AppIcon :name="item.icon" :size="22" />
              <span v-if="item.count" class="rail-badge">{{ item.count > 99 ? '99+' : item.count }}<span class="visually-hidden"> {{ t('nav.countOpen') }}</span></span>
            </span>
            <span class="rail-label">{{ item.short ?? item.label }}</span>
          </RouterLink>
        </li>
      </ul>
      <ul class="rail-list">
        <li class="apps">
          <button ref="appsButton" type="button" class="rail-link" :class="{ active: appsActive || appsOpen }" aria-haspopup="true" :aria-expanded="appsOpen" aria-controls="nav-apps" @click="appsOpen = !appsOpen">
            <span class="rail-icon">
              <AppIcon name="apps" :size="22" />
              <span v-if="appsCount" class="rail-badge">{{ appsCount > 99 ? '99+' : appsCount }}<span class="visually-hidden"> {{ t('nav.countOpen') }}</span></span>
            </span>
            <span class="rail-label">{{ t('nav.apps') }}</span>
          </button>
          <div v-if="appsOpen" id="nav-apps" ref="appsPanel" class="apps-panel">
            <p class="apps-title">{{ t('nav.apps') }}</p>
            <p class="apps-hint">{{ t('nav.pinHint') }}</p>
            <template v-for="group in appGroups" :key="group.key">
              <p v-if="group.label" class="nav-heading">{{ group.label }}</p>
              <ul class="nav-list">
                <li v-for="item in group.items" :key="item.to" class="app-row">
                  <RouterLink :to="target(item.to)" class="nav-link" :class="{ active: isActive(item.to) }" :aria-current="isActive(item.to) ? 'page' : undefined">
                    <AppIcon :name="item.icon" />
                    <span class="grow">{{ item.label }}</span>
                    <span v-if="item.count" class="count-badge">{{ item.count }}<span class="visually-hidden"> {{ t('nav.countOpen') }}</span></span>
                  </RouterLink>
                  <button
                    type="button"
                    class="btn btn-ghost btn-icon pin-btn"
                    :class="{ on: isPinned(item.to) }"
                    :aria-pressed="isPinned(item.to)"
                    :aria-label="t(isPinned(item.to) ? 'nav.unpin' : 'nav.pin', { name: item.label })"
                    :title="t(isPinned(item.to) ? 'nav.unpin' : 'nav.pin', { name: item.label })"
                    @click="togglePin(item.to)"
                  >
                    <AppIcon name="pin" :size="16" />
                  </button>
                </li>
              </ul>
            </template>
            <template v-if="quickLinks.length">
              <p class="nav-heading">{{ t('nav.moreTools') }}</p>
              <ul class="nav-list">
                <li v-for="link in quickLinks" :key="link.id">
                  <a :href="link.url" target="_blank" rel="noopener noreferrer" class="nav-link" :title="link.description || undefined">
                    <AppIcon :name="link.icon" />
                    <span class="grow">{{ link.title }}</span>
                    <AppIcon name="external" :size="16" :label="t('nav.opensNewTab')" />
                  </a>
                </li>
              </ul>
            </template>
          </div>
        </li>
      </ul>
      <ul class="rail-list rail-end">
        <li>
          <RouterLink to="/help" class="rail-link" :class="{ active: isActive('/help') }" :aria-current="isActive('/help') ? 'page' : undefined">
            <span class="rail-icon"><AppIcon name="lifebuoy" :size="22" /></span>
            <span class="rail-label">{{ t('nav.helpShort') }}</span>
          </RouterLink>
        </li>
      </ul>
    </nav>

    <!-- Phones: the whole menu slides in (from "More" or the menu button) -->
    <div v-if="menuOpen" class="drawer-backdrop" @click="menuOpen = false" />
    <aside
      id="sidebar"
      ref="drawer"
      class="sidebar"
      :class="{ open: menuOpen }"
      :aria-hidden="menuOpen ? undefined : 'true'"
      @keydown="menuOpen && onDrawerKeydown($event)"
    >
      <div class="sidebar-top">
        <RouterLink to="/" class="brand">
          <img v-if="branding.logo_version" :src="logoUrl()" alt="" class="logo-img" />
          <span v-else class="logo" aria-hidden="true"><AppIcon name="home" :size="16" /></span>
          <span class="brand-text">{{ branding.company_name || 'OfficeHub' }}</span>
        </RouterLink>
        <button type="button" class="btn btn-ghost btn-icon" :aria-label="t('app.closeMenu')" @click="menuOpen = false">
          <AppIcon name="close" />
        </button>
      </div>

      <nav class="nav" :aria-label="t('nav.main')">
        <template v-for="group in navGroups" :key="group.key">
          <p v-if="group.label && !group.collapsible" :id="`nav-${group.key}`" class="nav-heading">{{ group.label }}</p>
          <p v-else-if="group.label" :id="`nav-${group.key}`" class="nav-heading">
            <button type="button" class="fold" :aria-expanded="!isFolded(group)" :aria-controls="`navlist-${group.key}`" @click="toggleGroup(group.key)">
              {{ group.label }}<AppIcon :name="isFolded(group) ? 'chevronRight' : 'chevronDown'" :size="14" />
            </button>
          </p>
          <ul v-show="!isFolded(group)" :id="`navlist-${group.key}`" class="nav-list" :aria-labelledby="group.label ? `nav-${group.key}` : undefined">
            <li v-for="item in group.items" :key="item.to">
              <RouterLink :to="target(item.to)" class="nav-link" :class="{ active: isActive(item.to) }" :aria-current="isActive(item.to) ? 'page' : undefined">
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
            <span class="who-role">{{ roleNames(currentUser) }}</span>
          </span>
        </RouterLink>
        <div class="bottom-actions">
          <button type="button" class="btn btn-ghost nav-action" @click="toggleTheme">
            <AppIcon :name="theme === 'dark' ? 'sun' : 'moon'" />
            {{ theme === 'dark' ? t('app.lightMode') : t('app.darkMode') }}
          </button>
          <button v-if="showInstall" type="button" class="btn btn-ghost nav-action" @click="install">
            <AppIcon name="download" />
            {{ t('app.install') }}
          </button>
          <button type="button" class="btn btn-ghost nav-action" @click="logout">
            <AppIcon name="logout" />
            {{ t('app.signOut') }}
          </button>
          <RouterLink v-if="publicConfig?.version" to="/whats-new" class="version">
            {{ t('nav.whatsNew', { version: publicConfig.version }) }}
          </RouterLink>
        </div>
      </div>
    </aside>

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

    <!-- Phones in the browser: Teams' tab bar -->
    <nav v-if="showTabs && !route.meta.full" class="tabbar" :aria-label="t('nav.tabs')">
      <RouterLink v-for="item in tabItems" :key="item.to" :to="target(item.to)" class="tab" :class="{ active: isActive(item.to) }" :aria-current="isActive(item.to) ? 'page' : undefined">
        <span class="rail-icon">
          <AppIcon :name="item.icon" :size="22" />
          <span v-if="item.count" class="rail-badge">{{ item.count > 99 ? '99+' : item.count }}<span class="visually-hidden"> {{ t('nav.countOpen') }}</span></span>
        </span>
        <span class="rail-label">{{ item.short ?? item.label }}</span>
      </RouterLink>
      <button type="button" class="tab" :class="{ active: tabsMoreActive }" aria-controls="sidebar" :aria-expanded="menuOpen" @click="menuOpen = true">
        <span class="rail-icon"><AppIcon name="dots" :size="22" /></span>
        <span class="rail-label">{{ t('nav.more') }}</span>
      </button>
    </nav>

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

/* Like Teams: a bar across the top, the app bar on the left, the page in the rest */
.shell {
  display: grid;
  grid-template-columns: var(--rail-width) minmax(0, 1fr);
  grid-template-rows: var(--header-height) 1fr;
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
  font-size: var(--text-base, 1rem);
  letter-spacing: -0.01em;
  text-decoration: none;
}

.logo-img {
  width: 28px;
  height: 28px;
  object-fit: contain;
  border-radius: 7px;
}

.brand-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 200px;
}

.logo {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: var(--color-highlight);
  color: #fff;
}

/* ---------- Top bar ---------- */

.topbar {
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 560px) minmax(0, 1fr);
  align-items: center;
  gap: var(--space-3);
  height: var(--header-height);
  padding: 0 var(--space-3) 0 var(--space-4);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}

.menu-btn {
  display: none;
}

.search-trigger {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  min-height: 36px;
  padding: 0 var(--space-2) 0 var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
  color: var(--color-text-subtle);
  font: inherit;
  font-size: var(--text-sm);
  text-align: left;
  cursor: pointer;
  transition: border-color var(--t-fast) ease, background-color var(--t-fast) ease;
}

.search-trigger:hover {
  border-color: var(--color-border-strong);
  background: var(--color-surface);
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
  justify-content: flex-end;
  gap: var(--space-1);
}

.header-btn {
  color: var(--color-text-muted);
}

.header-btn:hover {
  color: var(--color-text);
}

.settings {
  position: relative;
}

.menu-panel {
  position: absolute;
  z-index: var(--z-dropdown, 50);
  top: calc(100% + 6px);
  right: 0;
  display: grid;
  width: 260px;
  padding: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface-raised);
  box-shadow: var(--shadow-overlay);
}

.menu-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-height: 40px;
  padding: 0 var(--space-3);
  border: 0;
  border-radius: var(--radius-sm);
  background: none;
  color: var(--color-text);
  font: inherit;
  font-size: var(--text-sm);
  text-align: left;
  text-decoration: none;
  cursor: pointer;
}

.menu-item:hover,
.menu-item:focus-visible {
  background: var(--color-surface-muted);
}

.menu-sep {
  width: 100%;
  margin: var(--space-1) 0;
  border: 0;
  border-top: 1px solid var(--color-border);
}

/* ---------- App bar (rail) ---------- */

.rail {
  position: fixed;
  top: var(--header-height);
  bottom: 0;
  left: 0;
  z-index: var(--z-drawer);
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: var(--rail-width);
  padding: var(--space-2) 4px;
  border-right: 1px solid var(--color-border);
  background: var(--color-surface-muted);
}

.rail-list {
  display: grid;
  gap: 2px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.rail-list.pinned {
  margin-top: var(--space-1);
  padding-top: var(--space-2);
  border-top: 1px solid var(--color-border);
}

.rail-end {
  margin-top: auto;
}

.apps {
  position: relative;
}

.rail-link,
.tab {
  position: relative;
  display: grid;
  justify-items: center;
  gap: 2px;
  width: 100%;
  padding: 7px 2px 6px;
  border: 0;
  border-radius: var(--radius-md);
  background: none;
  color: var(--color-text-muted);
  font: inherit;
  font-size: 0.68rem;
  font-weight: 500;
  line-height: 1.2;
  text-align: center;
  text-decoration: none;
  cursor: pointer;
  transition: background-color var(--t-fast) ease, color var(--t-fast) ease;
}

.rail-link:hover {
  background: var(--color-surface);
  color: var(--color-text);
}

.rail-link.active,
.tab.active {
  color: var(--color-primary-text);
  font-weight: 700;
}

.rail-link.active {
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}

/* Active marker: a short bar on the left edge, like Teams */
.rail-link.active::before {
  content: '';
  position: absolute;
  left: -4px;
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
  display: -webkit-box;
  max-width: 100%;
  overflow: hidden;
  overflow-wrap: anywhere;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.apps-panel {
  position: fixed;
  z-index: calc(var(--z-drawer) + 1);
  top: calc(var(--header-height) + var(--space-2));
  left: calc(var(--rail-width) + var(--space-2));
  width: 300px;
  max-height: calc(100vh - var(--header-height) - var(--space-4));
  padding: var(--space-3);
  overflow-y: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface-raised);
  box-shadow: var(--shadow-overlay);
}

.apps-title {
  margin: 0;
  font-family: var(--font-heading);
  font-weight: 600;
}

.apps-hint {
  margin: 2px 0 var(--space-2);
  color: var(--color-text-muted);
  font-size: var(--text-xs);
}

.app-row {
  display: flex;
  align-items: center;
  gap: 2px;
}

.app-row .nav-link {
  flex: 1;
  min-width: 0;
}

.pin-btn {
  flex: none;
  color: var(--color-text-subtle);
  opacity: 0.55;
}

.app-row:hover .pin-btn,
.pin-btn:focus-visible,
.pin-btn.on {
  opacity: 1;
}

.pin-btn.on {
  color: var(--color-primary-text);
}

/* ---------- Lists (Apps flyout and phone menu) ---------- */

.nav-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 2px;
}

.nav-heading {
  margin: var(--space-4) var(--space-3) var(--space-2);
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
  min-height: 40px;
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

/* ---------- Phone menu (drawer) ---------- */

.sidebar {
  display: none;
}

.drawer-backdrop {
  display: none;
}

.sidebar-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-2) var(--space-3);
}

.nav {
  flex: 1;
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

.tabbar {
  display: none;
}

/* ---------- Page ---------- */

.content {
  view-transition-name: page;
  grid-column: 2;
  min-width: 0;
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

@media (max-width: 899px) {
  .shell {
    grid-template-columns: minmax(0, 1fr);
  }

  .rail {
    display: none;
  }

  .content {
    grid-column: 1;
  }

  .topbar {
    display: flex;
    gap: var(--space-2);
    padding: 0 var(--space-2);
  }

  .menu-btn {
    display: inline-flex;
  }

  .search-trigger {
    flex: 0 0 var(--touch);
    justify-content: center;
    width: var(--touch);
    min-height: var(--touch);
    padding: 0;
    margin-left: auto;
    border-color: transparent;
    background: transparent;
    color: var(--color-text-muted);
  }

  .search-label,
  .shortcut {
    display: none;
  }

  .sidebar {
    position: fixed;
    inset: 0 auto 0 0;
    z-index: var(--z-drawer);
    display: flex;
    flex-direction: column;
    width: min(86vw, 320px);
    padding: var(--space-3) var(--space-3) var(--space-4);
    overflow-y: auto;
    background: var(--color-surface);
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

  /* Teams on the phone: the main tools at the bottom, "More" opens the whole menu */
  .with-tabs {
    --bottom-bar: 60px;
  }

  .with-tabs .content {
    padding-bottom: calc(var(--space-7) + var(--bottom-bar));
  }

  .with-tabs .content.full {
    padding-bottom: 0;
  }

  .tabbar {
    position: fixed;
    inset: auto 0 0 0;
    z-index: var(--z-sticky);
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    height: calc(var(--bottom-bar) + env(safe-area-inset-bottom, 0px));
    padding: 4px 4px env(safe-area-inset-bottom, 0px);
    border-top: 1px solid var(--color-border);
    background: var(--color-surface);
  }

  .tab {
    align-content: center;
    min-height: var(--touch);
    font-size: 0.72rem;
  }
}
</style>
