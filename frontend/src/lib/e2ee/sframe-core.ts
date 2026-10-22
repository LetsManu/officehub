/**
 * SFrame (RFC 9605) for the media of end-to-end encrypted meetings, keyed from MLS (RFC 9605 section 5.2).
 *
 * Cipher suite AES_128_GCM_SHA256_128. Every frame carries an SFrame header (key id and counter) and the
 * ciphertext with its tag. The key id says whose key and which MLS epoch: `KID = leaf index << 8 | epoch % 256`,
 * so each person encrypts with a key of their own. As in Jitsi, the first bytes of a frame (the VP8 payload
 * descriptor, the Opus TOC byte) stay readable so the browser can still packetise it; they are authenticated as
 * part of the associated data, so nobody can change them unnoticed.
 */

export const SUITE = 0x0004 // AES_128_GCM_SHA256_128
const NH = 32 // hash length
const NK = 16 // key length
const NN = 12 // nonce length
const EPOCH_BITS = 8

/** Bytes left readable at the start of a frame (as lib-jitsi-meet does). */
export function clearBytes(type: string | undefined): number {
  if (type === 'key') return 10
  if (type === 'delta') return 3
  return 1 // audio
}

export function kidOf(leaf: number, epoch: number): bigint {
  return (BigInt(leaf) << BigInt(EPOCH_BITS)) | BigInt(epoch % (1 << EPOCH_BITS))
}

export function splitKid(kid: bigint): { leaf: number; epochBits: number } {
  return { leaf: Number(kid >> BigInt(EPOCH_BITS)), epochBits: Number(kid & BigInt((1 << EPOCH_BITS) - 1)) }
}

function minimalBytes(value: bigint): Uint8Array {
  const out: number[] = []
  let v = value
  do {
    out.unshift(Number(v & 0xffn))
    v >>= 8n
  } while (v > 0n)
  return new Uint8Array(out)
}

/** The SFrame header: a config byte |X|K|Y|C| and, when they do not fit in three bits, KID and CTR. */
export function encodeHeader(kid: bigint, ctr: bigint): Uint8Array {
  const parts: number[] = []
  let config = 0
  const extra: number[] = []
  if (kid < 8n) {
    config |= Number(kid) << 4
  } else {
    const bytes = minimalBytes(kid)
    config |= 0x80 | ((bytes.length - 1) << 4)
    extra.push(...bytes)
  }
  if (ctr < 8n) {
    config |= Number(ctr)
  } else {
    const bytes = minimalBytes(ctr)
    config |= 0x08 | (bytes.length - 1)
    extra.push(...bytes)
  }
  parts.push(config, ...extra)
  // KID bytes come before CTR bytes; `extra` was filled in that order
  return new Uint8Array(parts)
}

function readBig(data: Uint8Array, at: number, length: number): bigint {
  let v = 0n
  for (let i = 0; i < length; i++) v = (v << 8n) | BigInt(data[at + i] ?? 0)
  return v
}

export function decodeHeader(data: Uint8Array, at = 0): { kid: bigint; ctr: bigint; length: number } | null {
  if (data.length <= at) return null
  const config = data[at]
  let pos = at + 1
  let kid: bigint
  let ctr: bigint
  if (config & 0x80) {
    const n = ((config >> 4) & 0x07) + 1
    if (data.length < pos + n) return null
    kid = readBig(data, pos, n)
    pos += n
  } else {
    kid = BigInt((config >> 4) & 0x07)
  }
  if (config & 0x08) {
    const n = (config & 0x07) + 1
    if (data.length < pos + n) return null
    ctr = readBig(data, pos, n)
    pos += n
  } else {
    ctr = BigInt(config & 0x07)
  }
  return { kid, ctr, length: pos - at }
}

const subtle = globalThis.crypto.subtle
const text = new TextEncoder()

