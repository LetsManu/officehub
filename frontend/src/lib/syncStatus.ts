/** How a computer's OfficeHub folder syncs (reported by the Windows app, backend services/sync_status.py). */
import { t } from './i18n'
import { timeAgo } from './notifications'
import type { SyncDevice } from './types'

/** When it last synced: older apps send no reports, so their last contact stands for it. */
export function lastSynced(device: SyncDevice): string | null {
  return device.reports ? device.last_sync_at : device.last_contact_at
}

/** A reason from the app ("tooLarge", "readOnly" …) in plain words; anything else as it came. */
export function reasonText(reason: string): string {
  const key = `syncDevices.reasons.${reason}`
  const text = reason ? t(key) : ''
  return text === key ? reason : text
}

/** "Last synced 5 minutes ago" / "Not synced yet". */
export function syncedText(device: SyncDevice, locale: string, now = Date.now()): string {
  const when = lastSynced(device)
  return when ? t('syncDevices.lastSynced', { when: timeAgo(when, locale, now) }) : t('syncDevices.notYet')
}

/** "Problems: 3 files not uploaded – too large for OfficeHub", or '' without problems. */
export function problemText(device: SyncDevice): string {
  if (device.failed_count > 0) {
    const reason = reasonText(device.failed[0]?.reason ?? '')
    const files = device.failed_count === 1 ? t('syncDevices.oneFile') : t('syncDevices.files', { count: device.failed_count })
    return reason ? t('syncDevices.problemsWhy', { files, reason }) : t('syncDevices.problems', { files })
  }
  if (device.last_error) return t('syncDevices.lastRoundFailed')
  return ''
}
