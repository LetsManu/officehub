import { computed, ref } from 'vue'
import { api } from './api'
import { setLanguage } from './i18n'
import type { PublicConfig, User } from './types'

export const currentUser = ref<User | null>(null)
export const publicConfig = ref<PublicConfig | null>(null)

export const isApprover = computed(() => currentUser.value?.role === 'manager' || currentUser.value?.role === 'admin')
export const isAdmin = computed(() => currentUser.value?.role === 'admin')

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
  }
}

export function clearSession(): void {
  currentUser.value = null
}