function be(value: bigint | number, length: number): Uint8Array {
  const out = new Uint8Array(length)
  let v = BigInt(value)
  for (let i = length - 1; i >= 0; i--) {
    out[i] = Number(v & 0xffn)
    v >>= 8n
  }
  return out
}

function concat(...parts: Uint8Array[]): Uint8Array {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0))
  let at = 0
  for (const p of parts) {
    out.set(p, at)
    at += p.length
  }
  return out
}

/** HKDF-Expand for at most one hash block (all lengths here are ≤ 32). */
async function expand(prk: Uint8Array, info: Uint8Array, length: number): Promise<Uint8Array> {
  const key = await subtle.importKey('raw', prk as BufferSource, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
  const block = new Uint8Array(await subtle.sign('HMAC', key, concat(info, new Uint8Array([1])) as BufferSource))
  return block.slice(0, length)
}

async function extract(salt: Uint8Array, ikm: Uint8Array): Promise<Uint8Array> {
  const key = await subtle.importKey('raw', (salt.length ? salt : new Uint8Array(NH)) as BufferSource, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
  return new Uint8Array(await subtle.sign('HMAC', key, ikm as BufferSource))
}

/** One sender's key in one epoch, from the epoch's SFrame secret (exported from MLS). */
export interface SenderKey {
  key: CryptoKey
  salt: Uint8Array
}

export async function senderKey(epochSecret: Uint8Array, leaf: number, epoch: number): Promise<SenderKey> {
  // RFC 9605 5.2: sender_base_key = HKDF-Expand(sframe_epoch_secret, encode_big_endian(index, 4), AEAD.Nh)
  const base = await expand(epochSecret, be(leaf, 4), NH)
  // RFC 9605 4.4.2: key and salt for this KID
  const kid = be(kidOf(leaf, epoch), 8)
  const suite = be(SUITE, 2)
  const secret = await extract(new Uint8Array(), base)
  const raw = await expand(secret, concat(text.encode('SFrame 1.0 Secret key '), kid, suite), NK)
  const salt = await expand(secret, concat(text.encode('SFrame 1.0 Secret salt '), kid, suite), NN)
  const key = await subtle.importKey('raw', raw as BufferSource, 'AES-GCM', false, ['encrypt', 'decrypt'])
  return { key, salt }
}

function nonce(salt: Uint8Array, ctr: bigint): Uint8Array {
  const c = be(ctr, NN)
  return salt.map((b, i) => b ^ c[i])
}

/** Encrypt one frame: readable prefix | SFrame header | ciphertext + tag. */
export async function seal(frame: Uint8Array, clear: number, sender: SenderKey, kid: bigint, ctr: bigint): Promise<Uint8Array> {
  const prefix = frame.subarray(0, Math.min(clear, frame.length))
  const header = encodeHeader(kid, ctr)
  const aad = concat(prefix, header)
  const ct = new Uint8Array(
    await subtle.encrypt({ name: 'AES-GCM', iv: nonce(sender.salt, ctr) as BufferSource, additionalData: aad as BufferSource, tagLength: 128 }, sender.key, frame.subarray(prefix.length) as BufferSource),
  )
  return concat(prefix, header, ct)
}

/** Read the header of a sealed frame (after its readable prefix). */
export function peek(data: Uint8Array, clear: number): { kid: bigint; ctr: bigint; length: number } | null {
  return decodeHeader(data, Math.min(clear, data.length))
}

export async function open(data: Uint8Array, clear: number, sender: SenderKey): Promise<Uint8Array | null> {
  const at = Math.min(clear, data.length)
  const header = decodeHeader(data, at)
  if (!header) return null
  const aad = data.subarray(0, at + header.length)
  try {
    const plain = new Uint8Array(
      await subtle.decrypt({ name: 'AES-GCM', iv: nonce(sender.salt, header.ctr) as BufferSource, additionalData: aad as BufferSource, tagLength: 128 }, sender.key, data.subarray(at + header.length) as BufferSource),
    )
    return concat(data.subarray(0, at), plain)
  } catch {
    return null
  }
}
