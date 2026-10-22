/**
 * Like Teams and Webex, the address bar stays calm: it shows only the portal's address, whatever page is open.
 * The pages themselves still have their own paths inside the app (vue-router with a memory history), so
 * - links from e-mails, notifications, the installed app's shortcuts, guest links and "open in new tab" still land on
 *   the right page: the path they open with is read once at the start and then hidden,
 * - the browser's back and forward buttons go through the pages visited, one browser entry per page,
 * - reloading stays on the same page (remembered for this tab only).
 */

import { ref } from 'vue'
import { createMemoryHistory, type RouterHistory } from 'vue-router'

const KEY = 'officehub.place'

/** The path of the page that is open now (the address bar no longer shows it). */
export const place = ref('/')

function remembered(): string | null {
  try {
    return sessionStorage.getItem(KEY)
  } catch {
    return null
  }
}

/** Where the app starts: the path it was opened with, else (a reload) the page this tab was on. */
export function startPath(): string {
  const opened = window.location.pathname + window.location.search + window.location.hash
  if (opened !== '/') return opened
  return remembered() ?? '/'
}

/**
 * A memory history whose page changes also become browser history entries with the plain address, so the browser's
 * back and forward buttons keep working.
 */
export function calmHistory(): RouterHistory {
  const history = createMemoryHistory()
  history.replace(startPath())
  // After a reload the browser still has the entries from before: carry on counting from where this one is
  const state = window.history.state as { officehub?: unknown } | null
  let index = typeof state?.officehub === 'number' ? state.officehub : 0
  window.history.replaceState({ officehub: index }, '', '/')

  const push = history.push.bind(history)
  history.push = (to, data) => {
    push(to, data)
    index += 1
    window.history.pushState({ officehub: index }, '', '/')
  }

  window.addEventListener('popstate', (event) => {
    const target = typeof event.state?.officehub === 'number' ? event.state.officehub : 0
    const delta = target - index
    index = target
    if (delta) history.go(delta)
  })

  return history
}

/** Called after every page change: remember it for a reload and for checks like "is this chat open". */
export function notePlace(path: string) {
  place.value = path
  try {
    sessionStorage.setItem(KEY, path)
  } catch {
    /* private mode: a reload starts on the home page */
  }
}
