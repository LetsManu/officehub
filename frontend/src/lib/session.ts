import { computed, ref } from 'vue'
import { api } from './api'
import { setLanguage, t } from './i18n'
import { appSignedIn } from './native'
import type { PublicConfig, Role, User } from './types'

export const currentUser = ref<User | null>(null)
export const publicConfig = ref<PublicConfig | null>(null)

/** All roles of a person, main one first (older servers only send the one role). */
export function rolesOf(user: Pick<User, 'role' | 'roles'> | null | undefined): Role[] {
  if (!user) return []
  if (user.roles?.length) return user.roles
  if (user.role === 'admin') return ['admin', 'hr']
  return user.role === 'employee' ? [] : [user.role]
}

/** "Team lead, Service desk" – or "Employee" when there is nothing more. */
export function roleNames(user: Pick<User, 'role' | 'roles'> | null | undefined): string {
  const held = rolesOf(user)
  return (held.length ? held : ['employee']).map((r) => t(`roles.${r}`)).join(', ')
}

/** Admins may do everything. */
function has(...names: Role[]) {
  const held = rolesOf(currentUser.value)
  return held.includes('admin') || names.some((n) => held.includes(n))
}

export const isAdmin = computed(() => rolesOf(currentUser.value).includes('admin'))
/** Decides requests and time sheets: their own team (team lead) or everyone. */
export const isApprover = computed(() => has('teamlead', 'manager', 'hr'))
/** Decides for everyone: company-wide reports and statistics. */
export const isOverseer = computed(() => has('manager', 'hr'))
export const isHr = computed(() => has('hr'))
export const isServiceDesk = computed(() => has('servicedesk'))
/** HR or service desk: passwords, two-factor, equipment. */
export const isSupport = computed(() => has('hr', 'servicedesk'))
/** Anyone who decides some requests (the service desk: IT access and equipment). */
export const decidesRequests = computed(() => isApprover.value || isServiceDesk.value)
/** More than the employee role: sees the administration page. */
export const isStaff = computed(() => isApprover.value || isSupport.value)

let loaded = false

export function setUser(user: User | null): void {
  currentUser.value = user
  if (user) setLanguage(user.language)
}

/** Loads the signed-in user once per page load. Returns null when not signed in. */
export async function loadSession(): Promise<User | null> {
  if (loaded) return currentUser.value
  try {
    setUser(await api.get<User>('/api/auth/me'))
  } catch {
    currentUser.value = null
  }
  loaded = true
  return currentUser.value
}

export async function loadConfig(): Promise<PublicConfig> {
  if (!publicConfig.value) {
    try {
      publicConfig.value = await api.get<PublicConfig>('/api/config')
    } catch {
      publicConfig.value = { demo_mode: false, max_upload_mb: 15 }
    }
  }
  return publicConfig.value
}

export async function signIn(email: string, password: string, code?: string): Promise<User> {
  const user = await api.post<User>('/api/auth/login', { email, password, ...(code ? { code } : {}) })
  setUser(user)
  loaded = true
  return user
}

export async function signOut(): Promise<void> {
  try {
    await api.post('/api/auth/logout')
  } finally {
    currentUser.value = null
    appSignedIn(false)
  }
}

export function clearSession(): void {
  currentUser.value = null
}
