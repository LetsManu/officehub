/**
 * Puts SFrame (sframe.worker.ts) on the audio and video of an encrypted meeting: every sender encrypts, every
 * receiver decrypts. RTCRtpScriptTransform where the browser has it, the older encoded streams otherwise. Built-in
 * meetings hand over their connections; with the Jitsi server, guardAll() catches the connections lib-jitsi-meet
 * makes (its own frame encryption with an external key leaves frames unencrypted in the version we use).
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

  /** Every sender and receiver a connection has right now. */
  secure(pc: RTCPeerConnection) {
    for (const transceiver of pc.getTransceivers()) {
      this.sender(transceiver.sender)
      this.receiver(transceiver.receiver)
    }
  }

  /**
   * For connections made by someone else's code (lib-jitsi-meet): from now on every RTCPeerConnection gets SFrame on
   * each sender before it can send anything (addTrack, addTransceiver, replaceTrack) and on each receiver as soon as
   * it exists. Returns a function that puts everything back.
   */
  guardAll(): () => void {
    const Pc = window.RTCPeerConnection
    const proto = Pc.prototype
    const senderProto = RTCRtpSender.prototype
    const original = {
      addTrack: proto.addTrack,
      addTransceiver: proto.addTransceiver,
      setRemoteDescription: proto.setRemoteDescription,
      setLocalDescription: proto.setLocalDescription,
      replaceTrack: senderProto.replaceTrack,
    }
    const crypto = this
    proto.addTrack = function (this: RTCPeerConnection, ...args: Parameters<RTCPeerConnection['addTrack']>) {
      const sender = original.addTrack.apply(this, args)
      crypto.secure(this)
      return sender
    }
    proto.addTransceiver = function (this: RTCPeerConnection, ...args: Parameters<RTCPeerConnection['addTransceiver']>) {
      const transceiver = original.addTransceiver.apply(this, args)
      crypto.sender(transceiver.sender)
      crypto.receiver(transceiver.receiver)
      return transceiver
    }
    type Describe = (this: RTCPeerConnection, ...args: unknown[]) => Promise<void>
    proto.setRemoteDescription = async function (this: RTCPeerConnection, ...args: unknown[]) {
      const result = await (original.setRemoteDescription as Describe).apply(this, args)
      crypto.secure(this)
      return result
    } as RTCPeerConnection['setRemoteDescription']
    proto.setLocalDescription = async function (this: RTCPeerConnection, ...args: unknown[]) {
      crypto.secure(this)
      return (original.setLocalDescription as Describe).apply(this, args)
    } as RTCPeerConnection['setLocalDescription']
    senderProto.replaceTrack = function (this: RTCRtpSender, track: MediaStreamTrack | null) {
      crypto.sender(this)
      return original.replaceTrack.call(this, track)
    }
    // The older interface has to be switched on when a connection is made
    if (!scriptTransform()) {
      window.RTCPeerConnection = class extends Pc {
        constructor(config?: RTCConfiguration) {
          super({ ...(config ?? {}), encodedInsertableStreams: true } as RTCConfiguration)
        }
      } as typeof RTCPeerConnection
    }
    return () => {
      Object.assign(proto, {
        addTrack: original.addTrack,
        addTransceiver: original.addTransceiver,
        setRemoteDescription: original.setRemoteDescription,
        setLocalDescription: original.setLocalDescription,
      })
      senderProto.replaceTrack = original.replaceTrack
      window.RTCPeerConnection = Pc
    }
  }

  stop() {
    this.worker.terminate()
  }
}
