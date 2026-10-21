<script setup lang="ts">
/** My picture at the top right: set my status like in Teams (and a short message), or open my profile. */
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import UserAvatar from './UserAvatar.vue'
import { errorText, t } from '@/lib/i18n'
import { changeMyPresence, myPresence, type ManualPresence } from '@/lib/presence'
import { currentUser } from '@/lib/session'
import { showToast } from '@/lib/toast'

const CHOICES: ManualPresence[] = ['auto', 'available', 'busy', 'dnd', 'away', 'offline']
const open = ref(false)
const root = ref<HTMLElement | null>(null)
const button = ref<HTMLButtonElement | null>(null)
const text = ref('')

watch(open, async (isOpen) => {
  if (!isOpen) return
  text.value = myPresence.value.text
  await nextTick()
  root.value?.querySelector<HTMLElement>('[role="menuitemradio"][aria-checked="true"]')?.focus()
})

async function choose(manual: ManualPresence) {
  try {
    await changeMyPresence(manual, text.value.trim(), currentUser.value?.id)
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

async function saveText() {
  if (text.value.trim() === myPresence.value.text) return
  await choose(myPresence.value.manual)
  showToast(t('presence.textSaved'))
}

function onDocumentClick(event: MouseEvent) {
  if (open.value && root.value && !root.value.contains(event.target as Node)) open.value = false
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && open.value) {
    open.value = false
    button.value?.focus()
  }
}

onMounted(() => document.addEventListener('click', onDocumentClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocumentClick))
</script>

<template>
  <div v-if="currentUser" ref="root" class="status-menu" @keydown="onKeydown">
    <button
      ref="button"
      type="button"
      class="avatar-btn"
      aria-haspopup="true"
      :aria-expanded="open"
      :aria-label="t('presence.menu', { name: currentUser.full_name, state: t(`presence.states.${myPresence.state}`) })"
      @click="open = !open"
    >
      <UserAvatar :id="currentUser.id" :name="currentUser.full_name" :photo-version="currentUser.photo_version" :size="34" status />
    </button>
    <div v-if="open" class="panel" role="menu" :aria-label="t('presence.title')">
      <div class="me">
        <UserAvatar :id="currentUser.id" :name="currentUser.full_name" :photo-version="currentUser.photo_version" :size="44" status />
        <div>
          <p class="name">{{ currentUser.full_name }}</p>
          <p class="muted small">{{ t(`presence.states.${myPresence.state}`) }}<template v-if="myPresence.manual === 'auto'"> · {{ t('presence.automatic') }}</template></p>
        </div>
      </div>
      <ul class="choices">
        <li v-for="c in CHOICES" :key="c">
          <button type="button" role="menuitemradio" :aria-checked="myPresence.manual === c" class="choice" @click="choose(c)">
            <span class="swatch" :class="`s-${c}`" aria-hidden="true" />
            <span class="grow">{{ t(`presence.choices.${c}`) }}</span>
            <AppIcon v-if="myPresence.manual === c" name="check" :size="16" />
          </button>
        </li>
      </ul>
      <form class="message" @submit.prevent="saveText">
        <label for="status-text" class="small muted">{{ t('presence.message') }}</label>
        <div class="row">
          <input id="status-text" v-model="text" class="input" maxlength="120" :placeholder="t('presence.messagePlaceholder')" autocomplete="off" />
          <button type="submit" class="btn btn-secondary">{{ t('app.save') }}</button>
        </div>
      </form>
      <RouterLink to="/profile" class="profile-link" role="menuitem" @click="open = false"><AppIcon name="user" :size="18" />{{ t('nav.profile') }}</RouterLink>
    </div>
  </div>
</template>

<style scoped>
.status-menu {
  position: relative;
}

.avatar-btn {
  display: grid;
  width: var(--touch);
  height: var(--touch);
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: none;
  cursor: pointer;
}

.panel {
  position: absolute;
  z-index: var(--z-dropdown, 50);
  top: calc(100% + 6px);
  right: 0;
  display: grid;
  gap: var(--space-2);
  width: 300px;
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface-raised);
  box-shadow: var(--shadow-overlay);
}

.me {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding-bottom: var(--space-2);
  border-bottom: 1px solid var(--color-border);
}

.me p {
  margin: 0;
}

.name {
  font-weight: 700;
}

.choices {
  display: grid;
  margin: 0;
  padding: 0;
  list-style: none;
}

.choice,
.profile-link {
  display: flex;
  width: 100%;
  align-items: center;
  gap: var(--space-3);
  min-height: 40px;
  padding: 0 var(--space-2);
  border: 0;
  border-radius: var(--radius-md);
  background: none;
  color: var(--color-text);
  font: inherit;
  font-size: var(--text-sm);
  text-align: left;
  text-decoration: none;
  cursor: pointer;
}

.choice:hover,
.profile-link:hover {
  background: var(--color-surface-muted);
}

.swatch {
  width: 12px;
  height: 12px;
  border-radius: 50%;
}

.s-auto {
  background: conic-gradient(#16a34a 0 50%, #f59e0b 50% 100%);
}

.s-available {
  background: #16a34a;
}

.s-busy {
  background: #dc2626;
}

.s-dnd {
  background: linear-gradient(#fff, #fff) center / 56% 22% no-repeat, #dc2626;
}

.s-away {
  background: #f59e0b;
}

.s-offline {
  box-shadow: inset 0 0 0 2px #9ca3af;
}

.message {
  display: grid;
  gap: 4px;
  padding-top: var(--space-2);
  border-top: 1px solid var(--color-border);
}

.message .row {
  display: flex;
  gap: var(--space-2);
}

.message .input {
  min-width: 0;
}

.profile-link {
  border-top: 1px solid var(--color-border);
  border-radius: 0;
  padding-top: var(--space-2);
}
</style>
