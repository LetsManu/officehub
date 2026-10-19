// Applies the saved (or system) colour theme before the first paint, so dark mode never flashes white.
// Kept as an external file because the Content-Security-Policy does not allow inline scripts.
(function () {
  var value = null
  try {
    value = localStorage.getItem('officehub.theme')
  } catch (e) {
    /* storage unavailable */
  }
  if (value !== 'dark' && value !== 'light') {
    value = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }
  document.documentElement.dataset.theme = value
})()
