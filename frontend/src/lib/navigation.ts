/** Pages in the sidebar. The search palette offers the same list, so both stay in sync. */

import { computed } from 'vue'
import { t } from './i18n'
import { decidesRequests, isAdmin, isApprover, isHr, isOverseer, isStaff, isSupport } from './session'
import { summary } from './summary'

export interface NavItem {
  to: string
  label: string
  icon: string
  count?: number
  /** Shorter name for the narrow app bar. */
  short?: string
}

export interface NavGroup {
  key: string
  label: string
  items: NavItem[]
  /** Can be folded away in the menu (less used areas). */
  collapsible?: boolean
}

/**
 * Ordered like the tools people already know (Teams, Outlook): the everyday tools at the top – also the
 * only ones in the slim icon bar – then "my working day", the company and the office.
 */
export const navGroups = computed<NavGroup[]>(() => {
  const groups: NavGroup[] = [
    {
      key: 'daily',
      label: '',
      items: [
        { to: '/', label: t('nav.dashboard'), icon: 'home' },
        { to: '/activity', label: t('nav.activity'), icon: 'bell', count: summary.value.unread },
        { to: '/chat', label: t('nav.chat'), icon: 'chat', count: summary.value.chat_unread },
        { to: '/calendar', label: t('nav.calendar'), icon: 'calendar' },
        { to: '/spaces', label: t('nav.spaces'), icon: 'spaces' },
        { to: '/tasks', label: t('nav.tasks'), icon: 'kanban', count: summary.value.cards_due },
        { to: '/files', label: t('nav.files'), icon: 'folder' },
      ],
    },
    {
      key: 'me',
      label: t('nav.groupMyDay'),
      items: [
        { to: '/time', label: t('nav.time'), short: t('nav.short.time'), icon: 'clock', count: summary.value.time_months_pending },
        { to: '/requests', label: t('nav.requests'), short: t('nav.short.requests'), icon: 'inbox' },
        { to: '/planning', label: t('nav.planning'), icon: 'planning' },
        { to: '/trainings', label: t('nav.trainings'), icon: 'graduation', count: summary.value.trainings_due },
        { to: '/reviews', label: t('nav.reviews'), short: t('nav.short.reviews'), icon: 'message', count: summary.value.reviews_todo },
      ],
    },
    {
      key: 'company',
      label: t('nav.groupCompany'),
      collapsible: true,
      items: [
        { to: '/announcements', label: t('nav.announcements'), icon: 'megaphone', count: summary.value.must_read_open },
        { to: '/documents', label: t('nav.documents'), icon: 'file', count: summary.value.personal_documents_new },
        { to: '/people', label: t('nav.people'), icon: 'users' },
        { to: '/surveys', label: t('nav.surveys'), icon: 'chart', count: summary.value.surveys_open },
        { to: '/ideas', label: t('nav.ideas'), icon: 'lightbulb' },
        { to: '/help', label: t('nav.help'), icon: 'lifebuoy' },
      ],
    },
    {
      key: 'office',
      label: t('nav.groupOffice'),
      collapsible: true,
      items: [
        { to: '/rooms', label: t('nav.rooms'), short: t('nav.short.rooms'), icon: 'door' },
        { to: '/visitors', label: t('nav.visitors'), icon: 'badge', count: summary.value.visitors_today },
      ],
    },
  ]
  const manage: NavItem[] = []
  if (decidesRequests.value || summary.value.acting_deputy) {
    manage.push({ to: '/approvals', label: t('nav.approvals'), icon: 'checkCircle', count: summary.value.approvals_pending })
  }
  if (isApprover.value || isHr.value) manage.push({ to: '/onboarding', label: t('nav.onboarding'), icon: 'clipboard' })
  if (isOverseer.value) manage.push({ to: '/reports', label: t('nav.reports'), icon: 'chart' })
  if (isHr.value) {
    manage.push({ to: '/manage/documents', label: t('nav.manageDocuments'), short: t('nav.documents'), icon: 'folder' })
    manage.push({ to: '/manage/announcements', label: t('nav.manageAnnouncements'), short: t('nav.announcements'), icon: 'edit' })
  }
  if (isSupport.value) manage.push({ to: '/equipment', label: t('nav.equipment'), icon: 'box' })
  if (isAdmin.value) manage.push({ to: '/admin/audit', label: t('nav.audit'), icon: 'history' })
  if (isAdmin.value) manage.push({ to: '/admin/system', label: t('nav.system'), icon: 'shield' })
  if (isStaff.value) manage.push({ to: '/admin', label: t('nav.administration'), short: t('nav.short.administration'), icon: 'settings' })
  if (manage.length) groups.push({ key: 'manage', label: t('nav.manage'), items: manage, collapsible: true })
  return groups
})

export const allPages = computed<NavItem[]>(() => [
  ...navGroups.value.flatMap((group) => group.items),
  { to: '/meetings', label: t('nav.meetings'), icon: 'video' },
  { to: '/profile', label: t('nav.profile'), icon: 'user' },
  { to: '/whats-new', label: t('whatsNew.title'), icon: 'star' },
])
