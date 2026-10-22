import { afterEach, describe, expect, it } from 'vitest'
import { appBadge, appKind, appNotify, appRing, appTexts } from '../src/lib/native'

const g = globalThis as unknown as { window?: Record<string, unknown> }

afterEach(() => {
  delete g.window
})

describe('the bridge to the Windows and Android apps', () => {
  it('does nothing in a normal browser', () => {
    expect(appKind()).toBeNull()
    expect(() => appBadge(3)).not.toThrow()
  })

  it('Windows: notifications, badge and ringing go to the app', () => {
    const sent: unknown[] = []
    g.window = { __TAURI_INTERNALS__: { invoke: async (cmd: string, args: unknown) => sent.push([cmd, args]) } }
    expect(appKind()).toBe('windows')
    appNotify({ title: 'Anna', body: 'Hallo', link: '/chat/3', tag: 'c3' })
    appBadge(5)
    appRing({ meeting_id: 9, name: 'Lukas', text: 'ruft an' })
    appRing(null)
    expect(sent.map((s) => ((s as [string, { message: { type: string } }])[1].message.type))).toEqual(['notify', 'badge', 'ring', 'ring-stop'])
    expect((sent[0] as [string])[0]).toBe('app_message')
  })

  it('Android: no notifications from the page (the app shows its own), but the wording for them', () => {
    const sent: Record<string, unknown>[] = []
    g.window = { OfficeHubAndroid: { postMessage: (m: string) => sent.push(JSON.parse(m)) } }
    expect(appKind()).toBe('android')
    appNotify({ title: 'Anna', body: 'Hallo', tag: 'c3' })
    appTexts()
    expect(sent.map((m) => m.type)).toEqual(['texts'])
    const texts = sent[0] as { kinds: Record<string, string>; requestTypes: Record<string, string> }
    expect(texts.kinds.request_approved).toContain('{title}')
    expect(texts.requestTypes.vacation).toBeTruthy()
  })
})
