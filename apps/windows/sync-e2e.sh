#!/usr/bin/env bash
# Runs the sync end-to-end test (src-tauri/tests/sync_e2e.rs) against a fresh demo OfficeHub server:
# starts the backend with demo data, makes a space and an app password, runs the test, stops the server.
# Needs Python with the backend's requirements and Rust. Used by .github/workflows/apps.yml as well.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
backend="$here/../../backend"
port="${PORT:-8011}"
data="$(mktemp -d)"
url="http://127.0.0.1:$port"
python="${PYTHON:-python3}"

cleanup() {
  [ -n "${server_pid:-}" ] && kill "$server_pid" 2>/dev/null || true
  rm -rf "$data"
}
trap cleanup EXIT

(cd "$backend" && DEMO_MODE=true DEMO_LANGUAGE=de DATA_DIR="$data" "$python" -m uvicorn app.main:app --port "$port" \
  >"$data/server.log" 2>&1) &
server_pid=$!
for _ in $(seq 1 60); do
  curl -sf "$url/api/config" >/dev/null && break
  sleep 1
done

jar="$data/cookies"
h=(-H "X-Requested-With: OfficeHub" -H "Content-Type: application/json" -b "$jar" -c "$jar")
curl -sf "${h[@]}" "$url/api/auth/login" -d '{"email":"anna.mayer@example.com","password":"demo1234"}' >/dev/null
curl -sf "${h[@]}" "$url/api/spaces" -d '{"name":"Sync-Test","description":"","color":"blue"}' >/dev/null
password="$(curl -sf "${h[@]}" "$url/api/profile/app-passwords" -d '{"name":"Sync-Test"}' |
  "$python" -c 'import json,sys; print(json.load(sys.stdin)["password"])')"

cd "$here/src-tauri"
OFFICEHUB_SYNC_SERVER="$url" OFFICEHUB_SYNC_LOGIN="anna.mayer@example.com" OFFICEHUB_SYNC_PASSWORD="$password" \
  OFFICEHUB_SYNC_SPACE="Sync-Test" cargo test --test sync_e2e -- --nocapture
