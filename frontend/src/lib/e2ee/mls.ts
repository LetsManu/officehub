/**
 * End-to-end encryption for a meeting: this browser's part of the meeting's MLS group (RFC 9420, ts-mls).
 *
 * The browser makes its own keys; OfficeHub only passes on public key packages, commits, welcomes and ciphertext
 * (backend services/mls.py). Whoever has been in the group longest – the leader – adds newcomers and removes
 * people who left. After every change (a new epoch) all members derive the same secrets: one for audio and video
 * (SFrame, sframe.worker.ts, or the Jitsi server's frame encryption) and a security code that everyone can compare
 * aloud – when it is the same for all, nobody else is listening in.
 *
 * Who is who: every browser signs its MLS key with its device key (identity.ts), and every member checks that
 * signature, the person's chain of devices and their root against what it checked or saw before. A key that does
 * not pass is never added, and finding one in the group stops the meeting here. Under the "confirmed people only"
 * rule (policy 'strict') guests, devices nobody confirmed and changed keys are kept out as well.
 */

import { reactive } from 'vue'
import { checkChain, leafStatement, sign, Trustbook, verify, type Chain, type Device, type DeviceRecord, type Trust } from './identity'
import {
  acceptAll,
  createApplicationMessage,
  createCommit,
  createGroup,
  decodeMlsMessage,
  emptyPskIndex,
  encodeMlsMessage,
  generateKeyPackageWithKey,
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
  /** 'strict': only confirmed people (no guests, no unconfirmed devices, no changed keys) */
  policy?: 'warn' | 'strict'
}

/** Who this browser is and what it knows about others (identity.ts). */
export interface E2eeIdentity {
  device: Device
  book: Trustbook
}

interface RosterMember {
  id: string
  who: string
  name: string
  in_group: boolean
  key_package: string
  keys?: DeviceRecord[]
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
  k: string // their device's public key (identity.ts)
  s: string // that device's signature over the person and this MLS key
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

export interface GroupMember extends Sender {
  trust: Trust
}

/** Never let in, whatever the rule */
const FORGED: Trust[] = ['forged']
/** Kept out under the "confirmed people only" rule */
const STRICT: Trust[] = ['forged', 'guest', 'unconfirmed', 'changed']

const toB64 = (b: Uint8Array) => btoa(String.fromCharCode(...b))
const fromB64 = (s: string) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0))

function readIdentity(credential: { credentialType: string; identity?: Uint8Array }): Identity | null {
  if (credential.credentialType !== 'basic' || !credential.identity) return null
  try {
    return JSON.parse(new TextDecoder().decode(credential.identity)) as Identity
  } catch {
    return null
  }
}
const text = new TextEncoder()

/** The security code everyone compares: 20 digits from the epoch authenticator, in groups of five. */
export function securityCode(authenticator: Uint8Array): string {
  let n = 0n
  for (const b of authenticator.subarray(0, 9)) n = (n << 8n) | BigInt(b)
  const digits = (n % 10n ** 20n).toString().padStart(20, '0')
  return digits.match(/.{5}/g)!.join(' ')
}

function leafOf(tree: ClientState['ratchetTree'], leaf: number): { identity: Identity | null; key: Uint8Array } | null {
  const node = tree[leaf * 2]
  if (!node || node.nodeType !== 'leaf') return null
  return { identity: readIdentity(node.leaf.credential as { credentialType: string; identity?: Uint8Array }), key: node.leaf.signaturePublicKey }
}

function identityOf(tree: ClientState['ratchetTree'], leaf: number): Identity | null {
  return leafOf(tree, leaf)?.identity ?? null
}

export class E2eeGroup {
  readonly view = reactive({
    status: 'connecting' as E2eeStatus,
    code: '',
    epoch: -1,
    members: [] as GroupMember[],
    strict: false,
    /** Why it stopped: e2ee_forged (someone's key is not theirs) or e2ee_unconfirmed_member (strict rule) */
    problem: '',
    problemName: '',
  })
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
  /** Each person's device keys as last seen in a roster, and what they amount to */
  private keysOf = new Map<string, DeviceRecord[]>()
  private chains = new Map<string, { at: string; chain: Promise<Chain | null> }>()

  constructor(
    private info: E2eeInfo,
    private identity: E2eeIdentity,
    private onKeys: (keys: E2eeKeys) => void,
    private onMessage: (payload: Record<string, unknown>, from: Sender) => void,
    private onFail: (problem: string, name: string) => void = () => undefined,
  ) {
    this.view.strict = info.policy === 'strict'
  }

