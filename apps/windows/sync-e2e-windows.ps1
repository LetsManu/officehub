# Windows: runs the cloud folder test (src-tauri/tests/cloud_e2e.rs) against a fresh demo OfficeHub server.
# Starts the backend with demo data, makes a space and an app password, runs the test, stops the server.
# Needs Python with the backend's requirements and Rust. Used by .github/workflows/apps.yml.
$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $here "..\..\backend"
$port = if ($env:PORT) { $env:PORT } else { "8011" }
$url = "http://127.0.0.1:$port"
$data = Join-Path ([IO.Path]::GetTempPath()) "officehub-sync-$PID"
New-Item -ItemType Directory -Force $data | Out-Null

$env:DEMO_MODE = "true"
$env:DEMO_LANGUAGE = "de"
$env:DATA_DIR = $data
$server = Start-Process -PassThru -NoNewWindow -WorkingDirectory $backend -FilePath python `
  -ArgumentList "-m", "uvicorn", "app.main:app", "--port", $port `
  -RedirectStandardOutput (Join-Path $data "server.log") -RedirectStandardError (Join-Path $data "server.err")
try {
  for ($i = 0; $i -lt 60; $i++) {
    try { Invoke-RestMethod "$url/api/config" | Out-Null; break } catch { Start-Sleep 1 }
  }
  $headers = @{ "X-Requested-With" = "OfficeHub" }
  $session = $null
  Invoke-RestMethod "$url/api/auth/login" -Method Post -Headers $headers -SessionVariable session -ContentType "application/json" `
    -Body '{"email":"anna.mayer@example.com","password":"demo1234"}' | Out-Null
  $space = Invoke-RestMethod "$url/api/spaces" -Method Post -Headers $headers -WebSession $session -ContentType "application/json" `
    -Body '{"name":"Cloud-Test","description":"","color":"blue"}'
  $password = (Invoke-RestMethod "$url/api/profile/app-passwords" -Method Post -Headers $headers -WebSession $session `
    -ContentType "application/json" -Body '{"name":"Cloud-Test"}').password

  $env:OFFICEHUB_SYNC_SERVER = $url
  $env:OFFICEHUB_SYNC_LOGIN = "anna.mayer@example.com"
  $env:OFFICEHUB_SYNC_PASSWORD = $password
  $env:OFFICEHUB_SYNC_SPACE = "Cloud-Test"
  $env:OFFICEHUB_SYNC_SPACE_ID = "$($space.id)"
  Push-Location (Join-Path $here "src-tauri")
  try {
    cargo test --test sync_e2e --test cloud_e2e -- --nocapture
    if ($LASTEXITCODE -ne 0) { throw "sync tests failed" }
  } finally { Pop-Location }
} finally {
  Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
  Get-Content (Join-Path $data "server.err") -Tail 20 -ErrorAction SilentlyContinue
}
