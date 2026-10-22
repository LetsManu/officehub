<script setup lang="ts">
/**
 * Choosing a camera, microphone or loudspeaker. Its own component on purpose: the meeting screen redraws many times a
 * second (microphone level, who is speaking), and a select inside it would be set anew each time and flicker.
 */
import { t } from '@/lib/i18n'

defineProps<{ label: string; devices: MediaDeviceInfo[] }>()
const model = defineModel<string>({ required: true })
const emit = defineEmits<{ change: [] }>()
</script>

<template>
  <label class="field">
    <span>{{ label }}</span>
    <select v-model="model" class="select" @change="emit('change')">
      <option value="">{{ t('meeting.defaultDevice') }}</option>
      <option v-for="d in devices" :key="d.deviceId" :value="d.deviceId">{{ d.label || label }}</option>
    </select>
  </label>
</template>
