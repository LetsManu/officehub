/**
 * Encrypts every outgoing audio and video frame and decrypts every incoming one (SFrame, see sframe-core.ts),
 * off the main thread. Works with both browser interfaces: RTCRtpScriptTransform (Safari, Firefox, newer
 * Chrome) and the older encoded streams (Chrome), which the page hands over.
 *
 * Keys arrive per MLS epoch. Frames for which no key is there yet are dropped, never sent or shown unencrypted.
 */

import { clearBytes, kidOf, open, peek, seal, senderKey, splitKid, type SenderKey } from './sframe-core'

interface Frame {
  data: ArrayBuffer
  type?: string
}

type Operation = 'encode' | 'decode'

interface Epoch {
  epoch: number
  secret: Uint8Array
  senders: Map<number, Promise<SenderKey>>
  at: number
}

const KEEP_EPOCHS = 4
const SWITCH_MS = 400 // give everyone a moment to reach the new epoch before sending with it

let myLeaf = -1
let sending: Epoch | null = null
const epochs: Epoch[] = []
let counter = 0n

function keyFor(e: Epoch, leaf: number): Promise<SenderKey> {
  let key = e.senders.get(leaf)
  if (!key) {
    key = senderKey(e.secret, leaf, e.epoch)
    e.senders.set(leaf, key)
  }
  return key
}

function setKeys(epoch: number, secret: ArrayBuffer, leaf: number) {
  if (epochs.some((e) => e.epoch === epoch)) return
  const e: Epoch = { epoch, secret: new Uint8Array(secret), senders: new Map(), at: Date.now() }
  epochs.unshift(e)
  epochs.splice(KEEP_EPOCHS)
  const first = sending === null
  const switchOver = () => {
    if (!sending || e.epoch > sending.epoch) {
      sending = e
      myLeaf = leaf
    }
  }
  if (first) switchOver()
  else setTimeout(switchOver, SWITCH_MS)
}

async function encode(frame: Frame, controller: TransformStreamDefaultController<Frame>) {
  const e = sending
  if (!e || myLeaf < 0 || frame.data.byteLength === 0) return
  const data = new Uint8Array(frame.data)
  const ctr = counter++
  const sealed = await seal(data, clearBytes(frame.type), await keyFor(e, myLeaf), kidOf(myLeaf, e.epoch), ctr)
  frame.data = sealed.buffer as ArrayBuffer
  controller.enqueue(frame)
}

async function decode(frame: Frame, controller: TransformStreamDefaultController<Frame>) {
  if (frame.data.byteLength === 0) return
  const data = new Uint8Array(frame.data)
  const clear = clearBytes(frame.type)
  const header = peek(data, clear)
  if (!header) return
  const { leaf, epochBits } = splitKid(header.kid)
  const e = epochs.find((x) => x.epoch % 256 === epochBits)
  if (!e) return
  const plain = await open(data, clear, await keyFor(e, leaf))
  if (!plain) return
  frame.data = plain.buffer as ArrayBuffer
  controller.enqueue(frame)
}

function pipe(readable: ReadableStream<Frame>, writable: WritableStream<Frame>, op: Operation) {
  const transform = new TransformStream<Frame, Frame>({
    transform: (frame, controller) => (op === 'encode' ? encode(frame, controller) : decode(frame, controller)).catch(() => undefined),
  })
  readable.pipeThrough(transform).pipeTo(writable).catch(() => undefined)
}

interface Scope {
  onmessage: ((event: MessageEvent) => void) | null
  onrtctransform?: ((event: { transformer: { readable: ReadableStream<Frame>; writable: WritableStream<Frame>; options: { op: Operation } } }) => void) | null
}

const scope = self as unknown as Scope

scope.onrtctransform = (event) => {
  const t = event.transformer
  pipe(t.readable, t.writable, t.options.op)
}

scope.onmessage = (event: MessageEvent) => {
  const m = event.data
  if (m.type === 'keys') setKeys(m.epoch, m.secret, m.leaf)
  else if (m.type === 'stream') pipe(m.readable, m.writable, m.op)
}
