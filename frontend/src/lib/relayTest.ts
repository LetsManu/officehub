/**
 * Administration → System: can this browser reach the stack's own relay (TURN) for meetings?
 * Gathers candidates with only the relay allowed; a "relay" candidate means the relay answered.
 * Talks only to the servers OfficeHub hands out (no outside STUN or any other service).
 */

export interface IceServer {
  urls: string | string[]
  username?: string
  credential?: string
}

export type RelayKind = 'udp' | 'tcp'
export type RelayResult = 'ok' | 'fail' | 'none' | 'unsupported'

/** The TURN addresses per way of connecting (TURN over TLS counts as TCP). STUN addresses are left out. */
export function relayUrls(servers: IceServer[]): Record<RelayKind, IceServer[]> {
  const groups: Record<RelayKind, IceServer[]> = { udp: [], tcp: [] }
  for (const server of servers) {
    const urls = Array.isArray(server.urls) ? server.urls : [server.urls]
    for (const url of urls) {
      const lower = url.toLowerCase()
      if (!lower.startsWith('turn:') && !lower.startsWith('turns:')) continue
      const kind: RelayKind = lower.startsWith('turns:') || lower.includes('transport=tcp') ? 'tcp' : 'udp'
      groups[kind].push({ urls: url, username: server.username, credential: server.credential })
    }
  }
  return groups
}

/** Tries to get a relay candidate from these servers within `timeoutMs`. */
export async function testRelay(servers: IceServer[], timeoutMs = 8000): Promise<RelayResult> {
  if (!servers.length) return 'none'
  if (typeof RTCPeerConnection === 'undefined') return 'unsupported'
  let pc: RTCPeerConnection
  try {
    pc = new RTCPeerConnection({ iceServers: servers, iceTransportPolicy: 'relay' })
  } catch {
    return 'fail'
  }
  try {
    return await new Promise<RelayResult>((resolve) => {
      const timer = window.setTimeout(() => resolve('fail'), timeoutMs)
      const finish = (result: RelayResult) => {
        window.clearTimeout(timer)
        resolve(result)
      }
      pc.onicecandidate = (event) => {
        if (!event.candidate) finish('fail') // gathering finished without a relay candidate
        else if (event.candidate.type === 'relay' || / typ relay /.test(event.candidate.candidate)) finish('ok')
      }
      pc.createDataChannel('check')
      pc.createOffer()
        .then((offer) => pc.setLocalDescription(offer))
        .catch(() => finish('fail'))
    })
  } finally {
    pc.close()
  }
}
