<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import EmptyState from '@/components/EmptyState.vue'
import FormField from '@/components/FormField.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import SectionContact from '@/components/SectionContact.vue'
import { api } from '@/lib/api'
import { errorText, formatDate, formatDateLong, t } from '@/lib/i18n'
import { showToast } from '@/lib/toast'
import { todayIso } from '@/lib/workdays'
import type { Booking, Room } from '@/lib/types'

const DAY_START = 7 * 60
const DAY_END = 20 * 60

/** Quarter-hour options between 07:00 and 20:00. */
const TIMES = Array.from({ length: (DAY_END - DAY_START) / 15 + 1 }, (_, i) => {
  const minutes = DAY_START + i * 15
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`
})

const day = ref(todayIso())
const rooms = ref<Room[]>([])
const bookings = ref<Booking[]>([])
const mine = ref<Booking[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

const bookingOpen = ref(false)
const form = reactive({ room_id: 0, start_time: '09:00', end_time: '10:00', title: '' })
const errors = reactive<Record<string, string>>({})
const saving = ref(false)
const cancelTarget = ref<Booking | null>(null)

const isToday = computed(() => day.value === todayIso())
const bookingsByRoom = computed(() => {
  const map = new Map<number, Booking[]>()
  for (const booking of bookings.value) map.set(booking.room_id, [...(map.get(booking.room_id) ?? []), booking])
  return map
})
const endOptions = computed(() => TIMES.filter((time) => time > form.start_time))

function minutes(time: string): number {
  const [h, m] = time.split(':').map(Number)
  return h * 60 + m
}

/** Position of a booking on the 07:00–20:00 bar, in percent. */
function barStyle(booking: Booking) {
  const total = DAY_END - DAY_START
  const left = ((minutes(booking.start_time) - DAY_START) / total) * 100
  const width = ((minutes(booking.end_time) - minutes(booking.start_time)) / total) * 100
  return { left: `${left}%`, width: `${width}%` }
}

function shiftDay(delta: number) {
  const date = new Date(`${day.value}T00:00:00`)
  date.setDate(date.getDate() + delta)
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
  day.value = local.toISOString().slice(0, 10)
}

async function load() {
  loading.value = rooms.value.length === 0
  error.value = null
  try {
    const [r, b, m] = await Promise.all([
      api.get<Room[]>('/api/rooms'),
      api.get<Booking[]>(`/api/rooms/bookings?day=${day.value}`),
      api.get<Booking[]>('/api/rooms/bookings/mine'),
    ])
    rooms.value = r
    bookings.value = b
    mine.value = m
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

function openBooking(room: Room) {
  Object.assign(form, { room_id: room.id, start_time: '09:00', end_time: '10:00', title: '' })
  for (const key of Object.keys(errors)) delete errors[key]
  bookingOpen.value = true
}

async function book() {
  for (const key of Object.keys(errors)) delete errors[key]
  if (!form.title.trim()) errors.title = t('validation.title_required')
  if (form.end_time <= form.start_time) errors.end_time = t('validation.end_before_start_time')
  if (Object.keys(errors).length) return
  saving.value = true
  try {
    await api.post('/api/rooms/bookings', { ...form, title: form.title.trim(), day: day.value })
    bookingOpen.value = false
    showToast(t('rooms.booked'))
    await load()
  } catch (e) {
    const field = (e as { field?: string }).field
    errors[field && field in form ? field : 'start_time'] = errorText(e)
  } finally {
    saving.value = false
  }
}

async function cancelBooking() {
  if (!cancelTarget.value) return
  saving.value = true
  try {
    await api.delete(`/api/rooms/bookings/${cancelTarget.value.id}`)
    cancelTarget.value = null
    showToast(t('rooms.cancelled'))
    await load()
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    saving.value = false
  }
}

watch(day, load)
watch(
  () => form.start_time,
  (start) => {
    if (form.end_time <= start) form.end_time = endOptions.value[3] ?? endOptions.value[0] ?? start
  },
)
onMounted(load)

const bookingRoom = computed(() => rooms.value.find((r) => r.id === form.room_id))
</script>

<template>
  <div class="page">
    <PageHeader :title="t('rooms.title')" :subtitle="t('rooms.subtitle')" />

    <div class="day-bar" role="group" :aria-label="t('rooms.day')">
      <button type="button" class="btn btn-secondary btn-icon" :aria-label="t('rooms.previousDay')" :disabled="isToday" @click="shiftDay(-1)">
        <AppIcon name="chevronLeft" />
      </button>
      <label for="room-day" class="visually-hidden">{{ t('rooms.day') }}</label>
      <input id="room-day" v-model="day" type="date" class="input day-input" :min="todayIso()" />
      <button type="button" class="btn btn-secondary btn-icon" :aria-label="t('rooms.nextDay')" @click="shiftDay(1)">
        <AppIcon name="chevronRight" />
      </button>
      <button v-if="!isToday" type="button" class="btn btn-ghost" @click="day = todayIso()">{{ t('rooms.today') }}</button>
      <p class="day-label">{{ formatDateLong(day) }}</p>
    </div>

    <LoadState :loading="loading" :error="error" @retry="load">
      <section v-if="rooms.length" class="room-list" :aria-label="t('rooms.title')">
        <article v-for="room in rooms" :key="room.id" class="card room" :aria-labelledby="`room-${room.id}`">
          <div class="row-between">
            <div>
              <h2 :id="`room-${room.id}`">{{ room.name }}</h2>
              <p class="muted small">{{ t('rooms.seats', { count: room.seats }) }}<template v-if="room.equipment"> · {{ room.equipment }}</template></p>
            </div>
            <button type="button" class="btn btn-primary" :aria-label="t('rooms.bookRoom', { room: room.name })" @click="openBooking(room)">
              <AppIcon name="plus" />{{ t('rooms.book') }}
            </button>
          </div>
          <div class="timeline" aria-hidden="true" :title="t('rooms.timeline')">
            <span v-for="booking in bookingsByRoom.get(room.id) ?? []" :key="booking.id" class="slot" :style="barStyle(booking)" />
            <span class="tick tick-7">07</span>
            <span class="tick tick-12">12</span>
            <span class="tick tick-17">17</span>
          </div>
          <ul v-if="bookingsByRoom.get(room.id)?.length" class="bookings">
            <li v-for="booking in bookingsByRoom.get(room.id)" :key="booking.id">
              <span class="time">{{ t('rooms.timeRange', { start: booking.start_time, end: booking.end_time }) }}</span>
              <span class="grow">{{ booking.title }} <span class="muted small">· {{ t('rooms.bookedBy', { name: booking.person_name }) }}</span></span>
              <button v-if="booking.can_cancel" type="button" class="btn btn-ghost danger-text" @click="cancelTarget = booking">{{ t('rooms.cancel') }}</button>
            </li>
          </ul>
          <p v-else class="muted small free"><AppIcon name="checkCircle" :size="16" />{{ t('rooms.free') }}</p>
        </article>
      </section>
      <section v-else class="card"><EmptyState icon="door" :message="t('rooms.noRooms')" /></section>

      <details class="disclosure" :open="mine.length > 0 || undefined">
        <summary>{{ t('rooms.mine') }} ({{ mine.length }})</summary>
        <div class="disclosure-body">
          <ul v-if="mine.length" class="bookings">
            <li v-for="booking in mine" :key="booking.id">
              <span class="time">{{ formatDate(booking.day) }} · {{ t('rooms.timeRange', { start: booking.start_time, end: booking.end_time }) }}</span>
              <span class="grow">{{ booking.title }} <span class="muted small">· {{ booking.room_name }}</span></span>
              <button type="button" class="btn btn-ghost danger-text" @click="cancelTarget = booking">{{ t('rooms.cancel') }}</button>
            </li>
          </ul>
          <p v-else class="muted">{{ t('rooms.noMine') }}</p>
        </div>
      </details>
    </LoadState>

    <SectionContact section="rooms" />

    <BaseModal
      :open="bookingOpen"
      :title="bookingRoom ? t('rooms.bookRoom', { room: bookingRoom.name }) : t('rooms.bookTitle')"
      :description="formatDateLong(day)"
      :confirm-label="t('rooms.book')"
      :busy="saving"
      @close="bookingOpen = false"
      @confirm="book"
    >
      <form class="stack" novalidate @submit.prevent="book">
        <FormField id="b-title" :label="t('rooms.purpose')" :error="errors.title">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.title" class="input" maxlength="120" :placeholder="t('rooms.purposePlaceholder')" /></template>
        </FormField>
        <div class="grid-2">
          <FormField id="b-start_time" :label="t('rooms.start')" :error="errors.start_time">
            <template #default="{ attrs }">
              <select v-bind="attrs" v-model="form.start_time" class="select">
                <option v-for="time in TIMES.slice(0, -1)" :key="time" :value="time">{{ time }}</option>
              </select>
            </template>
          </FormField>
          <FormField id="b-end_time" :label="t('rooms.end')" :error="errors.end_time">
            <template #default="{ attrs }">
              <select v-bind="attrs" v-model="form.end_time" class="select">
                <option v-for="time in endOptions" :key="time" :value="time">{{ time }}</option>
              </select>
            </template>
          </FormField>
        </div>
      </form>
    </BaseModal>

    <BaseModal
      :open="cancelTarget !== null"
      :title="t('rooms.cancelTitle')"
      :description="cancelTarget ? t('rooms.cancelText', { title: cancelTarget.title, date: formatDate(cancelTarget.day), start: cancelTarget.start_time, end: cancelTarget.end_time }) : ''"
      :confirm-label="t('rooms.cancelConfirm')"
      :cancel-label="t('rooms.keep')"
      tone="danger"
      :busy="saving"
      @close="cancelTarget = null"
      @confirm="cancelBooking"
    />
  </div>
</template>

<style scoped>
.day-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}

.day-input {
  width: auto;
}

.day-label {
  margin-left: var(--space-2);
  font-weight: 600;
}

.room-list {
  display: grid;
  gap: var(--space-3);
}

.room {
  display: grid;
  gap: var(--space-3);
}

.timeline {
  position: relative;
  height: 28px;
  border-radius: var(--radius-sm);
  background: var(--color-success-soft);
  border: 1px solid var(--color-border);
  overflow: hidden;
}

.slot {
  position: absolute;
  top: 0;
  bottom: 0;
  background: var(--color-primary);
  opacity: 0.85;
  border-left: 1px solid var(--color-surface);
}

.tick {
  position: absolute;
  bottom: 2px;
  padding-left: 4px;
  font-size: 11px;
  color: var(--color-text-muted);
  pointer-events: none;
}

.tick-7 {
  left: 0;
}

.tick-12 {
  left: 38.46%;
}

.tick-17 {
  left: 76.92%;
}

.bookings {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
}

.bookings li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1) var(--space-3);
  min-height: var(--touch);
  border-top: 1px solid var(--color-border);
}

.bookings li:first-child {
  border-top: 0;
}

.time {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  min-width: 110px;
}

.grow {
  flex: 1;
}

.free {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.free .icon {
  color: var(--color-success);
}

.danger-text {
  color: var(--color-danger);
}

@media (max-width: 560px) {
  .bookings li {
    display: grid;
    gap: 2px;
    padding: var(--space-2) 0;
  }

  .bookings .btn {
    justify-self: start;
    padding-left: 0;
  }
}
</style>
