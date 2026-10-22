<script setup lang="ts">
import { computed, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import PageHeader from '@/components/PageHeader.vue'
import { canInstall, installApp } from '@/lib/install'
import { isStandalone, platform, type Platform } from '@/lib/pwa'
import { t } from '@/lib/i18n'
import { inApp } from '@/lib/native'
import { publicConfig } from '@/lib/session'

const PLATFORMS: Platform[] = ['desktop', 'android', 'ios']
const chosen = ref<Platform>(platform())
const installed = isStandalone() || inApp()
const apps = computed(() => publicConfig.value?.apps)
const steps = computed(() => [1, 2, 3].map((n) => t(`install.${chosen.value}.step${n}`)))
</script>

<template>
  <div class="page install-page stack">
    <PageHeader :title="t('install.title')" :subtitle="t('install.subtitle')" back-to="/" />

    <div v-if="installed" class="notice notice-success">
      <AppIcon name="check" />
      <span>{{ t('install.already') }}</span>
    </div>

    <section v-if="!installed && apps" class="card stack">
      <h2>{{ t('install.appsTitle') }}</h2>
      <p class="muted">{{ t('install.appsText') }}</p>
      <div class="app-downloads">
        <a class="btn btn-primary" :href="apps.windows" rel="noopener">
          <AppIcon name="download" />{{ t('install.windowsApp') }}
        </a>
        <a class="btn btn-secondary" :href="apps.android" rel="noopener">
          <AppIcon name="download" />{{ t('install.androidApp') }}
        </a>
      </div>
      <p class="muted small">{{ t('install.appsNote') }}</p>
    </section>

    <section v-if="!installed" class="card stack">
      <h2>{{ t('install.browserTitle') }}</h2>
      <div v-if="canInstall" class="notice notice-info one-click">
        <span>{{ t('install.oneClick') }}</span>
        <button type="button" class="btn btn-primary" @click="installApp">
          <AppIcon name="download" />
          {{ t('app.install') }}
        </button>
      </div>

      <div class="segmented" role="group" :aria-label="t('install.device')">
        <button v-for="p in PLATFORMS" :key="p" type="button" :aria-pressed="chosen === p" @click="chosen = p">
          {{ t(`install.${p}.name`) }}
        </button>
      </div>

      <ol class="steps">
        <li v-for="step in steps" :key="step">{{ step }}</li>
      </ol>
      <p class="muted small">{{ t(`install.${chosen}.note`) }}</p>
    </section>

    <section class="card stack-sm">
      <h2>{{ t('install.benefitsTitle') }}</h2>
      <ul class="benefits">
        <li>{{ t('install.benefit1') }}</li>
        <li>{{ t('install.benefit2') }}</li>
        <li>{{ t('install.benefit3') }}</li>
        <li>{{ t('install.benefit4') }}</li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.install-page {
  max-width: 760px;
}

.app-downloads {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
}

.one-click {
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
}

.segmented {
  align-self: flex-start;
}

.steps,
.benefits {
  margin: 0;
  padding-left: var(--space-5);
  display: grid;
  gap: var(--space-2);
}
</style>
