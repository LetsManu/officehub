/**
 * Puts SFrame (sframe.worker.ts) on the audio and video of a built-in meeting: every sender encrypts, every
 * receiver decrypts. RTCRtpScriptTransform where the browser has it, the older encoded streams otherwise.
 */

import type { E2eeKeys } from './mls'

type Legacy = { createEncodedStreams?: () => { readable: ReadableStream; writable: WritableStream } }

const scriptTransform = () => typeof RTCRtpScriptTransform === 'function'
const legacy = () => typeof RTCRtpSender !== 'undefined' && 'createEncodedStreams' in RTCRtpSender.prototype

/** Whether this browser can take part in an end-to-end encrypted meeting at all. */
export function e2eeSupported(): boolean {
  return scriptTransform() || legacy()
}

export class MediaCrypto {
  private worker = new Worker(new URL('./sframe.worker.ts', import.meta.url), { type: 'module' })
  private done = new WeakSet<object>()

  /** Settings for each RTCPeerConnection (the older interface must be switched on per connection). */
  peerConfig(): Record<string, unknown> {
    return scriptTransform() ? {} : { encodedInsertableStreams: true }
  }

  setKeys(keys: E2eeKeys) {
    const secret = keys.sframe.slice().buffer
    this.worker.postMessage({ type: 'keys', epoch: keys.epoch, secret, leaf: keys.leaf }, [secret])
  }

  private attach(target: RTCRtpSender | RTCRtpReceiver, op: 'encode' | 'decode') {
    if (this.done.has(target)) return
    this.done.add(target)
    if (scriptTransform()) {
      ;(target as unknown as { transform: unknown }).transform = new RTCRtpScriptTransform(this.worker, { op })
      return
    }
    const streams = (target as unknown as Legacy).createEncodedStreams?.()
    if (streams) this.worker.postMessage({ type: 'stream', op, readable: streams.readable, writable: streams.writable }, [streams.readable, streams.writable] as unknown as Transferable[])
  }

  sender(sender: RTCRtpSender) {
    this.attach(sender, 'encode')
  }

  receiver(receiver: RTCRtpReceiver) {
    this.attach(receiver, 'decode')
  }

  stop() {
    this.worker.terminate()
  }
}
