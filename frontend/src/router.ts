import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { nextTick } from 'vue'
import { currentUser, loadSession } from './lib/session'
import { branding } from './lib/branding'
import { t } from './lib/i18n'

declare module 'vue-router' {
  interface RouteMeta {
    public?: boolean
    approver?: boolean
    admin?: boolean
    title?: string
  }
}

const routes: RouteRecordRaw[] = [
  { path: '/login', component: () => import('./views/LoginView.vue'), meta: { public: true, title: 'login.title' } },
  { path: '/', component: () => import('./views/DashboardView.vue'), meta: { title: 'nav.dashboard' } },
  { path: '/requests', component: () => import('./views/RequestsView.vue'), meta: { title: 'nav.requests' } },
  { path: '/requests/new', component: () => import('./views/NewRequestView.vue'), meta: { title: 'requests.new' } },
  { path: '/requests/new/:type', component: () => import('./views/RequestFormView.vue'), props: true, meta: { title: 'requests.new' } },
  { path: '/requests/:id(\\d+)', component: () => import('./views/RequestDetailView.vue'), props: true, meta: { title: 'nav.requests' } },
  { path: '/requests/:id(\\d+)/edit', component: () => import('./views/RequestFormView.vue'), props: true, meta: { title: 'form.editTitle' } },
  { path: '/documents', component: () => import('./views/DocumentsView.vue'), meta: { title: 'nav.documents' } },
  { path: '/documents/:id(\\d+)', component: () => import('./views/DocumentView.vue'), props: true, meta: { title: 'nav.documents' } },
  { path: '/announcements', component: () => import('./views/AnnouncementsView.vue'), meta: { title: 'nav.announcements' } },
  { path: '/profile', component: () => import('./views/ProfileView.vue'), meta: { title: 'nav.profile' } },
  { path: '/people', component: () => import('./views/PeopleView.vue'), meta: { title: 'nav.people' } },
  { path: '/rooms', component: () => import('./views/RoomsView.vue'), meta: { title: 'nav.rooms' } },
  { path: '/visitors', component: () => import('./views/VisitorsView.vue'), meta: { title: 'nav.visitors' } },
  { path: '/reviews', component: () => import('./views/ReviewsView.vue'), meta: { title: 'nav.reviews' } },
  { path: '/reviews/:id(\\d+)', component: () => import('./views/ReviewDetailView.vue'), props: true, meta: { title: 'nav.reviews' } },
  { path: '/onboarding', component: () => import('./views/OnboardingView.vue'), meta: { title: 'nav.onboarding' } },
  { path: '/onboarding/:id(\\d+)', component: () => import('./views/OnboardingDetailView.vue'), props: true, meta: { title: 'nav.onboarding' } },
  { path: '/reports', component: () => import('./views/ReportsView.vue'), meta: { approver: true, title: 'nav.reports' } },
  { path: '/time', component: () => import('./views/TimeView.vue'), meta: { title: 'nav.time' } },
  { path: '/planning', component: () => import('./views/PlanningView.vue'), meta: { title: 'nav.planning' } },
  { path: '/planning/projects', component: () => import('./views/ProjectsView.vue'), meta: { approver: true, title: 'projects.title' } },
  { path: '/planning/projects/:id(\\d+)', component: () => import('./views/ProjectDetailView.vue'), props: true, meta: { approver: true, title: 'projects.title' } },
  { path: '/surveys', component: () => import('./views/SurveysView.vue'), meta: { title: 'nav.surveys' } },
  { path: '/surveys/:id(\\d+)', component: () => import('./views/SurveyView.vue'), props: true, meta: { title: 'nav.surveys' } },
  { path: '/ideas', component: () => import('./views/IdeasView.vue'), meta: { title: 'nav.ideas' } },
  { path: '/trainings', component: () => import('./views/TrainingsView.vue'), meta: { title: 'nav.trainings' } },
  { path: '/equipment', component: () => import('./views/EquipmentView.vue'), meta: { admin: true, title: 'nav.equipment' } },
  { path: '/admin/audit', component: () => import('./views/AuditView.vue'), meta: { admin: true, title: 'nav.audit' } },
  { path: '/calendar', component: () => import('./views/CalendarView.vue'), meta: { title: 'nav.calendar' } },
  { path: '/help', component: () => import('./views/HelpView.vue'), meta: { title: 'nav.help' } },
  { path: '/whats-new', component: () => import('./views/WhatsNewView.vue'), meta: { title: 'whatsNew.title' } },
  // Also open for someone standing in for a manager; the API decides what they see.
  { path: '/approvals', component: () => import('./views/ApprovalsView.vue'), meta: { title: 'nav.approvals' } },
  { path: '/manage/documents', component: () => import('./views/ManageDocumentsView.vue'), meta: { admin: true, title: 'nav.manageDocuments' } },
  { path: '/manage/announcements', component: () => import('./views/ManageAnnouncementsView.vue'), meta: { admin: true, title: 'nav.manageAnnouncements' } },
  { path: '/admin', component: () => import('./views/AdminView.vue'), meta: { approver: true, title: 'nav.administration' } },
  { path: '/:pathMatch(.*)*', component: () => import('./views/NotFoundView.vue'), meta: { title: 'notFound.title' } },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach(async (to) => {
  const user = await loadSession()
  if (to.meta.public) return user && to.path === '/login' ? '/' : true
  if (!user) return { path: '/login', query: to.fullPath !== '/' ? { redirect: to.fullPath } : {} }
  if (to.meta.admin && user.role !== 'admin') return '/'
  if (to.meta.approver && user.role === 'employee') return '/'
  return true
})

let firstNavigation = true

router.afterEach(async (to) => {
  const site = branding.value.company_name || 'OfficeHub'
  document.title = to.meta.title ? `${t(to.meta.title)} · ${site}` : site
  // Move focus to the page content after navigation so screen readers announce the new page.
  if (firstNavigation) {
    firstNavigation = false
    return
  }
  await nextTick()
  if (currentUser.value) document.getElementById('main')?.focus({ preventScroll: true })
})
