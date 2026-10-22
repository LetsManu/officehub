import { describe, expect, it } from 'vitest'
import { decodeHeader, encodeHeader, kidOf, open, peek, seal, senderKey, splitKid } from '../src/lib/e2ee/sframe-core'

const hex = (b: Uint8Array) => Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')

describe('SFrame header (RFC 9605 4.3)', () => {
  it('encodes small values in the config byte and longer ones after it', () => {
    expect(hex(encodeHeader(0n, 0n))).toBe('00')
    expect(hex(encodeHeader(7n, 7n))).toBe('77')
    expect(hex(encodeHeader(8n, 0n))).toBe('8008')
    expect(hex(encodeHeader(0n, 8n))).toBe('0808')
    expect(hex(encodeHeader(0x0102n, 0x030405n))).toBe('9a0102030405')
  })
  it('reads back what it writes', () => {
    for (const [kid, ctr] of [[0n, 0n], [5n, 300n], [0xffffn, 1n], [kidOf(41, 300), 123456789n]] as [bigint, bigint][]) {
      const h = encodeHeader(kid, ctr)
      expect(decodeHeader(h)).toEqual({ kid, ctr, length: h.length })
    }
    expect(decodeHeader(new Uint8Array([0x9a, 1]))).toBeNull() // cut short: no crash
  })
  it('puts the sender and the epoch into the key id', () => {
    expect(splitKid(kidOf(3, 257))).toEqual({ leaf: 3, epochBits: 1 })
  })
})

describe('SFrame frames', () => {
  const secret = new Uint8Array(32).map((_, i) => i)
  it('seals and opens a frame, keeping the codec bytes readable', async () => {
    const key = await senderKey(secret, 2, 5)
    const frame = new Uint8Array([0xaa, 0xbb, 0xcc, 1, 2, 3, 4, 5])
    const sealed = await seal(frame, 3, key, kidOf(2, 5), 42n)
    expect(Array.from(sealed.subarray(0, 3))).toEqual([0xaa, 0xbb, 0xcc])
    expect(hex(sealed)).not.toContain('0102030405')
    expect(peek(sealed, 3)?.kid).toBe(kidOf(2, 5))
    expect(Array.from((await open(sealed, 3, key))!)).toEqual(Array.from(frame))
  })
  it('refuses a frame changed on the way, or with another sender key', async () => {
    const key = await senderKey(secret, 2, 5)
    const sealed = await seal(new Uint8Array([9, 8, 7, 6]), 1, key, kidOf(2, 5), 1n)
    const tampered = sealed.slice()
    tampered[0] ^= 1 // the readable byte is authenticated too
    expect(await open(tampered, 1, key)).toBeNull()
    expect(await open(sealed, 1, await senderKey(secret, 3, 5))).toBeNull()
    expect(await open(sealed, 1, await senderKey(new Uint8Array(32), 2, 5))).toBeNull()
  })
})