  private chainOf(who: string): Promise<Chain | null> {
    const devices = this.keysOf.get(who) ?? []
    const at = JSON.stringify(devices)
    const known = this.chains.get(who)
    if (known && known.at === at) return known.chain
    const chain = checkChain(who, devices)
    this.chains.set(who, { at, chain })
    return chain
  }

  /** How far a member's MLS key can be trusted to be theirs (see identity.ts). */
  private async trustOf(id: Identity | null, leafKey: Uint8Array): Promise<Trust> {
    if (!id?.k || !id.s || !id.w) return 'forged'
    if (!(await verify(id.k, leafStatement(id.w, toB64(leafKey)), id.s))) return 'forged'
    const me = this.identity.device
    if (id.w === me.userId && id.k === me.publicKey) return 'self'
    if (!/^\d+$/.test(id.w)) return 'guest'
    const chain = await this.chainOf(id.w)
    if (!chain) return 'unconfirmed'
    if (id.w === me.userId) return chain.confirmed.has(id.k) ? 'self' : 'unconfirmed'
    const judged = await this.identity.book.judge(id.w, chain.root)
    if (judged === 'changed') return 'changed'
    return chain.confirmed.has(id.k) ? judged : 'unconfirmed'
  }

  private refused(trust: Trust): boolean {
    return (this.view.strict ? STRICT : FORGED).includes(trust)
  }

  private fail(problem: string, name: string) {
    this.view.status = 'failed'
    this.view.problem = problem
    this.view.problemName = name
    this.stop()
    this.onFail(problem, name)
  }

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
    for (const m of roster.members) if (m.keys) this.keysOf.set(m.who, m.keys)
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

  /** A fresh MLS key for this group, signed with this browser's device key. */
  private async keyPackage() {
    const me = this.roster?.members.find((m) => m.id === this.memberId)
    const who = me?.who ?? ''
    const pair = await this.impl.signature.keygen()
    const device = this.identity.device
    const identity: Identity = {
      m: this.memberId,
      w: who,
      n: me?.name ?? '',
      k: device.publicKey,
      s: await sign(device.keys, leafStatement(who, toB64(pair.publicKey))),
    }
    this.own = await generateKeyPackageWithKey(
      { credentialType: 'basic', identity: text.encode(JSON.stringify(identity)) },
      defaultCapabilities(),
      defaultLifetime,
      [],
      pair,
      this.impl,
    )
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
      const leafNode = decoded.keyPackage.leafNode
      const identity = readIdentity(leafNode.credential as { credentialType: string; identity?: Uint8Array })
      if (!identity || identity.m !== m.id || identity.w !== m.who) continue
      // Only keys that are really theirs (and, under the strict rule, only confirmed people)
      if (this.refused(await this.trustOf(identity, leafNode.signaturePublicKey))) continue
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
    const members = await this.members(state)
    if (!members) return
    this.view.epoch = epoch
    this.view.code = securityCode(state.keySchedule.epochAuthenticator)
    this.view.members = members
    this.view.status = 'secure'
    this.onKeys({ epoch, sframe, shared, leaf })
    if (this.roster?.leader === this.memberId) await this.lead()
  }

  /** Everyone in the group and how far we trust them; null (and stopped) when someone must not be in it. */
  private async members(state: ClientState): Promise<GroupMember[] | null> {
    const members: GroupMember[] = []
    for (let i = 0; i * 2 < state.ratchetTree.length; i++) {
      const node = leafOf(state.ratchetTree, i)
      if (!node) continue
      const trust = await this.trustOf(node.identity, node.key)
      const name = node.identity?.n ?? '?'
      if (this.refused(trust)) {
        // Someone in the group whose key is not theirs (or not confirmed, under the strict rule): stop here
        this.fail(trust === 'forged' ? 'e2ee_forged' : 'e2ee_unconfirmed_member', name)
        return null
      }
      members.push({ who: node.identity?.w ?? '', name, trust })
    }
    return members
  }

  /** After checking someone's security number: look at everyone again. */
  async recheck(): Promise<void> {
    this.identity.book = await Trustbook.load(this.identity.device.userId)
    this.queue(async () => {
      if (!this.state) return
      const members = await this.members(this.state)
      if (members) this.view.members = members
    })
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
