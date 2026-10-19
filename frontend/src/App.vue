<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from './components/AppLayout.vue'
import ToastHost from './components/ToastHost.vue'
import { currentUser, loadConfig } from './lib/session'
import { loadPortal } from './lib/portal'

const route = useRoute()
const withLayout = computed(() => !route.meta.public && currentUser.value !== null)

// Portal extras (quick links, tiles, contacts) and the version are loaded once after sign-in.
watch(
  () => currentUser.value?.id,
  (id) => {
    if (id) {
      loadPortal()
      loadConfig()
    }
  },
  { immediate: true },
)
</script>

<template>
  <AppLayout v-if="withLayout">
    <RouterView />
  </AppLayout>
  <RouterView v-else />
  <ToastHost />
</template>
