<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import { api } from '@/lib/api'
import { errorText, formatDate, t } from '@/lib/i18n'
import { percent } from '@/lib/planning'
import { hours, mondayOf } from '@/lib/time'
import type { ProjectReport } from '@/lib/types'

const props = defineProps<{ id: string }>()

const report = ref<ProjectReport | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const hovered = ref<number | null>(null)
const thisWeek = mondayOf(new Date().toISOString().slice(0, 10))

const project = computed(() => report.value?.project)
const remaining = computed(() =>
  project.value?.budget_minutes != null ? project.value.budget_minutes - (project.value.booked_minutes ?? 0) : null,
)
const maxWeek = computed(() => Math.max(60, ...(report.value?.weeks ?? []).flatMap((w) => [w.planned, w.booked])))
const labelEvery = computed(() => Math.max(1, Math.ceil((report.value?.weeks.length ?? 0) / 12)))

async function load() {
  loading.value = true
  error.value = null
  try {
    report.value = await api.get<ProjectReport>(`/api/planning/projects/${props.id}`)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

function height(minutes: number) {
  return { height: `${(minutes / maxWeek.value) * 100}%` }
}

function weekLabel(start: string) {
  return formatDate(start)
}

onMounted(load)
</script>

<template>
  <div class="page">
    <LoadState :loading="loading" :error="error" @retry="load">
      <template v-if="report && project">
        <PageHeader
          :title="project.name"
          :subtitle="project.client"
          :crumbs="[{ label: t('planning.title'), to: '/planning' }, { label: t('projects.title'), to: '/planning/projects' }]"
        />

        <div class="tiles">
          <div class="tile">
            <span class="t-label">{{ t('projects.budgetHours') }}</span>
            <span class="t-value">{{ project.budget_minutes != null ? `${hours(project.budget_minutes)} h` : '–' }}</span>
          </div>
          <div class="tile">
            <span class="t-label"><span class="key key-planned" aria-hidden="true" />{{ t('projects.planned') }}</span>
            <span class="t-value">{{ hours(project.planned_minutes ?? 0) }} h</span>
          </div>
          <div class="tile">
            <span class="t-label"><span class="key key-booked" aria-hidden="true" />{{ t('projects.booked') }}</span>
            <span class="t-value">{{ hours(project.booked_minutes ?? 0) }} h</span>
            <span v-if="project.budget_minutes" class="t-sub">{{ t('projects.ofBudget', { pct: percent(project.booked_minutes ?? 0, project.budget_minutes) }) }}</span>
          </div>
          <div class="tile">
            <span class="t-label">{{ t('projects.remaining') }}</span>
            <span class="t-value" :class="{ warn: remaining !== null && remaining < 0 }">{{ remaining !== null ? `${hours(remaining)} h` : '–' }}</span>
            <span v-if="remaining !== null && remaining < 0" class="t-sub warn">{{ t('projects.overBudget') }}</span>
          </div>
        </div>

        <section class="card stack">
          <div class="row-between">
            <h2 class="h3">{{ t('projects.perWeek') }}</h2>
            <div class="legend small">
              <span><span class="key key-planned" aria-hidden="true" />{{ t('projects.planned') }}</span>
              <span><span class="key key-booked" aria-hidden="true" />{{ t('projects.booked') }}</span>
            </div>
          </div>
          <p v-if="!report.weeks.length" class="muted">{{ t('projects.noData') }}</p>
          <div v-else class="chart" role="img" :aria-label="t('projects.chartLabel')">
            <div class="y-max small muted" aria-hidden="true">{{ hours(maxWeek) }} h</div>
            <div class="plot">
              <div
                v-for="(w, i) in report.weeks"
                :key="w.start"
                class="week"
                :class="{ current: w.start === thisWeek, dim: hovered !== null && hovered !== i }"
                @pointerenter="hovered = i"
                @pointerleave="hovered = null"
              >
                <div class="bars">
                  <span class="b b-planned" :style="height(w.planned)" />
                  <span class="b b-booked" :style="height(w.booked)" />
                </div>
                <span class="x small muted">{{ i % labelEvery === 0 ? weekLabel(w.start) : '' }}</span>
                <div v-if="hovered === i" class="tip" role="presentation">
                  <strong>{{ t('projects.weekOf', { date: formatDate(w.start) }) }}</strong>
                  <span><span class="key key-planned" />{{ t('projects.planned') }}: {{ hours(w.planned) }} h</span>
                  <span><span class="key key-booked" />{{ t('projects.booked') }}: {{ hours(w.booked) }} h</span>
                </div>
              </div>
            </div>
          </div>
          <details v-if="report.weeks.length" class="disclosure">
            <summary>{{ t('projects.showTable') }}</summary>
            <div class="disclosure-body table-wrap">
              <table class="table">
                <thead>
                  <tr>
                    <th scope="col">{{ t('projects.week') }}</th>
                    <th scope="col" class="num">{{ t('projects.planned') }}</th>
                    <th scope="col" class="num">{{ t('projects.booked') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="w in report.weeks" :key="w.start">
                    <td>{{ t('projects.weekOf', { date: formatDate(w.start) }) }}</td>
                    <td class="num">{{ hours(w.planned) }} h</td>
                    <td class="num">{{ hours(w.booked) }} h</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </details>
        </section>

        <section class="card card-flush">
          <h2 class="h3 section-title">{{ t('projects.team') }}</h2>
          <div v-if="report.rows.length" class="table-wrap">
            <table class="table">
              <thead>
                <tr>
                  <th scope="col">{{ t('planning.person') }}</th>
                  <th scope="col" class="num">{{ t('projects.planned') }}</th>
                  <th scope="col" class="num">{{ t('projects.booked') }}</th>
                  <th scope="col" class="num">{{ t('projects.difference') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in report.rows" :key="r.person.id">
                  <td>
                    <span class="person">
                      <UserAvatar :id="r.person.id" :name="r.person.full_name" :photo-version="r.person.photo_version" :size="26" />
                      {{ r.person.full_name }}
                    </span>
                  </td>
                  <td class="num">{{ hours(r.planned) }} h</td>
                  <td class="num">{{ hours(r.booked) }} h</td>
                  <td class="num">{{ r.booked - r.planned > 0 ? '+' : '' }}{{ hours(r.booked - r.planned) }} h</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="muted section-title">{{ t('projects.noData') }}</p>
        </section>
      </template>
    </LoadState>
  </div>
</template>

<style scoped>
.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: var(--space-3);
}

.tile {
  display: grid;
  gap: 2px;
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: var(--shadow-card);
}

.t-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.t-value {
  font-family: var(--font-heading);
  font-size: var(--text-xl);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.t-sub {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.warn {
  color: var(--color-warning);
}

.legend {
  display: flex;
  gap: var(--space-4);
  color: var(--color-text-muted);
}

.legend > span,
.tip > span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.key {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
}

.key-planned {
  background: var(--chart-planned);
}

.key-booked {
  background: var(--chart-booked);
}

.chart {
  position: relative;
  padding-top: var(--space-4);
}

.y-max {
  position: absolute;
  top: 0;
  left: 0;
}

.plot {
  display: flex;
  align-items: stretch;
  gap: 2px;
  height: 224px;
  padding-top: var(--space-2);
  border-top: 1px dashed var(--color-border);
  overflow-x: auto;
}

.week {
  position: relative;
  display: grid;
  grid-template-rows: 1fr 24px;
  flex: 1;
  min-width: 22px;
  padding: 0 2px;
  border-radius: 4px;
  transition: opacity 150ms ease-out;
}

.week.current {
  background: var(--color-primary-soft);
}

.week.dim {
  opacity: 0.45;
}

.bars {
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 2px;
  height: 100%;
  border-bottom: 1px solid var(--color-border-strong);
}

.b {
  width: min(14px, 40%);
  min-height: 0;
  border-radius: 4px 4px 0 0;
}

.b-planned {
  background: var(--chart-planned);
}

.b-booked {
  background: var(--chart-booked);
}

.x {
  padding-top: 4px;
  white-space: nowrap;
  font-size: 0.7rem;
  overflow: visible;
}

.tip {
  position: absolute;
  bottom: calc(100% - 40px);
  left: 50%;
  z-index: 5;
  display: grid;
  gap: 2px;
  min-width: 170px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-raised);
  box-shadow: var(--shadow-hover);
  font-size: var(--text-sm);
  transform: translateX(-50%);
  pointer-events: none;
}

.section-title {
  padding: var(--space-4) var(--space-5) var(--space-2);
}

.person {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}

@media (prefers-reduced-motion: reduce) {
  .week {
    transition: none;
  }
}
</style>
