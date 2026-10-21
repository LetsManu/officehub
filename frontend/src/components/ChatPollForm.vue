<script setup lang="ts">
/** Ask the conversation a quick question with two to ten answers. */
import { ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import BaseModal from './BaseModal.vue'
import { api } from '@/lib/api'
import { errorText, t } from '@/lib/i18n'
import { showToast } from '@/lib/toast'
import type { ChatMessage } from '@/lib/types'

const props = defineProps<{ open: boolean; channelId: number; question?: string }>()
const emit = defineEmits<{ close: []; created: [message: ChatMessage] }>()

const MAX = 10
const text = ref('')
const options = ref<string[]>(['', ''])
const multi = ref(false)
const busy = ref(false)
const error = ref('')

watch(() => props.open, (open) => {
  if (!open) return
  text.value = props.question ?? ''
  options.value = ['', '']
  multi.value = false
  error.value = ''
})

async function save() {
  const answers = options.value.map((o) => o.trim()).filter(Boolean)
  if (!text.value.trim()) {
    error.value = t('chat.pollNeedsQuestion')
    return
  }
  if (new Set(answers).size < 2) {
    error.value = t('errors.poll_options')
    return
  }
  busy.value = true
  try {
    emit('created', await api.post<ChatMessage>(`/api/chat/${props.channelId}/polls`, { question: text.value.trim(), options: answers, multi: multi.value }))
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <BaseModal :open="open" :title="t('chat.newPoll')" :confirm-label="t('chat.postPoll')" :busy="busy" @close="emit('close')" @confirm="save">
    <div class="poll-form">
      <div class="field">
        <label for="poll-question" class="label">{{ t('chat.pollQuestion') }}</label>
        <input id="poll-question" v-model="text" class="input" maxlength="300" :placeholder="t('chat.pollQuestionPlaceholder')" autocomplete="off" />
      </div>
      <fieldset class="field">
        <legend class="label">{{ t('chat.pollAnswers') }}</legend>
        <div v-for="(_o, i) in options" :key="i" class="answer">
          <label :for="`poll-option-${i}`" class="visually-hidden">{{ t('chat.pollAnswer', { n: i + 1 }) }}</label>
          <input :id="`poll-option-${i}`" v-model="options[i]" class="input" maxlength="120" :placeholder="t('chat.pollAnswer', { n: i + 1 })" autocomplete="off" />
          <button v-if="options.length > 2" type="button" class="btn btn-ghost btn-icon" :aria-label="t('chat.pollRemoveAnswer', { n: i + 1 })" @click="options.splice(i, 1)"><AppIcon name="close" :size="16" /></button>
        </div>
        <button v-if="options.length < MAX" type="button" class="btn btn-ghost add" @click="options.push('')"><AppIcon name="plus" :size="16" />{{ t('chat.pollAddAnswer') }}</button>
      </fieldset>
      <label class="check"><input v-model="multi" type="checkbox" />{{ t('chat.pollMultiLabel') }}</label>
      <p v-if="error" class="notice notice-danger small" role="alert">{{ error }}</p>
    </div>
  </BaseModal>
</template>

<style scoped>
.poll-form {
  display: grid;
  gap: var(--space-4);
}

.field {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  border: 0;
}

.label {
  font-weight: 600;
}

.answer {
  display: flex;
  gap: var(--space-2);
}

.answer .input {
  flex: 1;
}

.add {
  justify-self: start;
}

.check {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
</style>
