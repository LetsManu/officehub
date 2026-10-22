import { describe, expect, it } from 'vitest'
import {
  checkChain,
  deviceStatement,
  fingerprint,
  leafStatement,
  parseQr,
  qrText,
  securityNumber,
  sign,
  toB64,
  verify,
  type DeviceRecord,
} from '../src/lib/e2ee/identity'

const ALG = { name: 'ECDSA', namedCurve: 'P-256' } as const

async function makeKey() {
  const keys = (await crypto.subtle.generateKey(ALG, false, ['sign', 'verify'])) as CryptoKeyPair
  const publicKey = toB64(new Uint8Array(await crypto.subtle.exportKey('spki', keys.publicKey)))
  return { keys, publicKey }
}

function record(id: number, publicKey: string, extra: Partial<DeviceRecord>): DeviceRecord {
  return { id, public_key: publicKey, name: '', root: false, signed_by: null, signature: '', pending: false, ...extra }
}

describe('a person\'s devices', () => {
  it('trusts the root and what it signed, not what the server adds on its own', async () => {
    const root = await makeKey()
    const phone = await makeKey()
    const intruder = await makeKey()
    const devices = [
      record(1, root.publicKey, { root: true, signature: await sign(root.keys, deviceStatement('7', root.publicKey)) }),
      record(2, phone.publicKey, { signed_by: 1, signature: await sign(root.keys, deviceStatement('7', phone.publicKey)) }),
      // signed by itself, claiming to be confirmed by the root
      record(3, intruder.publicKey, { signed_by: 1, signature: await sign(intruder.keys, deviceStatement('7', intruder.publicKey)) }),
    ]
    const chain = await checkChain('7', devices)
    expect(chain?.root).toBe(await fingerprint(root.publicKey))
    expect(chain?.confirmed.has(phone.publicKey)).toBe(true)
    expect(chain?.confirmed.has(intruder.publicKey)).toBe(false)
    // a signature for another person does not count
    expect((await checkChain('8', devices))).toBeNull()
    // two roots: no chain at all
    expect(await checkChain('7', [...devices, record(4, intruder.publicKey, { root: true })])).toBeNull()
  })

  it('binds an MLS key to a person and nothing else', async () => {
    const device = await makeKey()
    const signature = await sign(device.keys, leafStatement('7', 'bGVhZg=='))
    expect(await verify(device.publicKey, leafStatement('7', 'bGVhZg=='), signature)).toBe(true)
    expect(await verify(device.publicKey, leafStatement('8', 'bGVhZg=='), signature)).toBe(false)
    expect(await verify(device.publicKey, deviceStatement('7', 'bGVhZg=='), signature)).toBe(false)
  })
})

describe('security number', () => {
  it('is 30 digits in groups of five, and the QR code carries person and fingerprint', async () => {
    const fp = await fingerprint((await makeKey()).publicKey)
    expect(securityNumber(fp)).toMatch(/^\d{5}( \d{5}){5}$/)
    expect(parseQr(qrText('12', fp))).toEqual({ userId: '12', fp })
    expect(parseQr('something else')).toBeNull()
  })
})
