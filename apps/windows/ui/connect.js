// The address screen: which OfficeHub this app belongs to. The app checks the address and opens the portal.
const invoke = (cmd, args) => window.__TAURI_INTERNALS__.invoke(cmd, args)
const $ = (id) => document.getElementById(id)
let texts = {}

async function start() {
  texts = await invoke('ui_texts')
  document.documentElement.lang = texts.lang
  $('title').textContent = texts.connectTitle
  $('text').textContent = texts.connectText
  $('label').textContent = texts.addressLabel
  $('address').placeholder = texts.addressPlaceholder
  $('button').textContent = texts.connect
  $('address').focus()
}

$('form').addEventListener('submit', async (event) => {
  event.preventDefault()
  const address = $('address').value
  $('error').hidden = true
  $('button').disabled = true
  $('button').textContent = texts.checking
  try {
    await invoke('connect', { address })
  } catch (code) {
    $('error').textContent = texts[String(code)] || texts.unreachable
    $('error').hidden = false
    $('button').disabled = false
    $('button').textContent = texts.connect
    $('address').focus()
  }
})

start()
