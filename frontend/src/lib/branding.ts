/**
 * Company branding (name, logo, accent colour). Loaded without sign-in so the login page can use it.
 * The accent colour is turned into the primary colour tokens for light and dark mode.
 */

import { ref, watch } from 'vue'
import { api } from './api'
import { theme } from './theme'

export interface Branding {
  company_name: string
  accent_color: string
  logo_version: string | null
}

export const DEFAULT_ACCENT = '#1D4ED8'
export const branding = ref<Branding>({ company_name: '', accent_color: DEFAULT_ACCENT, logo_version: null })

type Rgb = [number, number, number]

function hexToRgb(hex: string): Rgb {
  const value = parseInt(hex.slice(1), 16)
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255]
}

function rgbToHex([r, g, b]: Rgb): string {
  return `#${[r, g, b].map((c) => Math.round(Math.min(255, Math.max(0, c))).toString(16).padStart(2, '0')).join('')}`
}

function mix(a: Rgb, b: Rgb, amount: number): Rgb {
  return [0, 1, 2].map((i) => a[i] + (b[i] - a[i]) * amount) as Rgb
}

function luminance([r, g, b]: Rgb): number {
  const channel = (c: number) => {
    const v = c / 255
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
}

export function contrast(a: string, b: string): number {
  const [l1, l2] = [luminance(hexToRgb(a)), luminance(hexToRgb(b))].sort((x, y) => y - x)
  return (l1 + 0.05) / (l2 + 0.05)
}

/** Primary colour tokens derived from one accent colour. */
export function accentTokens(accent: string, dark: boolean): Record<string, string> {
  const base = hexToRgb(accent)
  const white: Rgb = [255, 255, 255]
  if (!dark) {
    return {
      '--color-primary': accent,
      '--color-primary-hover': rgbToHex(mix(base, [0, 0, 0], 0.15)),
      '--color-primary-soft': rgbToHex(mix(base, white, 0.92)),
      '--color-primary-text': accent,
      '--color-focus': accent,
      '--color-highlight': `linear-gradient(135deg, ${accent} 0%, ${rgbToHex(mix(base, white, 0.25))} 100%)`,
    }
  }
  const surface = '#151a22'
  // Lighten the text colour until it is readable on the dark surface.
  let text = base
  for (let i = 0; i < 20 && contrast(rgbToHex(text), surface) < 6; i++) text = mix(text, white, 0.12)
  return {
    '--color-primary': accent,
    '--color-primary-hover': rgbToHex(mix(base, white, 0.12)),
    '--color-primary-soft': rgbToHex(mix(hexToRgb(surface), base, 0.22)),
    '--color-primary-text': rgbToHex(text),
    '--color-focus': rgbToHex(text),
    '--color-highlight': `linear-gradient(135deg, ${rgbToHex(mix(base, [0, 0, 0], 0.3))} 0%, ${accent} 100%)`,
  }
}

const TOKEN_NAMES = Object.keys(accentTokens(DEFAULT_ACCENT, false))

export function applyBranding(): void {
  const root = document.documentElement
  const accent = branding.value.accent_color.toUpperCase()
  for (const name of TOKEN_NAMES) root.style.removeProperty(name)
  if (accent !== DEFAULT_ACCENT) {
    for (const [name, value] of Object.entries(accentTokens(accent, theme.value === 'dark'))) root.style.setProperty(name, value)
  }
  // Use the company logo as the browser tab icon.
  const icon = document.querySelector<HTMLLinkElement>('link[rel="icon"]')
  if (icon) icon.href = branding.value.logo_version ? logoUrl() : '/favicon.svg'
}

export function logoUrl(): string {
  return `/api/branding/logo?v=${branding.value.logo_version ?? ''}`
}

export function photoUrl(personId: number, version: string | null | undefined): string | null {
  return version ? `/api/directory/${personId}/photo?v=${version}` : null
}

export async function loadBranding(): Promise<void> {
  try {
    branding.value = await api.get<Branding>('/api/branding')
  } catch {
    /* defaults stay */
  }
  applyBranding()
}

export function setBranding(value: Branding): void {
  branding.value = value
  applyBranding()
}

watch(theme, applyBranding)
