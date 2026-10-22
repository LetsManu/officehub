/**
 * The app bar on the left, like Teams: the everyday tools, then the apps someone pinned, then "Apps" with the rest.
 * A click on a tool goes back to where you last were in it (the chat you had open, the space and tab), like Teams.
 */

import { computed, ref } from 'vue'
import { allPages, navGroups, type NavGroup, type NavItem } from './navigation'

/** Always in the bar, in this order (Start stays first). */
export const RAIL_PATHS = ['/', '/activity', '/chat', '/spaces', '/calendar', '/meetings', '/files']
/** Pinned until someone changes it. */
export const DEFAULT_PINS = ['/tasks', '/requests', '/time']
const PINS_KEY = 'officehub-rail-pins'
const PLACES_KEY = 'officehub-rail-places'

function read<T>(storage: () => Storage, key: string, fallback: T): T {
  try {
    const raw = storage().getItem(key)
    return raw === null ? fallback : (JSON.parse(raw) as T)
  } catch {
    return fallback
  }
}

function write(storage: () => Storage, key: string, value: unknown) {
  try {
    storage().setItem(key, JSON.stringify(value))
  } catch {
    /* private window */
  }
}

const local = () => localStorage
const session = () => sessionStorage

export const pins = ref<string[]>(read(local, PINS_KEY, DEFAULT_PINS))

export const railItems = computed<NavItem[]>(() =>
  RAIL_PATHS.map((to) => allPages.value.find((p) => p.to === to)).filter((p): p is NavItem => !!p),
)

/** Everything that is not a fixed tool, grouped as in the menu (role-gated areas only when allowed). */
export const appGroups = computed<NavGroup[]>(() =>
  navGroups.value
    .map((g) => ({ ...g, items: g.items.filter((i) => !RAIL_PATHS.includes(i.to)) }))
    .filter((g) => g.items.length),
)

/** Pinned apps that exist for this person, in the order they were pinned. */
export const pinnedItems = computed<NavItem[]>(() => {
  const apps = appGroups.value.flatMap((g) => g.items)
  return pins.value.map((to) => apps.find((i) => i.to === to)).filter((i): i is NavItem => !!i)
})

export function isPinned(to: string): boolean {
  return pins.value.includes(to)
}

export function togglePin(to: string) {
  pins.value = isPinned(to) ? pins.value.filter((p) => p !== to) : [...pins.value, to]
  write(local, PINS_KEY, pins.value)
}

/** The tool or app a page belongs to: the longest matching entry ("/admin/audit" is not "/admin"). */
export function sectionOf(path: string, entries: string[]): string | null {
  const matches = entries.filter((to) => (to === '/' ? path === '/' : path === to || path.startsWith(`${to}/`)))
  return matches.sort((a, b) => b.length - a.length)[0] ?? null
}

const places = ref<Record<string, string>>(read(session, PLACES_KEY, {}))

/** Remembers the page someone is on as the place to come back to in its tool. */
export function notePlace(section: string | null, fullPath: string) {
  if (!section || section === '/' || places.value[section] === fullPath) return
  places.value = { ...places.value, [section]: fullPath }
  write(session, PLACES_KEY, places.value)
}

/** Where a click on a tool leads: back to the last place in it, or its start when you are already there. */
export function railTarget(to: string, current: string | null): string {
  if (current === to) return to
  return places.value[to] ?? to
}
