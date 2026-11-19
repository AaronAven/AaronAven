#!/usr/bin/env bash
# Start the BTC 15-minute paper bot and the dashboard, keep the Mac awake, stop everything on Ctrl-C.
#   ./run_all.sh            continue existing runs
#   ./run_all.sh --reset    start fresh with the $1,000 paper bankroll
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p logs
RESET=""
[[ "${1:-}" == "--reset" ]] && RESET="--reset"

pids=()
stopped=""
cleanup() { [[ -n "$stopped" ]] && return; stopped=1; echo; echo "Stopping..."; kill -TERM "${pids[@]}" 2>/dev/null || true; wait 2>/dev/null || true; }
trap cleanup INT TERM EXIT

python3 -u btc15_bot.py --name btc15 $RESET >> logs/btc15.log 2>&1 & pids+=($!)
python3 -u btc15_bot.py --name btc15_strong --min-price 0.92 $RESET >> logs/btc15_strong.log 2>&1 & pids+=($!)
python3 -u dashboard.py >> logs/dashboard.log 2>&1 & pids+=($!)

# keep the Mac from sleeping while this script runs (macOS only)
if command -v caffeinate >/dev/null; then caffeinate -i -w $$ & pids+=($!); fi

echo "Running. Dashboard: http://127.0.0.1:8787   Logs: kalshi_bot/logs/   Ctrl-C to stop."
echo "Phone access: tailscale serve --bg 8787   (once; it keeps serving after restarts)"
wait
