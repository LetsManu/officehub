/** Logic for the planning board: day maths, stacking bars into lanes and workload levels. */

import type { Allocation } from './types'

export const PROJECT_COLORS = ['blue', 'teal', 'green', 'amber', 'orange', 'purple', 'pink', 'slate'] as const

/** Whole days from a to b (ISO dates). */
export function dayDiff(a: string, b: string): number {
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000)
}

/** Put overlapping bars of one person into separate lanes, first come first. */
export function assignLanes(allocations: Allocation[]): Map<number, number> {
  const lanes = new Map<number, number>()
  const laneEnds: string[] = []
  const sorted = [...allocations].sort((x, y) => x.start_date.localeCompare(y.start_date) || x.id - y.id)
  for (const a of sorted) {
    let lane = laneEnds.findIndex((end) => end < a.start_date)
    if (lane === -1) {
      lane = laneEnds.length
      laneEnds.push(a.end_date)
    } else {
      laneEnds[lane] = a.end_date
    }
    lanes.set(a.id, lane)
  }
  return lanes
}

export type Workload = 'none' | 'free' | 'good' | 'full' | 'over'

/** Planned share of the working time: under 50 % free, up to 90 % good, up to 100 % full, above that over. */
export function workload(planned: number, capacity: number): Workload {
  if (capacity <= 0) return planned > 0 ? 'over' : 'none'
  const share = planned / capacity
  if (share > 1.001) return 'over'
  if (share >= 0.9) return 'full'
  if (share >= 0.5) return 'good'
  return 'free'
}

export function percent(part: number, whole: number): number {
  return whole > 0 ? Math.round((part / whole) * 100) : 0
}

/** Planned hours a day for each working day in the range, summed per day for one person. */
export function dailyLoad(allocations: Allocation[], days: string[]): number[] {
  return days.map((day) => allocations.reduce((sum, a) => (a.start_date <= day && day <= a.end_date ? sum + a.minutes_per_day : sum), 0))
}
