#!/usr/bin/env bash
# chain_dakbot_captures.sh — Run capture_dakbot.py back-to-back on the
# board to cover a window longer than one capture's ~15-20s memory limit,
# without wedging the board.
#
# A naive back-to-back loop once left the board unresponsive: a new
# mpremote session reconnected right as the previous one's ~15k-line
# print dump was still draining over USB, and the resulting stall needed
# a full USB-level reset (unbind/bind, not just Ctrl-C or `mpremote
# reset`) to recover. This script waits for each run's explicit
# CAPTURE_DONE sentinel, adds a settle delay, and confirms the board
# actually responds before starting the next round — if a round doesn't
# come back cleanly, it stops instead of piling on.
#
# Usage: ./chain_dakbot_captures.sh PORT OUT_PREFIX ROUNDS
#   ./chain_dakbot_captures.sh /dev/ttyACM1 /tmp/scratch/dakbot_chunk 6

set -u

PORT="${1:?usage: chain_dakbot_captures.sh PORT OUT_PREFIX ROUNDS}"
OUT_PREFIX="${2:?usage: chain_dakbot_captures.sh PORT OUT_PREFIX ROUNDS}"
ROUNDS="${3:?usage: chain_dakbot_captures.sh PORT OUT_PREFIX ROUNDS}"
SETTLE_SECONDS=3

check_ready() {
    timeout 8 mpremote connect "$PORT" exec "print('READY')" 2>/dev/null | grep -q READY
}

for i in $(seq 1 "$ROUNDS"); do
    out="${OUT_PREFIX}${i}.log"
    err="${OUT_PREFIX}${i}.err"
    echo "=== round $i starting at $(date +%H:%M:%S) ==="

    mpremote connect "$PORT" run capture_dakbot.py > "$out" 2> "$err"
    rc=$?

    if [ $rc -ne 0 ] || ! grep -q '^CAPTURE_DONE' "$out"; then
        echo "=== round $i FAILED (exit=$rc, no CAPTURE_DONE sentinel) — stopping chain, not retrying blind ==="
        cat "$err"
        exit 1
    fi

    lines=$(grep -c . "$out")
    echo "=== round $i done at $(date +%H:%M:%S), $lines lines ==="

    echo "settling ${SETTLE_SECONDS}s before reconnecting..."
    sleep "$SETTLE_SECONDS"

    if ! check_ready; then
        echo "board did not respond after settle delay — waiting longer and rechecking..."
        sleep 5
        if ! check_ready; then
            echo "=== board still unresponsive after round $i — stopping chain rather than risk another wedge ==="
            exit 1
        fi
    fi
done

echo "=== all $ROUNDS rounds completed cleanly ==="
