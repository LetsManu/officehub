<script setup lang="ts">
import EmptyState from '@/components/EmptyState.vue'
import { t } from '@/lib/i18n'
</script>

<template>
  <div class="page">
    <h1>{{ t('notFound.title') }}</h1>
    <section class="card">
      <EmptyState icon="search" :message="t('notFound.text')" :action-label="t('notFound.home')" action-to="/" />
    </section>
  </div>
</template>
