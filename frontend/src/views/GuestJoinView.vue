<script setup lang="ts">
/** The page a guest from outside opens from an invitation link: enter a name, wait to be let in, join. */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import FormField from '@/components/FormField.vue'
import MeetingRoom from '@/components/MeetingRoom.vue'
import { api } from '@/lib/api'
import { branding } from '@/lib/branding'
import { errorText, formatDateTime, t } from '@/lib/i18n'
import type { JoinInfo } from '@/lib/meeting'

const props = defineProps<{ token: string }>()
const info = ref<{ title: string; organizer: string | null; starts_at: string | null } | null>(null)
const error = ref<string | null>(null)
const phase = ref<'name' | 'waiting' | 'denied' | 'room' | 'left'>('name')
const name = ref('')
const nameError = ref('')
const busy = ref(false)
const join = ref<JoinInfo | null>(null)
let secret = ''
let timer: number | undefined

const KEY = 'officehub-guest-name'

async function ask() {
  nameError.value = name.value.trim() ? '' : t('validation.name_required')
  if (nameError.value) return
  busy.value = true
  try {
    const r = await api.post<{ status: string; secret: string }>(`/api/guest/${props.token}/request`, { name: name.value.trim() })
    secret = r.secret
    try {
      localStorage.setItem(KEY, name.value.trim())
    } catch {
      /* private window */
    }
    phase.value = 'waiting'
    poll()
  } catch (e) {
    nameError.value = errorText(e)
  } finally {
    busy.value = false
  }
}

async function poll() {
  window.clearTimeout(timer)
  try {
    const s = await api.get<{ status: string; join: JoinInfo | null }>(`/api/guest/status/${secret}`)
    if (s.status === 'denied') {
      phase.value = 'denied'
      return
    }
    if (s.status === 'admitted' && s.join && phase.value === 'waiting') {
      join.value = s.join
      phase.value = 'room'
    }
  } catch {
    if (phase.value === 'waiting') {
      error.value = t('guest.gone')
      return
    }
  }
  if (phase.value === 'waiting' || phase.value === 'room') {
    // Quick while waiting; slower in the meeting, where it only says "still here"
    timer = window.setTimeout(poll, phase.value === 'waiting' ? 2500 : 10_000)
  }
}

onMounted(async () => {
  try {
    name.value = localStorage.getItem(KEY) ?? ''
  } catch {
    /* private window */
  }
  try {
    info.value = await api.get(`/api/guest/${props.token}`)
    document.title = `${info.value!.title} · ${branding.value.company_name || 'OfficeHub'}`
  } catch {
    error.value = t('guest.notFound')
  }
})
onBeforeUnmount(() => window.clearTimeout(timer))
</script>

<template>
  <main class="guest" :class="{ inroom: phase === 'room' }">
    <MeetingRoom v-if="phase === 'room' && join" :meeting-id="join.meeting_id" :title="join.title" :display-name="join.connection.display_name" :join="join" guest @left="phase = 'left'" />

    <section v-else class="card box">
      <p class="brand">{{ branding.company_name || 'OfficeHub' }}</p>
      <div v-if="error" class="center">
        <AppIcon name="alert" :size="32" />
        <p>{{ error }}</p>
      </div>
      <template v-else-if="info">
        <h1 class="h2">{{ info.title }}</h1>
        <p class="muted">
          <template v-if="info.organizer">{{ t('guest.invitedBy', { name: info.organizer }) }}</template>
          <template v-if="info.starts_at"> · {{ formatDateTime(info.starts_at) }}</template>
        </p>

        <form v-if="phase === 'name'" class="stack" novalidate @submit.prevent="ask">
          <FormField id="guest-name" :label="t('guest.yourName')" :hint="t('guest.nameHint')" :error="nameError">
            <template #default="{ attrs }"><input v-bind="attrs" v-model="name" class="input" maxlength="80" autocomplete="name" /></template>
          </FormField>
          <button type="submit" class="btn btn-primary" :disabled="busy"><AppIcon name="video" />{{ t('guest.ask') }}</button>
          <p class="muted small">{{ t('meeting.privacy') }}</p>
        </form>

        <div v-else-if="phase === 'waiting'" class="center" role="status">
          <span class="spinner" aria-hidden="true" />
          <p><strong>{{ t('guest.waiting') }}</strong></p>
          <p class="muted small">{{ t('guest.waitingHint') }}</p>
        </div>

        <div v-else-if="phase === 'denied'" class="center" role="status">
          <AppIcon name="lock" :size="32" />
          <p>{{ t('guest.denied') }}</p>
        </div>

        <div v-else class="center" role="status">
          <AppIcon name="checkCircle" :size="32" />
          <p>{{ t('guest.thanks') }}</p>
        </div>
      </template>
    </section>
  </main>
</template>

<style scoped>
.guest {
  display: grid;
  min-height: 100dvh;
  place-items: center;
  padding: var(--space-4);
  background: var(--color-bg);
}

.guest.inroom {
  height: 100dvh;
  padding: 0;
  place-items: stretch;
}

.box {
  display: grid;
  width: min(440px, 100%);
  gap: var(--space-3);
  padding: var(--space-6);
}

.brand {
  margin: 0;
  color: var(--color-primary);
  font-weight: 700;
}

.box h1 {
  margin: 0;
}

.center {
  display: grid;
  justify-items: center;
  gap: var(--space-2);
  padding: var(--space-4) 0;
  text-align: center;
}

.center p {
  margin: 0;
}

.spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--color-border);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .spinner {
    animation-duration: 3s;
  }
}
</style>
