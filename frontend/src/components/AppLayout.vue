<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from './AppIcon.vue'
import { currentUser, isAdmin, isApprover, publicConfig, signOut } from '@/lib/session'
import { quickLinks, resetPortal } from '@/lib/portal'
import { t } from '@/lib/i18n'
import { applyTheme, theme } from '@/lib/theme'
import { showToast } from '@/lib/toast'
import { trapTab } from '@/lib/focus'

interface NavItem {
  to: string
  label: string
  icon: string
}

const route = useRoute()
const router = useRouter()
const menuOpen = ref(false)
const drawer = ref<HTMLElement | null>(null)
const menuButton = ref<HTMLButtonElement | null>(null)

const mainItems = computed<NavItem[]>(() => [
  { to: '/', label: t('nav.dashboard'), icon: 'dashboard' },
  { to: '/requests', label: t('nav.requests'), icon: 'inbox' },
  { to: '/documents', label: t('nav.documents'), icon: 'file' },
  { to: '/announcements', label: t('nav.announcements'), icon: 'megaphone' },
  { to: '/people', label: t('nav.people'), icon: 'users' },
  { to: '/rooms', label: t('nav.rooms'), icon: 'door' },
  { to: '/visitors', label: t('nav.visitors'), icon: 'badge' },
  { to: '/reviews', label: t('nav.reviews'), icon: 'message' },
  { to: '/profile', label: t('nav.profile'), icon: 'user' },
])

const manageItems = computed<NavItem[]>(() => {
  const items: NavItem[] = []
  if (isApprover.value) {
    items.push({ to: '/approvals', label: t('nav.approvals'), icon: 'checkCircle' })
    items.push({ to: '/onboarding', label: t('nav.onboarding'), icon: 'clipboard' })
    items.push({ to: '/reports', label: t('nav.reports'), icon: 'chart' })
  }
  if (isAdmin.value) {
    items.push({ to: '/manage/documents', label: t('nav.manageDocuments'), icon: 'folder' })
    items.push({ to: '/manage/announcements', label: t('nav.manageAnnouncements'), icon: 'edit' })
  }
  if (isApprover.value) items.push({ to: '/admin', label: t('nav.administration'), icon: 'settings' })
  return items
})

function isActive(to: string): boolean {
  return to === '/' ? route.path === '/' : route.path === to || route.path.startsWith(`${to}/`)
}

const initials = computed(() => {
  const u = currentUser.value
  return u ? `${u.first_name[0] ?? ''}${u.last_name[0] ?? ''}`.toUpperCase() : ''
})

function toggleTheme() {
  applyTheme(theme.value === 'dark' ? 'light' : 'dark')
}

async function logout() {
  await signOut().catch(() => undefined)
  resetPortal()
  showToast(t('app.signedOutToast'), 'info')
  router.push('/login')
}

function onDrawerKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') menuOpen.value = false
  else if (drawer.value) trapTab(event, drawer.value)
}

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
  <div class="shell">
    <!-- Mobile top bar -->
    <header class="topbar">
      <RouterLink to="/" class="brand"><span class="logo" aria-hidden="true"><AppIcon name="home" :size="18" /></span>OfficeHub</RouterLink>
      <button
        ref="menuButton"
        type="button"
        class="btn btn-ghost btn-icon"
        :aria-label="t('app.openMenu')"
        aria-controls="sidebar"
        :aria-expanded="menuOpen"
        @click="menuOpen = true"
      >
        <AppIcon name="menu" :size="24" />
      </button>
    </header>

    <div v-if="menuOpen" class="drawer-backdrop" @click="menuOpen = false" />

    <aside
      id="sidebar"
      ref="drawer"
      class="sidebar"
      :class="{ open: menuOpen }"
      @keydown="menuOpen && onDrawerKeydown($event)"
    >
      <div class="sidebar-top">
        <RouterLink to="/" class="brand"><span class="logo" aria-hidden="true"><AppIcon name="home" :size="18" /></span>OfficeHub</RouterLink>
        <button v-if="menuOpen" type="button" class="btn btn-ghost btn-icon" :aria-label="t('app.closeMenu')" @click="menuOpen = false">
          <AppIcon name="close" />
        </button>
      </div>

      <nav class="nav" :aria-label="t('nav.main')">
        <ul class="nav-list">
          <li v-for="item in mainItems" :key="item.to">
            <RouterLink :to="item.to" class="nav-link" :class="{ active: isActive(item.to) }" :aria-current="isActive(item.to) ? 'page' : undefined">
              <AppIcon :name="item.icon" />
              {{ item.label }}
            </RouterLink>
          </li>
        </ul>
        <template v-if="manageItems.length">
          <p class="nav-heading">{{ t('nav.manage') }}</p>
          <ul class="nav-list">
            <li v-for="item in manageItems" :key="item.to">
              <RouterLink :to="item.to" class="nav-link" :class="{ active: isActive(item.to) }" :aria-current="isActive(item.to) ? 'page' : undefined">
                <AppIcon :name="item.icon" />
                {{ item.label }}
              </RouterLink>
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
          <span class="avatar" aria-hidden="true">{{ initials }}</span>
          <span class="who-text">
            <span class="who-name">{{ currentUser.full_name }}</span>
            <span class="who-role">{{ t(`roles.${currentUser.role}`) }}</span>
          </span>
        </RouterLink>
        <div class="bottom-actions">
          <button type="button" class="btn btn-ghost nav-action" @click="toggleTheme">
            <AppIcon :name="theme === 'dark' ? 'sun' : 'moon'" />
            {{ theme === 'dark' ? t('app.lightMode') : t('app.darkMode') }}
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

    <main id="main" class="content" tabindex="-1">
      <slot />
    </main>
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
  font-weight: 700;
  font-size: var(--text-lg);
  text-decoration: none;
}

.logo {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--color-primary);
  color: #fff;
}

.topbar {
  display: none;
}

.sidebar {
  position: fixed;
  inset: 0 auto 0 0;
  z-index: 50;
  display: flex;
  flex-direction: column;
  width: var(--sidebar-width);
  padding: var(--space-4) var(--space-3);
  border-right: 1px solid var(--color-border);
  background: var(--color-surface);
  overflow-y: auto;
}

.sidebar-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-2) var(--space-4);
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

.content {
  margin-left: var(--sidebar-width);
  padding: var(--space-6) var(--space-6) var(--space-7);
  max-width: calc(1080px + var(--sidebar-width));
}

.content:focus {
  outline: none;
}

.drawer-backdrop {
  display: none;
}

@media (max-width: 899px) {
  .topbar {
    position: sticky;
    top: 0;
    z-index: 40;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-2) var(--space-3) var(--space-2) var(--space-4);
    border-bottom: 1px solid var(--color-border);
    background: var(--color-surface);
  }

  .sidebar {
    width: min(86vw, 320px);
    transform: translateX(-100%);
    visibility: hidden;
    transition: transform 0.2s ease, visibility 0.2s;
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
    z-index: 45;
    background: var(--backdrop);
  }

  .content {
    margin-left: 0;
    padding: var(--space-5) var(--space-4) var(--space-7);
  }
}
</style>
