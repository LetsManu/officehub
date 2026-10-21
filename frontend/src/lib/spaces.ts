/** Helpers for team spaces: file icons, sizes and which files open in the office editor. */

import { api } from './api'
import type { OfficeConfig } from './types'

const OFFICE = new Set(['docx', 'xlsx', 'pptx', 'odt', 'ods', 'odp', 'doc', 'xls', 'ppt', 'rtf', 'csv'])
const PREVIEW = new Set(['pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'txt', 'md'])

export function fileIcon(type: string): string {
  if (['docx', 'doc', 'odt', 'rtf', 'md', 'txt'].includes(type)) return 'file'
  if (['xlsx', 'xls', 'ods', 'csv'].includes(type)) return 'table'
  if (['pptx', 'ppt', 'odp'].includes(type)) return 'presentation'
  if (['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(type)) return 'image'
  if (type === 'pdf') return 'filePdf'
  return 'paperclip'
}

/** Colour family per type, shown as a small tinted icon box. */
export function fileTone(type: string): string {
  if (['docx', 'doc', 'odt', 'rtf'].includes(type)) return 'blue'
  if (['xlsx', 'xls', 'ods', 'csv'].includes(type)) return 'green'
  if (['pptx', 'ppt', 'odp'].includes(type)) return 'orange'
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

/** "@Anna Mayer" mentions in a message, matched against the members of the conversation. */
export function findMentions(text: string, members: { id: number; full_name: string }[]): number[] {
  return members.filter((m) => text.includes(`@${m.full_name}`)).map((m) => m.id)
}
