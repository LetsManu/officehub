/**
 * Breakout rooms: the people leading a meeting split it into small groups for a while. The portal keeps who
 * belongs where; each group is a room of its own on the same way underneath (built in or Jitsi).
 * Uses the meeting's room token, so guests take part too.
 */

import { ApiError } from './api'
import type { JoinInfo } from './meeting'

export interface BreakoutState {
  open: boolean
  rooms: string[]
  mine: number | null
  ends_at: number | null // seconds since 1970
  assign?: Record<string, number> // only for the people leading the meeting
  moderator: boolean
  current: string | null // the room I am in, when it is a breakout room
}

async function call<T>(token: string, method: 'GET' | 'PUT' | 'POST', path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { 'X-Meeting-Token': token, Accept: 'application/json' }
  if (method !== 'GET') {
    headers['X-Requested-With'] = 'OfficeHub'
    headers['Content-Type'] = 'application/json'
  }
  const response = await fetch(`/api/rtc/breakouts${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined })
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(response.status, data?.code ?? 'unknown', data?.detail ?? '')
  return data as T
}

export const breakoutState = (token: string) => call<BreakoutState>(token, 'GET', '')

export const saveBreakouts = (token: string, body: { rooms: string[]; assign: Record<string, number>; open: boolean; minutes?: number | null }) =>
  call<BreakoutState>(token, 'PUT', '', body)

/** The connection for a breakout room, or back to the meeting (null). */
export async function breakoutJoin(token: string, room: number | null, meetingId: number, title: string): Promise<JoinInfo> {
  const connection = await call<JoinInfo['connection']>(token, 'POST', '/join', { room })
  return { meeting_id: meetingId, title, connection }
}

/** Spread people evenly over the rooms (the order they are listed in). */
export function spread(people: string[], rooms: number): Record<string, number> {
  return Object.fromEntries(people.map((who, i) => [who, i % rooms]))
}
