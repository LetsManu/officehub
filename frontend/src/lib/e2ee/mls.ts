/**
 * End-to-end encryption for a meeting: this browser's part of the meeting's MLS group (RFC 9420, ts-mls).
 *
 * The browser makes its own keys; OfficeHub only passes on public key packages, commits, welcomes and ciphertext
 * (backend services/mls.py). Whoever has been in the group longest – the leader – adds newcomers and removes
 * people who left. After every change (a new epoch) all members derive the same secrets: one for audio and video
 * (SFrame, sframe.worker.ts, or the Jitsi server's frame encryption) and a security code that everyone can compare
 * aloud – when it is the same for all, nobody else is listening in.
 */

import { reactive } from 'vue'
import {
  acceptAll,
  createApplicationMessage,
  createCommit,
  createGroup,
  decodeMlsMessage,
  emptyPskIndex,
  encodeMlsMessage,
  generateKeyPackage,
  getCiphersuiteFromName,
  getCiphersuiteImpl,
  defaultCapabilities,
  defaultLifetime,
  joinGroup,
  mlsExporter,
  processMessage,
  processPrivateMessage,
  type CiphersuiteImpl,
  type ClientState,
  type KeyPackage,
  type PrivateKeyPackage,
  type Proposal,
} from 'ts-mls'

const SUITE = 'MLS_128_DHKEMX25519_AES128GCM_SHA256_Ed25519'

export interface E2eeInfo {
  token: string
  signal: string
}

interface RosterMember {
  id: string
  who: string
  name: string
  in_group: boolean
  key_package: string
}

interface Roster {
  version: number
  epoch: number | null
  leader: string | null
  members: RosterMember[]
  gone: string[]
}

interface Identity {
  m: string // member id at OfficeHub's delivery service
  w: string // the person (user id or guest-…)
  n: string // their name
}

export type E2eeStatus = 'connecting' | 'secure' | 'failed'

export interface E2eeKeys {
  epoch: number
  /** RFC 9605 5.2: sframe_epoch_secret = MLS-Exporter("SFrame 1.0 Secret", "", Nh) */
  sframe: Uint8Array
  /** A key for the Jitsi server's own frame encryption (one for everyone, per epoch). */
  shared: Uint8Array
  leaf: number
}

export interface Sender {
  who: string
  name: string
}

const toB64 = (b: Uint8Array) => btoa(String.fromCharCode(...b))
const fromB64 = (s: string) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0))
const text = new TextEncoder()

/** The security code everyone compares: 20 digits from the epoch authenticator, in groups of five. */
export function securityCode(authenticator: Uint8Array): string {
  let n = 0n
  for (const b of authenticator.subarray(0, 9)) n = (n << 8n) | BigInt(b)
  const digits = (n % 10n ** 20n).toString().padStart(20, '0')
  return digits.match(/.{5}/g)!.join(' ')
}

function identityOf(tree: ClientState['ratchetTree'], leaf: number): Identity | null {
  const node = tree[leaf * 2]
  if (!node || node.nodeType !== 'leaf' || node.leaf.credential.credentialType !== 'basic') return null
  try {
    return JSON.parse(new TextDecoder().decode(node.leaf.credential.identity)) as Identity
  } catch {
    return null
  }
}

export class E2eeGroup {
  readonly view = reactive({ status: 'connecting' as E2eeStatus, code: '', epoch: -1, members: [] as Sender[] })
  private impl!: CiphersuiteImpl
  private memberId = ''
  private after = 0
  private state: ClientState | null = null
  private own: { publicPackage: KeyPackage; privatePackage: PrivateKeyPackage } | null = null
  private roster: Roster | null = null
  private running = false
  private busy = false
  /** Rosters older than what our own last step produced are stale: they would undo it. */
  private seenVersion = 0
  private chain: Promise<void> = Promise.resolve()

  constructor(
    private info: E2eeInfo,
    private onKeys: (keys: E2eeKeys) => void,
    private onMessage: (payload: Record<string, unknown>, from: Sender) => void,
  ) {}

