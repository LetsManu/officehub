/** Tiny translation helper. German is the default language. */

import { computed, ref } from 'vue'
import de from '@/locales/de'
import en from '@/locales/en'
import type { Language } from './types'

const KEY = 'officehub.language'
const messages = { de, en } as const

function storedLanguage(): Language {
  try {
    return localStorage.getItem(KEY) === 'en' ? 'en' : 'de'
  } catch {
    return 'de'
  }
}

export const language = ref<Language>(storedLanguage())
export const locale = computed(() => (language.value === 'de' ? 'de-DE' : 'en-GB'))

export function setLanguage(value: Language): void {
  language.value = value
  document.documentElement.lang = value
  try {
    localStorage.setItem(KEY, value)
  } catch {
    /* not remembered without storage */
  }
}

function lookup(source: unknown, key: string): string | undefined {
  let node: unknown = source
  for (const part of key.split('.')) {
    if (node && typeof node === 'object' && part in node) node = (node as Record<string, unknown>)[part]
    else return undefined
  }
  return typeof node === 'string' ? node : undefined
}

export function t(key: string, params: Record<string, string | number> = {}): string {
  const text = lookup(messages[language.value], key) ?? lookup(messages.de, key) ?? key
  return text.replace(/\{(\w+)\}/g, (_, name: string) => (name in params ? String(params[name]) : `{${name}}`))
}

/** Translates an API error code, falling back to the server message. */
export function errorText(error: unknown): string {
  const code = (error as { code?: string })?.code
  if (code) {
    const known = lookup(messages[language.value], `errors.${code}`) ?? lookup(messages[language.value], `validation.${code}`)
    if (known) return known
  }
  const message = (error as { message?: string })?.message
  return message || t('errors.unknown')
}

// Date and number formatting in the user's language.

function toDate(value: string): Date | null {
  const date = value.length === 10 ? new Date(`${value}T00:00:00`) : new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

function format(value: string | null | undefined, options: Intl.DateTimeFormatOptions): string {
  if (!value) return ''
  const date = toDate(value)
  return date ? new Intl.DateTimeFormat(locale.value, options).format(date) : value
}

export function formatDate(value: string | null | undefined): string {
  return format(value, { day: 'numeric', month: 'short', year: 'numeric' })
}

export function formatDateLong(value: string | null | undefined): string {
  return format(value, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
}

export function formatDateTime(value: string | null | undefined): string {
  return format(value, { dateStyle: 'medium', timeStyle: 'short' })
}

export function formatPeriod(start: string | null, end: string | null): string {
  if (!start) return ''
  if (!end || end === start) return formatDate(start)
  return `${formatDate(start)} – ${formatDate(end)}`
}

export function formatMoney(amount: string | null, currency: string | null): string {
  if (amount === null) return ''
  return new Intl.NumberFormat(locale.value, { style: 'currency', currency: currency || 'EUR' }).format(Number(amount))
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function useI18n() {
  return { t, language, formatDate, formatDateLong, formatDateTime, formatPeriod, formatMoney, formatFileSize, errorText }
}
