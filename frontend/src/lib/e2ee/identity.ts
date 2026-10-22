/**
 * Who is really who in an end-to-end encrypted meeting.
 *
 * Every browser has its own identity key (ECDSA P-256). The private part is made here, kept in IndexedDB and cannot
 * be read out (not even by this page); OfficeHub only gets the public part (backend services/keys.py). A person's
 * first device is their root, every further one is signed by one of their confirmed devices. In a meeting each
 * browser signs its MLS key with its device key, and everyone checks that signature, the person's chain of devices
 * and the root against what they remember (trust on first use) or have checked in person (a signed note). OfficeHub
 * can hand out wrong keys, but never make them pass these checks.
 */

import { api, ApiError } from '../api'

export interface DeviceRecord {
  id: number
  public_key: string
  name: string
  root: boolean
  signed_by: number | null
  signature: string
  pending: boolean
  created_at?: string
}

interface VerificationRecord {
  subject_id: number
  root: string
  signed_by: number
  signature: string
}

export interface MyKeys {
  devices: DeviceRecord[]
  verifications: VerificationRecord[]
  policy: 'warn' | 'strict'
}

/** This browser's device: its id at OfficeHub and the key pair (private part not readable). */
export interface Device {
  userId: string
  id: number
  publicKey: string
  keys: CryptoKeyPair
  pending: boolean
  root: boolean
}

/** How much we can trust a member of the group, best first. */
export type Trust = 'self' | 'verified' | 'known' | 'new' | 'guest' | 'unconfirmed' | 'changed' | 'forged'

export const toB64 = (b: Uint8Array) => btoa(String.fromCharCode(...b))
export const fromB64 = (s: string) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0))
const utf8 = new TextEncoder()
const subtle = () => globalThis.crypto.subtle
const ALG = { name: 'ECDSA', namedCurve: 'P-256' } as const
const SIGN = { name: 'ECDSA', hash: 'SHA-256' } as const

// What is signed; each kind with its own label so one signature can never stand for another
export const deviceStatement = (userId: string, publicKey: string) => utf8.encode(`OfficeHub device v1\0${userId}\0${publicKey}`)
export const leafStatement = (who: string, leafKey: string) => utf8.encode(`OfficeHub MLS leaf v1\0${who}\0${leafKey}`)
export const verifiedStatement = (subjectId: string, root: string) => utf8.encode(`OfficeHub verified v1\0${subjectId}\0${root}`)

export async function sign(keys: CryptoKeyPair, message: Uint8Array): Promise<string> {
  return toB64(new Uint8Array(await subtle().sign(SIGN, keys.privateKey, message as BufferSource)))
}

const imported = new Map<string, Promise<CryptoKey | null>>()

function publicKeyOf(spki: string): Promise<CryptoKey | null> {
  let key = imported.get(spki)
  if (!key) {
    key = subtle().importKey('spki', fromB64(spki) as BufferSource, ALG, true, ['verify']).catch(() => null)
    imported.set(spki, key)
  }
  return key
}

export async function verify(spki: string, message: Uint8Array, signature: string): Promise<boolean> {
  try {
    const key = await publicKeyOf(spki)
    return !!key && (await subtle().verify(SIGN, key, fromB64(signature) as BufferSource, message as BufferSource))
  } catch {
    return false
  }
}

/** SHA-256 of a public key, as hex: what identifies a person's root key. */
export async function fingerprint(spki: string): Promise<string> {
  const digest = new Uint8Array(await subtle().digest('SHA-256', fromB64(spki) as BufferSource))
  return Array.from(digest, (b) => b.toString(16).padStart(2, '0')).join('')
}

/** The security number people compare: 30 digits in groups of five, from the root key's fingerprint. */
export function securityNumber(fp: string): string {
  const groups: string[] = []
  for (let i = 0; i < 6; i++) {
    const n = parseInt(fp.slice(i * 10, i * 10 + 10), 16) % 100000
    groups.push(String(n).padStart(5, '0'))
  }
  return groups.join(' ')
}

/** The short code both screens show when a new device is confirmed. */
export async function deviceCode(publicKey: string): Promise<string> {
  const fp = await fingerprint(publicKey)
  return String(parseInt(fp.slice(0, 12), 16) % 1000000).padStart(6, '0').replace(/(\d{3})(\d{3})/, '$1 $2')
}

/** What a QR code for a person's security number contains. */
export const qrText = (userId: string, fp: string) => `OFFICEHUB-KEY:1:${userId}:${fp}`

