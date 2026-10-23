/** Helpers for team spaces: file icons, sizes and which files open in the office editor. */

import { api } from './api'
import type { OfficeConfig } from './types'

const OFFICE = new Set(['docx', 'xlsx', 'pptx', 'odt', 'ods', 'odp', 'doc', 'xls', 'ppt', 'rtf', 'csv'])
const PREVIEW = new Set(['pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'txt', 'md'])

export function fileIcon(type: string): string {
  if (['docx', 'doc', 'odt', 'rtf', 'md', 'txt'].includes(type)) return 'file'
  if (['xlsx', 'xls', 'ods', 'csv'].includes(type)) return 'table'
  if (['pptx', 'ppt', 'odp', 'deckcraft'].includes(type)) return 'presentation'
  if (['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(type)) return 'image'
  if (type === 'pdf') return 'filePdf'
  return 'paperclip'
}

/** Colour family per type, shown as a small tinted icon box. */
export function fileTone(type: string): string {
  if (['docx', 'doc', 'odt', 'rtf'].includes(type)) return 'blue'
  if (['xlsx', 'xls', 'ods', 'csv'].includes(type)) return 'green'
  if (['pptx', 'ppt', 'odp', 'deckcraft'].includes(type)) return 'orange'
  if (type === 'pdf') return 'pink'
  if (['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(type)) return 'purple'
  return 'slate'
}

export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.0', '')} MB`
}

export function isOffice(type: string): boolean {
  return OFFICE.has(type)
}

export function canPreview(type: string): boolean {
  return PREVIEW.has(type)
}

let officeConfig: Promise<OfficeConfig> | null = null

/** Which office servers are set up (asked once per page load). */
export function loadOfficeConfig(force = false): Promise<OfficeConfig> {
  if (!officeConfig || force) {
    officeConfig = api.get<OfficeConfig>('/api/office/config').catch(() => ({ engines: [], default: null, editable: {} }))
  }
  return officeConfig
}

export type CraftAppName = 'wordcraft' | 'deckcraft' | 'gridcraft'

export interface CraftConfig {
  apps: CraftAppName[]
  types: Record<string, string[]>
}

let craftConfig: Promise<CraftConfig> | null = null

/** WordCraft / DeckCraft / GridCraft in the browser: which run in the stack and which file types they edit. */
export function loadCraftConfig(): Promise<CraftConfig> {
  craftConfig ??= api.get<CraftConfig>('/api/craft/config').catch(() => ({ apps: [], types: {} }))
  return craftConfig
}

const warmed = new Set<string>()

/**
 * Fetch the craft programs' large program files in the background while someone looks at files, so opening a
 * document is quick. Once per version: the service worker keeps them. Skipped when the connection is slow or the
 * person asked to save data.
 */
export function warmCraft(apps: CraftAppName[]): void {
  const connection = (navigator as Navigator & { connection?: { saveData?: boolean; effectiveType?: string } }).connection
  if (connection?.saveData || /2g/.test(connection?.effectiveType ?? '') || !navigator.serviceWorker?.controller) return
  for (const app of apps) {
    if (warmed.has(app)) continue
    warmed.add(app)
    window.setTimeout(async () => {
      try {
        const list = (await (await fetch(`/${app}/assets.json`)).json()) as { files?: string[] }
        for (const file of list.files ?? []) await fetch(`/${app}/${file}`)
      } catch {
        /* the program then loads when the document opens */
      }
    }, 3000)
  }
}

/** The browser program for a file, if it runs: "wordcraft", "deckcraft" or "gridcraft". */
export function craftApp(config: CraftConfig, type: string): CraftAppName | null {
  return config.apps.find((app) => config.types[app]?.includes(type)) ?? null
}

/** The network-drive address of a file: for Windows Explorer (\\server@SSL\dav\…) and for other systems (https://…). */
export function driveAddresses(drivePath: string): { windows: string; web: string } {
  const { protocol, host } = window.location
  const decoded = decodeURIComponent(drivePath)
  const ssl = protocol === 'https:' ? '@SSL' : ''
  const [hostname, port] = host.split(':')
  const portPart = port ? `@${port}` : ''
  return {
    windows: `\\\\${hostname}${ssl}${portPart}${decoded.replace(/\//g, '\\')}`,
    web: `${protocol}//${host}${drivePath}`,
  }
}

/** "@Anna Mayer" mentions in a message, matched against the members of the conversation. */
export function findMentions(text: string, members: { id: number; full_name: string }[]): number[] {
  return members.filter((m) => text.includes(`@${m.full_name}`)).map((m) => m.id)
}
