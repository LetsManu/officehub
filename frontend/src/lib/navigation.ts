/** Pages in the sidebar. The search palette offers the same list, so both stay in sync. */

import { computed } from 'vue'
import { t } from './i18n'
import { isAdmin, isApprover } from './session'
import { summary } from './summary'

export interface NavItem {
  to: string
  label: string
  icon: string
  count?: number
}

export interface NavGroup {
  key: string
  label: string
  items: NavItem[]
}

export const navGroups = computed<NavGroup[]>(() => {
  const groups: NavGroup[] = [
    {
      key: 'start',
      label: '',
      items: [
        { to: '/', label: t('nav.dashboard'), icon: 'dashboard' },
        { to: '/time', label: t('nav.time'), icon: 'clock', count: summary.value.time_months_pending },
        { to: '/planning', label: t('nav.planning'), icon: 'planning' },
        { to: '/requests', label: t('nav.requests'), icon: 'inbox' },
        { to: '/announcements', label: t('nav.announcements'), icon: 'megaphone', count: summary.value.must_read_open },
      ],
    },
    {
      key: 'find',
      label: t('nav.groupFind'),
      items: [
        { to: '/documents', label: t('nav.documents'), icon: 'file', count: summary.value.personal_documents_new },
        { to: '/people', label: t('nav.people'), icon: 'users' },
        { to: '/help', label: t('nav.help'), icon: 'lifebuoy' },
      ],
    },
    {
      key: 'office',
      label: t('nav.groupOffice'),
      items: [
        { to: '/calendar', label: t('nav.calendar'), icon: 'calendar' },
        { to: '/rooms', label: t('nav.rooms'), icon: 'door' },
        { to: '/visitors', label: t('nav.visitors'), icon: 'badge', count: summary.value.visitors_today },
        { to: '/reviews', label: t('nav.reviews'), icon: 'message', count: summary.value.reviews_todo },
        { to: '/trainings', label: t('nav.trainings'), icon: 'graduation', count: summary.value.trainings_due },
      ],
    },
    {
      key: 'together',
      label: t('nav.groupTogether'),
      items: [
        { to: '/surveys', label: t('nav.surveys'), icon: 'chart', count: summary.value.surveys_open },
        { to: '/ideas', label: t('nav.ideas'), icon: 'lightbulb' },
      ],
    },
  ]
  const manage: NavItem[] = []
  if (isApprover.value || summary.value.acting_deputy) {
    manage.push({ to: '/approvals', label: t('nav.approvals'), icon: 'checkCircle', count: summary.value.approvals_pending })
  }
  if (isApprover.value) {
    manage.push({ to: '/onboarding', label: t('nav.onboarding'), icon: 'clipboard' })
    manage.push({ to: '/reports', label: t('nav.reports'), icon: 'chart' })
  }
  if (isAdmin.value) {
    manage.push({ to: '/manage/documents', label: t('nav.manageDocuments'), icon: 'folder' })
    manage.push({ to: '/manage/announcements', label: t('nav.manageAnnouncements'), icon: 'edit' })
    manage.push({ to: '/equipment', label: t('nav.equipment'), icon: 'box' })
    manage.push({ to: '/admin/audit', label: t('nav.audit'), icon: 'history' })
  }
  if (isApprover.value) manage.push({ to: '/admin', label: t('nav.administration'), icon: 'settings' })
  if (manage.length) groups.push({ key: 'manage', label: t('nav.manage'), items: manage })
  return groups
})

export const allPages = computed<NavItem[]>(() => [
  ...navGroups.value.flatMap((group) => group.items),
  { to: '/profile', label: t('nav.profile'), icon: 'user' },
  { to: '/whats-new', label: t('whatsNew.title'), icon: 'star' },
])
