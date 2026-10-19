<script setup lang="ts">
/** A small poll under an announcement. Results appear after voting; the vote can be changed. */
import { computed, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import { api } from '@/lib/api'
import { errorText, t } from '@/lib/i18n'
import { showToast } from '@/lib/toast'
import type { Announcement } from '@/lib/types'

const props = defineProps<{ announcement: Announcement }>()
const emit = defineEmits<{ updated: [Announcement] }>()

const busy = ref(false)
const changing = ref(false)
const poll = computed(() => props.announcement.poll!)
const showResults = computed(() => poll.value.counts !== null && !changing.value)
const legendId = `poll-${props.announcement.id}`

function percent(index: number): number {
  const counts = poll.value.counts ?? []
  return poll.value.total ? Math.round(((counts[index] ?? 0) / poll.value.total) * 100) : 0
}

async function vote(option: number) {
  busy.value = true
  try {
    emit('updated', await api.post<Announcement>(`/api/announcements/${props.announcement.id}/vote`, { option }))
    changing.value = false
    showToast(t('poll.thanks'))
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="poll" :aria-labelledby="legendId">
    <p :id="legendId" class="poll-question"><AppIcon name="chart" :size="18" />{{ poll.question }}</p>

    <ul v-if="showResults" class="results">
      <li v-for="(option, i) in poll.options" :key="i" class="result" :class="{ mine: poll.my_vote === i }">
        <span class="result-bar" :style="{ width: `${percent(i)}%` }" aria-hidden="true" />
        <span class="result-text">
          <span>
            {{ option }}
            <span v-if="poll.my_vote === i" class="mine-tag"><AppIcon name="check" :size="14" />{{ t('poll.yourVote') }}</span>
          </span>
          <span class="result-number">{{ percent(i) }} %</span>
        </span>
      </li>
    </ul>
    <div v-else class="options" role="group" :aria-labelledby="legendId">
      <button v-for="(option, i) in poll.options" :key="i" type="button" class="btn btn-secondary option" :disabled="busy" @click="vote(i)">
        {{ option }}
      </button>
    </div>

    <div class="row-between poll-foot">
      <span class="muted small">{{ poll.total === 1 ? t('poll.votesOne') : t('poll.votes', { count: poll.total }) }}</span>
      <button v-if="showResults && poll.my_vote !== null" type="button" class="btn btn-ghost" @click="changing = true">{{ t('poll.change') }}</button>
      <button v-else-if="changing" type="button" class="btn btn-ghost" @click="changing = false">{{ t('app.cancel') }}</button>
    </div>
  </section>
</template>

<style scoped>
.poll {
  display: grid;
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
}

.poll-question {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-weight: 600;
}

.options {
  display: grid;
  gap: var(--space-2);
}

.option {
  justify-content: flex-start;
  white-space: normal;
  text-align: left;
}

.results {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-2);
}

.result {
  position: relative;
  min-height: var(--touch);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  overflow: hidden;
}

.result.mine {
  border-color: var(--color-primary);
}

.result-bar {
  position: absolute;
  inset: 0 auto 0 0;
  background: var(--color-primary-soft);
  transition: width var(--t-med) var(--ease);
}

.result-text {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  min-height: var(--touch);
  padding: var(--space-2) var(--space-3);
}

.mine-tag {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  margin-left: var(--space-2);
  color: var(--color-primary-text);
  font-size: var(--text-xs);
  font-weight: 600;
}

.result-number {
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.poll-foot .btn {
  min-height: 36px;
}
</style>
