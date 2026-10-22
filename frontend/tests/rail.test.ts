import { describe, expect, it, vi } from 'vitest'
import { computed } from 'vue'

vi.mock('../src/lib/navigation', () => ({ allPages: computed(() => []), navGroups: computed(() => []) }))
const { notePlace, railTarget, sectionOf } = await import('../src/lib/rail')

describe('app bar (like Teams)', () => {
  it('finds the tool a page belongs to, most specific first', () => {
    const entries = ['/', '/admin', '/admin/audit', '/chat']
    expect(sectionOf('/admin/audit', entries)).toBe('/admin/audit')
    expect(sectionOf('/admin/users', entries)).toBe('/admin')
    expect(sectionOf('/chat/4', entries)).toBe('/chat')
    expect(sectionOf('/', entries)).toBe('/')
    expect(sectionOf('/chatroom', entries)).toBeNull()
  })

  it('goes back to the last place in a tool, or to its start when already there', () => {
    expect(railTarget('/spaces', null)).toBe('/spaces')
    notePlace('/spaces', '/spaces/3?tab=files')
    expect(railTarget('/spaces', '/chat')).toBe('/spaces/3?tab=files')
    expect(railTarget('/spaces', '/spaces')).toBe('/spaces')
    notePlace('/', '/?x=1')
    expect(railTarget('/', '/chat')).toBe('/')
  })
})
