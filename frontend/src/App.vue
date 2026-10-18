<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from './components/AppLayout.vue'
import ToastHost from './components/ToastHost.vue'
import { currentUser } from './lib/session'

const route = useRoute()
const withLayout = computed(() => !route.meta.public && currentUser.value !== null)
</script>

<template>
  <AppLayout v-if="withLayout">
    <RouterView />
  </AppLayout>
  <RouterView v-else />
  <ToastHost />
</template>
