<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import HealthBadge from '@/components/HealthBadge.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api } from '@/lib/api'
import { errorText, formatDateTime, formatFileSize, locale, t } from '@/lib/i18n'
import { relayUrls, testRelay, type IceServer, type RelayKind, type RelayResult } from '@/lib/relayTest'

type Tone = 'ok' | 'warn' | 'bad' | 'off'
type State = 'ok' | 'warn' | 'bad' | 'unknown'

interface SystemInfo {
  version: string
  in_stack: boolean
  craft: { apps: string[]; running: boolean; set_up: boolean }
  onlyoffice: { running: boolean; set_up: boolean }
  jitsi: { running: boolean; set_up: boolean }
  relay: { own_servers: boolean; secret: boolean; port: number; host: string | null; ready: boolean }
  disk: { free: number | null; total: number | null; state: State }
  database_size: number | null
  backup: { available: boolean; enabled: boolean; at: string | null; ok: boolean | null; error: string | null; state: State }
  network: {
    public: { address: string | null; source: 'setting' | 'proxy' | 'portal' | 'noted' | null }
    office: string | null
    behind_proxy: boolean
    portal_url: string
    inside_office: boolean | null
  }
  notices: string[]
  ice_servers: IceServer[]
}

interface Row {
  key: string
  icon: string
  label: string
  text: string
  tone?: Tone
}

const info = ref<SystemInfo | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const testing = ref(false)
const results = ref<Record<RelayKind, RelayResult> | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    info.value = await api.get<SystemInfo>('/api/admin/system')
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

function gigabytes(bytes: number): string {
  const value = bytes / 1024 ** 3
  return `${new Intl.NumberFormat(locale.value, { maximumFractionDigits: value < 10 ? 1 : 0 }).format(value)} GB`
}

const stateTone = (state: State): Tone => (state === 'unknown' ? 'off' : state)
const toneLabel = (tone: Tone) => t(`system.states.${tone}`)

const rows = computed<Row[]>(() => {
  const s = info.value
  if (!s) return []
  const list: Row[] = []
  list.push(s.craft.running
    ? { key: 'craft', icon: 'file', label: t('system.craft'), text: t('system.craftOk'), tone: 'ok' }
    : { key: 'craft', icon: 'file', label: t('system.craft'), text: t('system.craftOff'), tone: s.in_stack ? 'warn' : 'off' })
  list.push({ key: 'onlyoffice', icon: 'edit', label: t('system.onlyoffice'),
    text: t(s.onlyoffice.running ? 'system.onlyofficeOk' : 'system.onlyofficeOff'), tone: s.onlyoffice.running ? 'ok' : 'off' })
  list.push({ key: 'jitsi', icon: 'video', label: t('system.jitsi'),
    text: t(s.jitsi.running ? 'system.jitsiOk' : 'system.jitsiOff'), tone: s.jitsi.running ? 'ok' : 'off' })
  const relay = s.relay
  list.push(relay.own_servers
    ? { key: 'relay', icon: 'globe', label: t('system.relay'), text: t('system.relayOwn'), tone: 'ok' }
    : relay.ready
      ? { key: 'relay', icon: 'globe', label: t('system.relay'), text: t('system.relayOk', { host: relay.host ?? '', port: relay.port }), tone: 'ok' }
      : { key: 'relay', icon: 'globe', label: t('system.relay'), text: t(relay.secret ? 'system.relayMissing' : 'system.relayOff'), tone: relay.secret ? 'warn' : 'off' })
  const disk = s.disk
  list.push({ key: 'disk', icon: 'archive', label: t('system.disk'),
    text: disk.free !== null && disk.total !== null
      ? t(disk.state === 'ok' ? 'system.diskText' : 'system.diskLow', { free: gigabytes(disk.free), total: gigabytes(disk.total) })
      : t('system.unknown'),
    tone: stateTone(disk.state) })
  list.push({ key: 'database', icon: 'box', label: t('system.database'),
    text: s.database_size !== null ? t('system.databaseText', { size: formatFileSize(s.database_size) }) : t('system.databaseOther') })
  const b = s.backup
  let backupText = t('system.backupOther')
  if (b.available) {
    if (b.ok === false) backupText = t('system.backupFailed', { when: formatDateTime(b.at), error: b.error ?? '' })
    else if (!b.enabled) backupText = t('system.backupOff')
    else if (!b.at) backupText = t('system.backupNone')
    else if (b.state === 'ok') backupText = t('system.backupOk', { when: formatDateTime(b.at) })
    else backupText = t('system.backupOld', { when: formatDateTime(b.at) })
  }
  list.push({ key: 'backup', icon: 'history', label: t('system.backup'), text: backupText, tone: stateTone(b.state) })
  return list
})

const sourceText = computed(() => {
  const s = info.value
  if (!s?.network.public.source) return t('system.noAddressHint')
  return t(`system.sources.${s.network.public.source}`, { url: s.network.portal_url })
})

const relayGroups = computed(() => relayUrls(info.value?.ice_servers ?? []))
const kinds: RelayKind[] = ['udp', 'tcp']
const allOk = computed(() => {
  const r = results.value
  return !!r && kinds.some((k) => r[k] === 'ok') && kinds.every((k) => r[k] === 'ok' || r[k] === 'none')
})
const anyFail = computed(() => !!results.value && kinds.some((k) => results.value?.[k] === 'fail'))
const resultTone = (result: RelayResult): Tone => (result === 'ok' ? 'ok' : result === 'fail' ? 'bad' : 'off')

