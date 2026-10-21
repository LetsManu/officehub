<script setup lang="ts">
/**
 * Breakout rooms in the meeting panel. People leading the meeting choose how many rooms, who goes where and for how
 * long, then open them; everyone else sees which room is theirs. Closing calls everyone back.
 */
import { computed, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { t } from '@/lib/i18n'
import { spread, type BreakoutState } from '@/lib/breakouts'
import type { Tile } from '@/lib/meeting'

const props = defineProps<{ state: BreakoutState | null; tiles: Tile[]; inRoom: number | null; busy: boolean }>()
const emit = defineEmits<{
  save: [body: { rooms: string[]; assign: Record<string, number>; open: boolean; minutes: number | null }]
  visit: [room: number | null]
}>()

const count = ref(2)
const minutes = ref<number | null>(15)
const assign = ref<Record<string, number>>({})
const people = computed(() => props.tiles.filter((x) => x.who && !x.mod))
const names = computed(() => Array.from({ length: count.value }, (_, i) => props.state?.rooms[i] ?? t('meeting.breakouts.roomName', { n: i + 1 })))

// Start from what is saved (another person leading the meeting may have prepared it)
watch(() => props.state, (s) => {
  if (!s || s.open) return
  if (s.rooms.length) count.value = s.rooms.length
  if (s.assign) assign.value = { ...s.assign }
}, { immediate: true })

function shuffle() {
  assign.value = spread(people.value.map((p) => p.who), count.value)
}

function open() {
  const who = new Set(people.value.map((p) => p.who))
  const chosen = Object.fromEntries(Object.entries(assign.value).filter(([w, n]) => who.has(w) && n < count.value))
  emit('save', { rooms: names.value, assign: chosen, open: true, minutes: minutes.value })
}

function close() {
  emit('save', { rooms: props.state?.rooms.length ? props.state.rooms : names.value, assign: props.state?.assign ?? {}, open: false, minutes: null })
}

const membersOf = (n: number) => props.tiles.filter((x) => props.state?.assign?.[x.who] === n).map((x) => x.name)
</script>

<template>
  <div class="breakouts">
    <template v-if="!state">
      <p class="muted-light small">{{ t('app.loading') }}</p>
    </template>

    <!-- Everyone else: which room is mine -->
    <template v-else-if="!state.moderator">
      <p v-if="!state.open" class="muted-light small">{{ t('meeting.breakouts.none') }}</p>
      <p v-else-if="state.mine === null" class="muted-light small">{{ t('meeting.breakouts.notAssigned') }}</p>
      <p v-else>{{ t('meeting.breakouts.yours', { name: state.rooms[state.mine] }) }}</p>
    </template>

    <!-- People leading the meeting: open rooms -->
    <template v-else-if="!state.open">
      <p class="muted-light small">{{ t('meeting.breakouts.intro') }}</p>
      <div class="row">
        <label for="bo-count">{{ t('meeting.breakouts.count') }}</label>
        <select id="bo-count" v-model.number="count" class="select dark">
          <option v-for="n in 19" :key="n" :value="n + 1">{{ n + 1 }}</option>
        </select>
        <label for="bo-minutes">{{ t('meeting.breakouts.duration') }}</label>
        <select id="bo-minutes" v-model="minutes" class="select dark">
          <option :value="null">{{ t('meeting.breakouts.noLimit') }}</option>
          <option v-for="m in [5, 10, 15, 20, 30, 45, 60]" :key="m" :value="m">{{ t('meeting.breakouts.minutes', { n: m }) }}</option>
        </select>
      </div>
      <button type="button" class="btn btn-secondary" :disabled="!people.length" @click="shuffle"><AppIcon name="users" :size="16" />{{ t('meeting.breakouts.spread') }}</button>
      <ul class="assign">
        <li v-for="p in people" :key="p.who">
          <label :for="`bo-${p.who}`">{{ p.name }}</label>
          <select :id="`bo-${p.who}`" v-model.number="assign[p.who]" class="select dark">
            <option :value="undefined">{{ t('meeting.breakouts.stays') }}</option>
            <option v-for="(name, i) in names" :key="i" :value="i">{{ name }}</option>
          </select>
        </li>
        <li v-if="!people.length" class="muted-light small">{{ t('meeting.breakouts.nobody') }}</li>
      </ul>
      <button type="button" class="btn btn-primary" :disabled="busy || !Object.keys(assign).length" @click="open">{{ t('meeting.breakouts.open') }}</button>
    </template>

    <template v-else>
      <p class="muted-light small">{{ t('meeting.breakouts.running') }}</p>
      <ul class="rooms">
        <li v-for="(name, i) in state.rooms" :key="i">
          <span><strong>{{ name }}</strong><span class="muted-light small block">{{ membersOf(i).join(', ') || t('meeting.breakouts.empty') }}</span></span>
          <button v-if="inRoom !== i" type="button" class="btn btn-ghost light" @click="emit('visit', i)">{{ t('meeting.breakouts.visit') }}</button>
          <span v-else class="here small">{{ t('meeting.breakouts.here') }}</span>
        </li>
      </ul>
      <button v-if="inRoom !== null" type="button" class="btn btn-secondary" @click="emit('visit', null)">{{ t('meeting.breakouts.backToMain') }}</button>
      <button type="button" class="btn btn-danger" :disabled="busy" @click="close">{{ t('meeting.breakouts.close') }}</button>
    </template>
  </div>
</template>

<style scoped>
.breakouts {
  display: grid;
  align-content: start;
  gap: var(--space-3);
  min-height: 0;
  overflow-y: auto;
}

.row {
  display: grid;
  grid-template-columns: auto 1fr;
  align-items: center;
  gap: var(--space-2) var(--space-3);
  font-size: var(--text-sm);
}

.dark {
  background: var(--m-bg, #0f141c);
  border-color: var(--m-border, #2e384a);
  color: var(--m-text, #eef1f6);
}

.assign,
.rooms {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.assign li {
  display: grid;
  grid-template-columns: 1fr 1fr;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
}

.rooms li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--m-border, #2e384a);
}

.block {
  display: block;
}

.light {
  color: var(--m-text, #eef1f6);
}

.here {
  color: #86efac;
  font-weight: 600;
}
</style>