export function parseQr(text: string): { userId: string; fp: string } | null {
  const m = /^OFFICEHUB-KEY:1:(\d+):([0-9a-f]{64})$/.exec(text.trim())
  return m ? { userId: m[1], fp: m[2] } : null
}

// ---------- storage (IndexedDB): this browser's keys and the roots it has seen ----------

const DB_NAME = 'officehub-keys'

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1)
    request.onupgradeneeded = () => {
      request.result.createObjectStore('devices')
      request.result.createObjectStore('pins')
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

async function idb<T>(store: string, mode: IDBTransactionMode, run: (s: IDBObjectStore) => IDBRequest): Promise<T> {
  const db = await openDb()
  try {
    return await new Promise<T>((resolve, reject) => {
      const request = run(db.transaction(store, mode).objectStore(store))
      request.onsuccess = () => resolve(request.result as T)
      request.onerror = () => reject(request.error)
    })
  } finally {
    db.close()
  }
}

interface Stored {
  id: number
  publicKey: string
  keys: CryptoKeyPair
}

export function identitySupported(): boolean {
  return typeof indexedDB !== 'undefined' && !!globalThis.crypto?.subtle
}

function deviceName(): string {
  const ua = navigator.userAgent
  const browser = /Edg\//.test(ua) ? 'Edge' : /Firefox\//.test(ua) ? 'Firefox' : /Chrome\//.test(ua) ? 'Chrome' : /Safari\//.test(ua) ? 'Safari' : 'Browser'
  const system = /Android/.test(ua) ? 'Android' : /iPhone|iPad/.test(ua) ? 'iOS' : /Windows/.test(ua) ? 'Windows' : /Mac OS/.test(ua) ? 'macOS' : /Linux/.test(ua) ? 'Linux' : ''
  return system ? `${browser} · ${system}` : browser
}

async function newKeys(userId: string): Promise<{ keys: CryptoKeyPair; publicKey: string; body: Record<string, unknown> }> {
  // Not extractable: the private key can be used for signing, but never read out
  const keys = (await subtle().generateKey(ALG, false, ['sign', 'verify'])) as CryptoKeyPair
  const publicKey = toB64(new Uint8Array(await subtle().exportKey('spki', keys.publicKey)))
  const signature = await sign(keys, deviceStatement(userId, publicKey))
  return { keys, publicKey, body: { public_key: publicKey, name: deviceName(), signature } }
}

let current: Promise<Device | null> | null = null
let currentUser = ''
let loading = false

/** This browser's device for the signed-in person: made and registered the first time. `fresh` asks OfficeHub
 * again (confirmed in the meantime?); a load already under way is shared, so a new browser registers only once. */
export function myDevice(userId: string, fresh = false): Promise<Device | null> {
  if (!current || currentUser !== userId || (fresh && !loading)) {
    currentUser = userId
    loading = true
    current = loadDevice(userId)
      .catch((e) => {
        console.warn('device key:', e)
        current = null
        return null
      })
      .finally(() => (loading = false))
  }
  return current
}

async function loadDevice(userId: string): Promise<Device | null> {
  if (!identitySupported()) return null
  const mine = await api.get<MyKeys>('/api/keys/me')
  const stored = await idb<Stored | undefined>('devices', 'readonly', (s) => s.get(userId))
  const record = stored && mine.devices.find((d) => d.id === stored.id && d.public_key === stored.publicKey)
  if (stored && record) return { userId, id: record.id, publicKey: record.public_key, keys: stored.keys, pending: record.pending, root: record.root }
  // New here (or this device was removed / everything was started anew elsewhere): register a new key
  const made = await newKeys(userId)
  const added = await api.post<DeviceRecord>('/api/keys/devices', made.body)
  await idb('devices', 'readwrite', (s) => s.put({ id: added.id, publicKey: made.publicKey, keys: made.keys } satisfies Stored, userId))
  return { userId, id: added.id, publicKey: made.publicKey, keys: made.keys, pending: added.pending, root: added.root }
}

/** No confirmed device left: this browser becomes the person's new first device. */
export async function startAnew(userId: string): Promise<Device> {
  const made = await newKeys(userId)
  const added = await api.post<DeviceRecord>('/api/keys/reset', made.body)
  await idb('devices', 'readwrite', (s) => s.put({ id: added.id, publicKey: made.publicKey, keys: made.keys } satisfies Stored, userId))
  current = Promise.resolve({ userId, id: added.id, publicKey: made.publicKey, keys: made.keys, pending: false, root: true })
  currentUser = userId
  return current as Promise<Device>
}

/** A key for a guest: only for this visit, never stored. */
export async function guestDevice(who: string): Promise<Device> {
  const made = await newKeys(who)
  return { userId: who, id: 0, publicKey: made.publicKey, keys: made.keys, pending: true, root: false }
}

/** Confirm one of my new devices from this one (after comparing the code on both screens). */
export async function approve(me: Device, device: DeviceRecord): Promise<void> {
  const signature = await sign(me.keys, deviceStatement(me.userId, device.public_key))
  await api.post(`/api/keys/devices/${device.id}/approve`, { signed_by: me.id, signature })
}

// ---------- checking a person's devices ----------

export interface Chain {
  root: string // fingerprint of the root key
  rootKey: string
  confirmed: Set<string> // public keys signed down from the root
  pending: Set<string>
}

/** The root and everything properly signed down from it. Null when there is no single root with a valid signature. */
export async function checkChain(userId: string, devices: DeviceRecord[]): Promise<Chain | null> {
  const roots = devices.filter((d) => d.root)
  if (roots.length !== 1) return null
  const root = roots[0]
  if (!(await verify(root.public_key, deviceStatement(userId, root.public_key), root.signature))) return null
  const confirmed = new Map<number, string>([[root.id, root.public_key]])
  let grew = true
  while (grew) {
    grew = false
    for (const d of devices) {
      if (confirmed.has(d.id) || d.signed_by === null || !confirmed.has(d.signed_by)) continue
      if (await verify(confirmed.get(d.signed_by)!, deviceStatement(userId, d.public_key), d.signature)) {
        confirmed.set(d.id, d.public_key)
        grew = true
      }
    }
  }
  const pending = new Set(devices.filter((d) => d.pending).map((d) => d.public_key))
  return { root: await fingerprint(root.public_key), rootKey: root.public_key, confirmed: new Set(confirmed.values()), pending }
}

// ---------- what I know about others: checked in person (signed, on the server) and seen before (here) ----------

export class Trustbook {
  private verified = new Map<string, string>() // subject → root fingerprint I checked
  private pins = new Map<string, string>() // subject → root fingerprint seen first
  private fresh = new Set<string>() // first seen while this page is open: still "new"

  private constructor(private me: string) {}

  static async load(me: string): Promise<Trustbook> {
    const book = new Trustbook(me)
    if (!/^\d+$/.test(me) || !identitySupported()) return book
    try {
      const mine = await api.get<MyKeys>('/api/keys/me')
      const chain = await checkChain(me, mine.devices)
      const byId = new Map(mine.devices.map((d) => [d.id, d.public_key]))
      for (const v of mine.verifications) {
        const key = byId.get(v.signed_by)
        // Only notes signed by one of my own confirmed devices count
        if (!key || !chain?.confirmed.has(key)) continue
        if (await verify(key, verifiedStatement(String(v.subject_id), v.root), v.signature)) book.verified.set(String(v.subject_id), v.root)
      }
      const pins = await idb<{ key: string; root: string }[]>('pins', 'readonly', (s) => s.getAll())
      for (const p of pins ?? []) if (p.key.startsWith(`${me}:`)) book.pins.set(p.key.slice(me.length + 1), p.root)
    } catch (e) {
      console.warn('trust:', e)
    }
    return book
  }

  isVerified(subject: string, root: string): boolean {
    return this.verified.get(subject) === root
  }

  /** How a person's root compares with what I checked or saw before; the first time it is remembered. */
  async judge(subject: string, root: string): Promise<'verified' | 'known' | 'new' | 'changed'> {
    const checked = this.verified.get(subject)
    if (checked) return checked === root ? 'verified' : 'changed'
    const pinned = this.pins.get(subject)
    if (pinned) return pinned !== root ? 'changed' : this.fresh.has(subject) ? 'new' : 'known'
    await this.pin(subject, root)
    this.fresh.add(subject)
    return 'new'
  }

  async pin(subject: string, root: string): Promise<void> {
    this.pins.set(subject, root)
    const key = `${this.me}:${subject}`
    await idb('pins', 'readwrite', (s) => s.put({ key, root }, key)).catch(() => undefined)
  }

  /** "The number matches": a signed note, so it holds on all my devices; also remembered here. */
  async confirm(device: Device, subject: string, root: string): Promise<void> {
    const signature = await sign(device.keys, verifiedStatement(subject, root))
    await api.put('/api/keys/verifications', { subject_id: Number(subject), root, signed_by: device.id, signature })
    this.verified.set(subject, root)
    await this.pin(subject, root)
  }

  async unconfirm(subject: string): Promise<void> {
    await api.delete(`/api/keys/verifications/${subject}`)
    this.verified.delete(subject)
  }
}

export { ApiError }
