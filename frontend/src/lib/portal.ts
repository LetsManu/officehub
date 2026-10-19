/** Portal-wide settings (dashboard tiles, section contacts) and quick links, loaded once per sign-in. */

import { ref } from 'vue'
import { api } from './api'
import type { PortalSettings, QuickLink } from './types'

export const portalSettings = ref<PortalSettings>({ dashboard_tiles: [], section_contacts: {} })
export const quickLinks = ref<QuickLink[]>([])

let loaded = false

export async function loadPortal(force = false): Promise<void> {
  if (loaded && !force) return
  try {
    const [settings, links] = await Promise.all([
      api.get<PortalSettings>('/api/portal/settings'),
      api.get<QuickLink[]>('/api/portal/links'),
    ])
    portalSettings.value = settings
    quickLinks.value = links
    loaded = true
  } catch {
    /* the portal still works without these extras */
  }
}

export function resetPortal(): void {
  loaded = false
  quickLinks.value = []
}