async function runTest() {
  testing.value = true
  results.value = null
  try {
    // Fresh passwords for the relay (they last a few hours)
    info.value = await api.get<SystemInfo>('/api/admin/system')
    const groups = relayGroups.value
    const [udp, tcp] = await Promise.all([testRelay(groups.udp), testRelay(groups.tcp)])
    results.value = { udp, tcp }
  } catch (e) {
    error.value = errorText(e)
  } finally {
    testing.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader :title="t('system.title')" :subtitle="t('system.subtitle')" :crumbs="[{ label: t('nav.administration'), to: '/admin' }]" />

    <LoadState :loading="loading" :error="error" @retry="load">
      <template v-if="info">
        <section v-if="info.notices.length" class="stack" aria-labelledby="sys-notices">
          <h2 id="sys-notices">{{ t('system.noticesTitle') }}</h2>
          <div v-for="code in info.notices" :key="code" class="notice notice-warning" role="status">
            <AppIcon name="alert" />
            <div class="stack-sm">
              <p class="notice-title">{{ t(`system.notices.${code}.title`) }}</p>
              <p class="small">{{ t(`system.notices.${code}.text`) }}</p>
            </div>
          </div>
        </section>
        <div v-else class="notice notice-success" role="status">
          <AppIcon name="checkCircle" />
          <p>{{ t('system.allGood') }}</p>
        </div>

        <section class="card stack" aria-labelledby="sys-overview">
          <div class="row-between">
            <h2 id="sys-overview">{{ t('system.overview') }}</h2>
            <span class="muted small">{{ t('system.version', { version: info.version }) }}</span>
          </div>
          <ul class="list status-list">
            <li v-for="row in rows" :key="row.key" class="status-row">
              <span class="status-icon"><AppIcon :name="row.icon" :size="20" /></span>
              <span class="status-text">
                <span class="status-label">{{ row.label }}</span>
                <span class="muted small">{{ row.text }}</span>
              </span>
              <HealthBadge v-if="row.tone" :tone="row.tone" :label="toneLabel(row.tone)" />
            </li>
          </ul>
          <p class="muted small">
            <RouterLink to="/admin">{{ t('system.backupLink') }}</RouterLink>
          </p>
        </section>

        <section class="card stack" aria-labelledby="sys-meetings">
          <div>
            <h2 id="sys-meetings">{{ t('system.meetings') }}</h2>
            <p class="muted small">{{ t('system.meetingsIntro') }}</p>
          </div>
          <dl class="facts">
            <div>
              <dt>{{ t('system.publicAddress') }}</dt>
              <dd>
                <span class="value">{{ info.network.public.address ?? t('system.unknown') }}</span>
                <span class="muted small">{{ sourceText }}</span>
              </dd>
            </div>
            <div>
              <dt>{{ t('system.officeAddress') }}</dt>
              <dd><span class="value">{{ info.network.office ?? t('system.unknown') }}</span></dd>
            </div>
            <div>
              <dt>{{ t('system.proxy') }}</dt>
              <dd>
                <span class="value">{{ info.network.behind_proxy ? t('app.yes') : t('app.no') }}</span>
                <span v-if="info.network.behind_proxy" class="muted small">{{ t('system.proxyHint') }}</span>
              </dd>
            </div>
          </dl>

          <div class="stack test">
            <div>
              <h3>{{ t('system.test') }}</h3>
              <p class="muted small">{{ t('system.testIntro') }}</p>
            </div>
            <div v-if="info.network.inside_office" class="notice notice-info small" role="status">
              <AppIcon name="info" />
              <p>{{ t('system.testInside') }}</p>
            </div>
            <ul v-if="results" class="list status-list" aria-live="polite">
              <li v-for="kind in kinds" :key="kind" class="status-row">
                <span class="status-icon"><AppIcon name="globe" :size="20" /></span>
                <span class="status-text">
                  <span class="status-label">{{ t(`system.${kind}`) }}</span>
                  <span class="muted small">{{ t(`system.result.${results[kind]}`) }}</span>
                </span>
                <HealthBadge :tone="resultTone(results[kind])" :label="t(`system.resultShort.${results[kind]}`)" />
              </li>
            </ul>
            <div v-if="results && allOk" class="notice notice-success small" role="status">
              <AppIcon name="checkCircle" />
              <p>{{ t('system.testAllOk') }}</p>
            </div>
            <div v-if="anyFail" class="notice notice-danger small" role="status">
              <AppIcon name="alert" />
              <p>{{ t('system.testAdvice', { port: info.relay.port }) }}</p>
            </div>
            <p v-if="info.jitsi.running" class="muted small hint">
              <AppIcon name="info" :size="16" />{{ t('system.jvbHint') }}
            </p>
            <div>
              <button type="button" class="btn btn-primary" :disabled="testing" @click="runTest">
                <AppIcon name="play" :size="18" />
                {{ testing ? t('system.testRunning') : results ? t('system.testAgain') : t('system.testRun') }}
              </button>
            </div>
          </div>
        </section>
      </template>
    </LoadState>
  </div>
</template>

<style scoped>
.notice-title {
  font-weight: 600;
}

.status-list {
  display: grid;
}

.status-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2) var(--space-3);
  padding: var(--space-3) 0;
  border-top: 1px solid var(--color-border);
}

.status-row:first-child {
  border-top: 0;
}

.status-icon {
  display: inline-flex;
  flex-shrink: 0;
  color: var(--color-text-muted);
}

.status-text {
  display: grid;
  gap: 2px;
  flex: 1 1 220px;
  min-width: 0;
  overflow-wrap: anywhere;
}

.status-label {
  font-weight: 600;
}

.facts {
  display: grid;
  gap: var(--space-3);
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr));
  margin: 0;
}

.facts dt {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-text-muted);
}

.facts dd {
  display: grid;
  gap: 2px;
  margin: 0;
  overflow-wrap: anywhere;
}

.value {
  font-weight: 600;
}

.test {
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
}

.hint {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
}
</style>
