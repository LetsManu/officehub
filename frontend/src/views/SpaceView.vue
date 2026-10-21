<script setup lang="ts">
/** Layout of one space: header, tabs and the active tab below (files, board, chat, wiki …). */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import LoadState from '@/components/LoadState.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import { api } from '@/lib/api'
import { errorText, t } from '@/lib/i18n'
import { publicConfig } from '@/lib/session'
import { provideSpace } from '@/lib/spaceContext'
import type { Meeting, SpaceDetail } from '@/lib/types'

const props = defineProps<{ id: string }>()
const route = useRoute()
const space = ref<SpaceDetail | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

const base = computed(() => `/spaces/${props.id}`)
const tabs = computed(() => [
  { to: base.value, label: t('spaces.tabs.overview'), icon: 'dashboard', exact: true },
  { to: `${base.value}/files`, label: t('spaces.tabs.files'), icon: 'folder' },
  { to: `${base.value}/board`, label: t('spaces.tabs.board'), icon: 'kanban' },
  { to: `${base.value}/chat`, label: t('spaces.tabs.chat'), icon: 'chat', count: space.value?.unread },
  { to: `${base.value}/wiki`, label: t('spaces.tabs.wiki'), icon: 'book' },
  { to: `${base.value}/members`, label: t('spaces.tabs.members'), icon: 'users' },
])

function isActive(tab: { to: string; exact?: boolean }) {
  return tab.exact ? route.path === tab.to : route.path.startsWith(tab.to)
}

async function reload() {
  try {
    space.value = await api.get<SpaceDetail>(`/api/spaces/${props.id}`)
    error.value = null
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

/** The space's standing meeting room and who is in it right now. */
const room = ref<Meeting | null>(null)
let roomTimer: number | undefined

async function loadRoom() {
  window.clearTimeout(roomTimer)
  if (!publicConfig.value?.meetings_enabled) return
  if (document.visibilityState === 'visible') {
    try {
      room.value = await api.get<Meeting>(`/api/spaces/${props.id}/meeting`)
    } catch {
      room.value = null // not a member
      return
    }
  }
  roomTimer = window.setTimeout(loadRoom, 20_000)
}
onBeforeUnmount(() => window.clearTimeout(roomTimer))

provideSpace({ space, reload })
watch(() => props.id, () => {
  loading.value = true
  space.value = null
  room.value = null
  reload()
  loadRoom()
}, { immediate: true })
</script>

<template>
  <div class="page space-page">
    <LoadState :loading="loading" :error="error" @retry="reload">
      <template v-if="space">
        <header class="space-head" :class="`pc-${space.color}`">
          <nav class="crumbs" :aria-label="t('app.breadcrumbs')">
            <RouterLink to="/spaces">{{ t('spaces.title') }}</RouterLink>
            <AppIcon name="chevronRight" :size="14" />
          </nav>
          <div class="title-row">
            <span class="badge" aria-hidden="true">{{ space.name.slice(0, 1).toUpperCase() }}</span>
            <div class="titles">
              <h1>{{ space.name }}</h1>
              <p v-if="space.description" class="muted">{{ space.description }}</p>
            </div>
            <div class="people" :aria-label="t('spaces.members', { n: space.member_count })">
              <UserAvatar v-for="m in space.members.slice(0, 5)" :id="m.person.id" :key="m.person.id" :name="m.person.full_name" :photo-version="m.person.photo_version" :size="32" />
              <span v-if="space.members.length > 5" class="more">+{{ space.members.length - 5 }}</span>
            </div>
            <RouterLink v-if="room && !space.archived" :to="`/meetings/${room.id}/room`" class="btn room-btn" :class="room.live.length ? 'btn-primary' : 'btn-secondary'">
              <AppIcon name="video" :size="18" />
              <span>{{ room.live.length ? t('spaces.roomLive', { n: room.live.length }) : t('spaces.room') }}</span>
            </RouterLink>
          </div>
          <p v-if="space.archived" class="notice notice-warning small">{{ t('spaces.archivedHint') }}</p>
          <nav class="tabs" :aria-label="space.name">
            <RouterLink v-for="tab in tabs" :key="tab.to" :to="tab.to" class="tab" :class="{ active: isActive(tab) }" :aria-current="isActive(tab) ? 'page' : undefined">
              <AppIcon :name="tab.icon" :size="18" />
              <span>{{ tab.label }}</span>
              <span v-if="tab.count" class="count">{{ tab.count }}</span>
            </RouterLink>
          </nav>
        </header>
        <RouterView :key="route.path.startsWith(`${base}/wiki`) ? 'wiki' : route.path" />
      </template>
    </LoadState>
  </div>
</template>

<style scoped>
.space-page {
  max-width: none;
}

.space-head {
  display: grid;
  gap: var(--space-3);
}

.crumbs {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-sm);
}

.crumbs a {
  color: var(--color-text-muted);
}

.title-row {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.badge {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 48px;
  height: 48px;
  border-radius: var(--radius-md);
  background: var(--pc);
  color: #fff;
  font-family: var(--font-heading);
  font-size: var(--text-xl);
  font-weight: 700;
}

.titles {
  flex: 1;
  min-width: 0;
}

.people {
  display: flex;
  align-items: center;
}

.people > :deep(*) + :deep(*) {
  margin-left: -8px;
}

.people :deep(.avatar) {
  box-shadow: 0 0 0 2px var(--color-bg);
}

.more {
  display: grid;
  place-items: center;
  min-width: 32px;
  height: 32px;
  padding: 0 6px;
  border-radius: 99px;
  background: var(--color-neutral-soft);
  font-size: 0.75rem;
  font-weight: 700;
  box-shadow: 0 0 0 2px var(--color-bg);
}

.tabs {
  display: flex;
  gap: var(--space-1);
  border-bottom: 1px solid var(--color-border);
  overflow-x: auto;
  scrollbar-width: none;
}

.tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 44px;
  padding: 0 var(--space-3);
  border-bottom: 3px solid transparent;
  color: var(--color-text-muted);
  font-weight: 600;
  white-space: nowrap;
  text-decoration: none;
}

.tab:hover {
  color: var(--color-text);
}

.tab.active {
  border-bottom-color: var(--pc);
  color: var(--color-text);
}

.count {
  display: grid;
  place-items: center;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 99px;
  background: var(--color-badge);
  color: var(--color-on-badge);
  font-size: 0.72rem;
  font-weight: 700;
}

@media (max-width: 720px) {
  .people {
    display: none;
  }

  .title-row {
    flex-wrap: wrap;
  }
}

.room-btn {
  flex: none;
}
</style>
