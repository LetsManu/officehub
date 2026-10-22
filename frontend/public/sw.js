// OfficeHub service worker: makes the portal installable and keeps the app shell available
// for a moment without network. API answers are never cached (they contain personal data).
const CACHE = 'officehub-shell-v2'
const SHELL = ['/', '/index.html', '/offline.html', '/offline.css', '/favicon.svg', '/icon-192.png', '/theme-init.js']
// Files and text shared from other apps wait here until the person chooses where they go (see /share).
const SHARE = 'officehub-share'

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()))
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE && key !== SHARE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  )
})

/** Keep what another app shared (the installed app is its share target) and open the page that hands it on. */
async function receiveShare(request) {
  const form = await request.formData()
  const cache = await caches.open(SHARE)
  for (const key of await cache.keys()) await cache.delete(key)
  const files = form.getAll('files').filter((f) => typeof f !== 'string' && f.size > 0)
  const meta = {
    title: String(form.get('title') || ''),
    text: String(form.get('text') || ''),
    url: String(form.get('url') || ''),
    files: files.map((f, i) => ({ name: f.name || `file-${i + 1}`, type: f.type || 'application/octet-stream', size: f.size })),
  }
  await Promise.all(
    files.map((f, i) => cache.put(`/share/file/${i}`, new Response(f, { headers: { 'Content-Type': f.type || 'application/octet-stream' } }))),
  )
  await cache.put('/share/meta', new Response(JSON.stringify(meta), { headers: { 'Content-Type': 'application/json' } }))
  return Response.redirect('/share', 303)
}

self.addEventListener('fetch', (event) => {
  const request = event.request
  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  if (request.method === 'POST' && url.pathname === '/share') {
    event.respondWith(receiveShare(request))
    return
  }
  if (request.method !== 'GET' || url.pathname.startsWith('/api/')) return

  // Built files have content hashes in their names, so the cached copy is always right.
  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(
      caches.match(request).then(
        (hit) =>
          hit ||
          fetch(request).then((response) => {
            if (response.ok) {
              const copy = response.clone()
              caches.open(CACHE).then((cache) => cache.put(request, copy))
            }
            return response
          }),
      ),
    )
    return
  }

  // Pages: always try the network first so updates arrive at once; without network the cached shell
  // (the portal then says it is offline), or a plain "no connection" page.
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.match('/index.html').then((hit) => hit || caches.match('/offline.html'))))
  }
})

// A click on a notification (new message, call, meeting reminder) brings OfficeHub to the front on that page.
self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url = (event.notification.data && event.notification.data.url) || '/'
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
      const open = windows.find((w) => new URL(w.url).origin === self.location.origin)
      if (open) {
        open.postMessage({ navigate: url })
        return open.focus()
      }
      return self.clients.openWindow(url)
    }),
  )
})