  private async call<T>(path: string, body?: Record<string, unknown>): Promise<T> {
    const response = await fetch(`${this.info.signal}/${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Meeting-Token': this.info.token, 'X-Requested-With': 'OfficeHub' },
      body: JSON.stringify({ member_id: this.memberId, ...body }),
    })
    if (!response.ok) {
      const error = new Error(String(response.status)) as Error & { status: number }
      error.status = response.status
      throw error
    }
    return response.status === 204 ? (undefined as T) : ((await response.json()) as T)
  }

  async start(): Promise<void> {
    this.impl = await getCiphersuiteImpl(getCiphersuiteFromName(SUITE))
    const hello = await this.call<{ member_id: string; roster: Roster }>('hello')
    this.memberId = hello.member_id
    this.running = true
    this.queue(() => this.onRoster(hello.roster))
    void this.loop()
  }

  stop() {
    this.running = false
    if (this.memberId) {
      fetch(`${this.info.signal}/bye`, {
        method: 'POST',
        keepalive: true,
        headers: { 'Content-Type': 'application/json', 'X-Meeting-Token': this.info.token, 'X-Requested-With': 'OfficeHub' },
        body: JSON.stringify({ member_id: this.memberId }),
      }).catch(() => undefined)
    }
  }

  /** Encrypt something for the others in the group (chat, reaction, whiteboard). */
  async seal(payload: Record<string, unknown>): Promise<boolean> {
    if (!this.state) return false
    const result = await createApplicationMessage(this.state, text.encode(JSON.stringify({ ...payload, from: this.memberId })), this.impl)
    this.state = result.newState
    const message = encodeMlsMessage({ privateMessage: result.privateMessage, wireformat: 'mls_private_message', version: 'mls10' })
    await this.call('app', { epoch: Number(this.state.groupContext.epoch), message: toB64(message) })
    return true
  }

  /** Messages are handled one after another, in the order the server gives them. */
  private queue(task: () => Promise<void>) {
    this.chain = this.chain.then(task).catch((e) => {
      console.warn('end-to-end encryption:', e)
      return this.recover()
    })
  }

  private async loop() {
    while (this.running) {
      try {
        const { messages } = await this.call<{ messages: { seq: number; type: string; data: Record<string, unknown> }[] }>('poll', { after: this.after })
        for (const m of messages) {
          this.after = Math.max(this.after, m.seq)
          this.queue(() => this.onEvent(m.type, m.data))
        }
      } catch (e) {
        if ((e as { status?: number }).status === 410 || (e as { status?: number }).status === 403) {
          this.view.status = 'failed'
          this.running = false
          return
        }
        await new Promise((r) => setTimeout(r, 2000))
      }
    }
  }

  private async onEvent(type: string, data: Record<string, unknown>) {
    if (type === 'roster') return this.onRoster(data as unknown as Roster)
    if (type === 'removed') {
      this.view.status = 'failed'
      this.running = false
      return
    }
    const message = decodeMlsMessage(fromB64(String(data.message)), 0)?.[0]
    if (!message) return
    if (type === 'welcome' && message.wireformat === 'mls_welcome' && this.own) {
      this.state = await joinGroup(message.welcome, this.own.publicPackage, this.own.privatePackage, emptyPskIndex, this.impl)
      this.own = null
      await this.changed()
    } else if (type === 'commit' && this.state && (message.wireformat === 'mls_private_message' || message.wireformat === 'mls_public_message')) {
      const result = await processMessage(message, this.state, emptyPskIndex, acceptAll, this.impl)
      this.state = result.newState
      await this.changed()
    } else if (type === 'app' && this.state && message.wireformat === 'mls_private_message') {
      const result = await processPrivateMessage(this.state, message.privateMessage, emptyPskIndex, this.impl)
      this.state = result.newState
      if (result.kind !== 'applicationMessage') return
      const payload = JSON.parse(new TextDecoder().decode(result.message)) as Record<string, unknown>
      const from = this.roster?.members.find((m) => m.id === payload.from)
      this.onMessage(payload, { who: from?.who ?? '', name: from?.name ?? '' })
    }
  }

  private async onRoster(roster: Roster) {
    if (roster.version < this.seenVersion) return
    this.seenVersion = roster.version
    this.roster = roster
    const me = roster.members.find((m) => m.id === this.memberId)
    if (!me) return
    if (!me.in_group && this.state) {
      // The group was started anew (everyone else left) or we were taken out: start again
      this.state = null
      this.view.status = 'connecting'
    }
    if (!this.state) {
      if (roster.epoch === null) {
        const { created, version } = await this.call<{ created: boolean; version: number }>('create')
        this.seenVersion = Math.max(this.seenVersion, version)
        if (created) {
          const own = await this.keyPackage()
          this.state = await createGroup(crypto.getRandomValues(new Uint8Array(16)), own.publicPackage, own.privatePackage, [], this.impl)
          this.own = null
          await this.changed()
        }
        return
      }
      if (!me.key_package && !this.own) {
        const own = await this.keyPackage()
        const { version } = await this.call<{ version: number }>('publish', { key_package: toB64(encodeMlsMessage({ keyPackage: own.publicPackage, wireformat: 'mls_key_package', version: 'mls10' })) })
        this.seenVersion = Math.max(this.seenVersion, version)
      }
      return
    }
    if (roster.leader === this.memberId) await this.lead()
  }

  private async keyPackage() {
    const me = this.roster?.members.find((m) => m.id === this.memberId)
    const identity: Identity = { m: this.memberId, w: me?.who ?? '', n: me?.name ?? '' }
    this.own = await generateKeyPackage({ credentialType: 'basic', identity: text.encode(JSON.stringify(identity)) }, defaultCapabilities(), defaultLifetime, [], this.impl)
    return this.own
  }

  /** The leader adds whoever waits and removes whoever left, in one commit. */
  private async lead() {
    if (this.busy || !this.state || !this.roster) return
    const state = this.state
    const roster = this.roster
    const proposals: Proposal[] = []
    const added: string[] = []
    const removed: string[] = []
    for (const m of roster.members) {
      if (m.in_group || !m.key_package || m.id === this.memberId) continue
      const decoded = decodeMlsMessage(fromB64(m.key_package), 0)?.[0]
      if (!decoded || decoded.wireformat !== 'mls_key_package') continue
      // The key package must belong to the member the server says it does
      const credential = decoded.keyPackage.leafNode.credential
      if (credential.credentialType !== 'basic') continue
      let identity: Identity | null = null
      try {
        identity = JSON.parse(new TextDecoder().decode(credential.identity)) as Identity
      } catch {
        continue
      }
      if (identity.m !== m.id || identity.w !== m.who) continue
      proposals.push({ proposalType: 'add', add: { keyPackage: decoded.keyPackage } })
      added.push(m.id)
    }
    for (let leaf = 0; leaf * 2 < state.ratchetTree.length; leaf++) {
      const identity = identityOf(state.ratchetTree, leaf)
      if (identity && roster.gone.includes(identity.m)) {
        proposals.push({ proposalType: 'remove', remove: { removed: leaf } })
        removed.push(identity.m)
      }
    }
    // Members the server no longer lists are not removed here unless it says they are gone
    if (!proposals.length) return
    this.busy = true
    try {
      const result = await createCommit({ state, cipherSuite: this.impl }, { extraProposals: proposals, ratchetTreeExtension: true })
      const commit = toB64(encodeMlsMessage(result.commit))
      const welcome = result.welcome ? toB64(encodeMlsMessage({ welcome: result.welcome, wireformat: 'mls_welcome', version: 'mls10' })) : ''
      const { version } = await this.call<{ version: number }>('commit', { epoch: Number(state.groupContext.epoch), message: commit, welcome, added, removed })
      this.seenVersion = Math.max(this.seenVersion, version)
      this.state = result.newState
      await this.changed()
    } catch (e) {
      if ((e as { status?: number }).status !== 409) throw e
      // Someone else's commit came first: it arrives through the poll, then the roster asks again
    } finally {
      this.busy = false
    }
  }

  /** A new epoch: new media keys, a new security code and the list of who holds the keys. */
  private async changed() {
    const state = this.state
    if (!state) return
    const epoch = Number(state.groupContext.epoch)
    const secret = state.keySchedule.exporterSecret
    const sframe = await mlsExporter(secret, 'SFrame 1.0 Secret', new Uint8Array(), 32, this.impl)
    const shared = await mlsExporter(secret, 'OfficeHub Jitsi media', new Uint8Array(), 16, this.impl)
    const leaf = state.privatePath.leafIndex
    const members: Sender[] = []
    for (let i = 0; i * 2 < state.ratchetTree.length; i++) {
      const identity = identityOf(state.ratchetTree, i)
      if (identity) members.push({ who: identity.w, name: identity.n })
    }
    this.view.epoch = epoch
    this.view.code = securityCode(state.keySchedule.epochAuthenticator)
    this.view.members = members
    this.view.status = 'secure'
    this.onKeys({ epoch, sframe, shared, leaf })
    if (this.roster?.leader === this.memberId) await this.lead()
  }

  /** Something could not be read (a commit we missed): leave the group and be added again. */
  private async recover() {
    if (!this.running) return
    this.state = null
    this.own = null
    this.view.status = 'connecting'
    await this.call('rejoin').catch(() => undefined)
  }
}
