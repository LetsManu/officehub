import { describe, expect, it } from 'vitest'
import { assignLanes, dailyLoad, dayDiff, workload } from '../src/lib/planning'
import type { Allocation } from '../src/lib/types'

const a = (id: number, start_date: string, end_date: string, minutes_per_day = 240): Allocation => ({
  id, project_id: 1, user_id: 1, start_date, end_date, minutes_per_day, note: '',
})

describe('planning board', () => {
  it('counts days', () => {
    expect(dayDiff('2026-10-19', '2026-10-26')).toBe(7)
    expect(dayDiff('2026-03-28', '2026-03-30')).toBe(2) // across the switch to summer time
  })

  it('stacks overlapping bars into lanes', () => {
    const lanes = assignLanes([a(1, '2026-10-19', '2026-10-23'), a(2, '2026-10-21', '2026-10-30'), a(3, '2026-10-26', '2026-10-27')])
    expect(lanes.get(1)).toBe(0)
    expect(lanes.get(2)).toBe(1)
    expect(lanes.get(3)).toBe(0)
  })

  it('rates the workload', () => {
    expect(workload(0, 0)).toBe('none')
    expect(workload(60, 0)).toBe('over')
    expect(workload(100, 480)).toBe('free')
    expect(workload(300, 480)).toBe('good')
    expect(workload(480, 480)).toBe('full')
    expect(workload(500, 480)).toBe('over')
  })

  it('adds up the hours per day', () => {
    expect(dailyLoad([a(1, '2026-10-19', '2026-10-20'), a(2, '2026-10-20', '2026-10-21', 120)], ['2026-10-19', '2026-10-20', '2026-10-22']))
      .toEqual([240, 360, 0])
  })
})
