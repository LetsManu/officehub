<script setup lang="ts">
/** A QR code drawn here in the browser (never by the server: it carries a security number). */
import { computed } from 'vue'
import { encode } from 'uqr'

const props = defineProps<{ text: string; label: string }>()

const code = computed(() => {
  const qr = encode(props.text, { ecc: 'M', border: 2 })
  let d = ''
  qr.data.forEach((row, y) => row.forEach((dark, x) => {
    if (dark) d += `M${x} ${y}h1v1h-1z`
  }))
  return { size: qr.size, d }
})
</script>

<template>
  <svg class="qr" :viewBox="`0 0 ${code.size} ${code.size}`" role="img" :aria-label="label" shape-rendering="crispEdges">
    <rect :width="code.size" :height="code.size" fill="#fff" />
    <path :d="code.d" fill="#000" />
  </svg>
</template>

<style scoped>
.qr {
  width: 100%;
  max-width: 220px;
  height: auto;
  border-radius: var(--radius-sm, 6px);
}
</style>
