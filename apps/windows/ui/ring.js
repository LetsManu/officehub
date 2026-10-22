// The small window that rings when a call comes in while OfficeHub is hidden (like Teams).
const invoke = (cmd, args) => window.__TAURI_INTERNALS__.invoke(cmd, args)
const params = new URLSearchParams(location.search)
const $ = (id) => document.getElementById(id)
const name = params.get('name') || ''

$('name').textContent = name
$('text').textContent = params.get('text') || ''
$('initials').textContent = name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('')
$('accept').textContent = params.get('accept') || 'Accept'
$('decline').textContent = params.get('decline') || 'Decline'
$('accept').addEventListener('click', () => invoke('ring_answer', { action: 'accept' }))
$('decline').addEventListener('click', () => invoke('ring_answer', { action: 'decline' }))
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') invoke('ring_answer', { action: 'decline' })
})
$('accept').focus()
