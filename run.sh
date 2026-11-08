#!/usr/bin/env bash
# Run Headcount from the terminal.
#
#   ./run.sh           server + Cloudflare tunnel (real Twilio calls work)
#   ./run.sh local     server only (simulated calls, no tunnel)
#   ./run.sh offline   server only, Gemini off (saves your free quota; keyword fallback)
#   ./run.sh stop      stop everything this script started
#
# Ctrl+C stops it. Logs go to .run/server.log and .run/tunnel.log.
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8080}"
mkdir -p .run

stop_all() {
  pkill -f "uvicorn app.main:app --host 127.0.0.1 --port $PORT" 2>/dev/null || true
  pkill -f "cloudflared tunnel --url http://localhost:$PORT" 2>/dev/null || true
}

if [[ "${1:-}" == "stop" ]]; then stop_all; echo "Stopped."; exit 0; fi

[[ -x .venv/bin/uvicorn ]] || { echo "Setting up .venv (first run)..."; python3 -m venv .venv; .venv/bin/pip install -q -r requirements.txt; }
[[ -f .env ]] || { cp .env.example .env; echo "Created .env from .env.example (add your keys)."; }

stop_all   # start clean
trap 'echo; echo "Stopping..."; stop_all; exit 0' INT TERM

MODE="${1:-tunnel}"
if [[ "$MODE" == "tunnel" ]]; then
  command -v cloudflared >/dev/null || { echo "cloudflared not found: brew install cloudflared (or run ./run.sh local)"; exit 1; }
  echo "Starting Cloudflare tunnel..."
  cloudflared tunnel --url "http://localhost:$PORT" > .run/tunnel.log 2>&1 &
  URL=""
  for _ in $(seq 1 30); do
    URL=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" .run/tunnel.log | head -1 || true)
    [[ -n "$URL" ]] && break; sleep 1
  done
  [[ -n "$URL" ]] || { echo "Tunnel did not start; see .run/tunnel.log"; stop_all; exit 1; }
  # write the fresh tunnel address into .env (it changes every run)
  if grep -q '^PUBLIC_BASE_URL=' .env; then sed -i '' "s|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=$URL|" .env
  else echo "PUBLIC_BASE_URL=$URL" >> .env; fi
fi

echo "Starting Headcount on port $PORT..."
if [[ "$MODE" == "offline" ]]; then
  GEMINI_API_KEY= GOOGLE_API_KEY= .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT" > .run/server.log 2>&1 &
else
  .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT" > .run/server.log 2>&1 &
fi

for _ in $(seq 1 20); do curl -s "localhost:$PORT/api/health" >/dev/null 2>&1 && break; sleep 0.5; done
HEALTH=$(curl -s "localhost:$PORT/api/health" || echo '{"ok":false}')

cat <<EOF

  Headcount is running.
  Board:            http://localhost:$PORT        (press F for full screen)
  Phone simulator:  http://localhost:$PORT/phone
  Status:           $HEALTH
EOF
if [[ "$MODE" == "tunnel" ]]; then
cat <<EOF
  Public (Twilio):  $URL
  Twilio number "A call comes in" webhook (only needed for calling IN):
                    $URL/twilio/incoming
EOF
fi
echo
echo "  Ctrl+C to stop."
open "http://localhost:$PORT" 2>/dev/null || true
wait
