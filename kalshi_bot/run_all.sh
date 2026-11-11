#!/usr/bin/env bash
# Start both paper runs and the dashboard, keep the Mac awake, stop everything on Ctrl-C.
#   ./run_all.sh            continue existing runs
#   ./run_all.sh --reset    start both runs fresh at $500
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p logs
RESET=""
[[ "${1:-}" == "--reset" ]] && RESET="--reset"

pids=()
stopped=""
cleanup() { [[ -n "$stopped" ]] && return; stopped=1; echo; echo "Stopping..."; kill -TERM "${pids[@]}" 2>/dev/null || true; wait 2>/dev/null || true; }
trap cleanup INT TERM EXIT

python3 -u paper_bot.py --name through $RESET --report-every 900 >> logs/through.log 2>&1 & pids+=($!)
python3 -u paper_bot.py --name touch --fill-rule touch --max-rps 5 $RESET --report-every 900 >> logs/touch.log 2>&1 & pids+=($!)
python3 -u dashboard.py >> logs/dashboard.log 2>&1 & pids+=($!)

# keep the Mac from sleeping while this script runs (macOS only)
if command -v caffeinate >/dev/null; then caffeinate -i -w $$ & pids+=($!); fi

echo "Running. Dashboard: http://127.0.0.1:8787   Logs: kalshi_bot/logs/   Ctrl-C to stop."
echo "Phone access: tailscale serve --bg 8787   (once; it keeps serving after restarts)"
wait
