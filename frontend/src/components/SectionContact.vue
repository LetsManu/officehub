<script setup lang="ts">
// "Questions? Contact …" line at the bottom of a page, configured by HR per section.
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'
import { portalSettings } from '@/lib/portal'
import { t } from '@/lib/i18n'

const props = defineProps<{ section: string }>()
const contact = computed(() => portalSettings.value.section_contacts[props.section])
</script>

<template>
  <aside v-if="contact" class="section-contact" :aria-label="t('profile.contact')">
    <AppIcon name="info" :size="18" />
    <p>{{ t('contact.question', { name: contact.full_name }) }}</p>
    <span class="links">
      <a :href="`mailto:${contact.email}`" :aria-label="t('contact.write', { name: contact.full_name })"><AppIcon name="mail" :size="18" />{{ contact.email }}</a>
      <a v-if="contact.phone" :href="`tel:${contact.phone.replace(/[^0-9+]/g, '')}`" :aria-label="t('contact.call', { name: contact.full_name })">
        <AppIcon name="phone" :size="18" />{{ contact.phone }}
      </a>
    </span>
  </aside>
</template>

<style scoped>
.section-contact {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2) var(--space-3);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.links {
  display: inline-flex;
  flex-wrap: wrap;
  gap: var(--space-3);
}

.links a {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: var(--touch);
  font-weight: 600;
}

@media print {
  .section-contact {
    display: none;
  }
}
</style>
