import { describe, expect, it } from 'vitest'
import { language } from '../src/lib/i18n'
import { lastSynced, problemText, reasonText, syncedText } from '../src/lib/syncStatus'
import type { SyncDevice } from '../src/lib/types'

const base: SyncDevice = {
  device_name: 'ANNA-PC',
  app_version: '1.4.0',
  status: 'ok',
  reports: true,
  last_contact_at: '2026-10-25T09:59:00Z',
  last_sync_at: '2026-10-25T09:55:00Z',
  failed_count: 0,
  failed: [],
  pending_uploads: 0,
  last_error: '',
}
const now = Date.parse('2026-10-25T10:00:00Z')

describe('sync status texts', () => {
  it('says when the folder last synced', () => {
    language.value = 'en'
    expect(syncedText(base, 'en-GB', now)).toBe('Last synced 5 minutes ago')
    expect(syncedText({ ...base, last_sync_at: null }, 'en-GB', now)).toBe('Not synced yet')
    // An older app without reports: its last contact counts
    expect(lastSynced({ ...base, reports: false })).toBe(base.last_contact_at)
  })

  it('explains problems in plain words', () => {
    language.value = 'en'
    expect(problemText(base)).toBe('')
    const failed = { ...base, failed_count: 3, failed: [{ path: 'a.zip', reason: 'tooLarge' }] }
    expect(problemText(failed)).toBe('Problems: 3 files not uploaded – too large for OfficeHub')
    expect(problemText({ ...failed, failed_count: 1 })).toBe('Problems: 1 file not uploaded – too large for OfficeHub')
    expect(problemText({ ...base, last_error: 'HTTP 500' })).toBe('The last sync did not work. It will try again by itself.')
    expect(reasonText('something else')).toBe('something else')
    language.value = 'de'
    expect(problemText(failed)).toBe('Probleme: 3 Dateien nicht hochgeladen – zu groß für OfficeHub')
  })
})
