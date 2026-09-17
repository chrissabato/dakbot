# capture_dakbot.py — Raw UART byte dump for the dakbot's Colorado console
# input, run directly on the ESP32-S3 (MicroPython) via mpremote.
#
# Captures every byte received on the same UART/pins/baud that colorado.py
# uses, so the exact bytes dakbot sees can be compared against an
# independent capture of the same tapped signal (see capture_usb_serial.py
# + compare_captures.py in this directory).
#
# IMPORTANT: bytes are buffered in memory during the capture window and
# only printed afterward. Printing per-byte *during* the capture (as an
# earlier version of this script did) is slow enough on MicroPython to
# starve the UART's receive buffer under load and drop bytes itself —
# that would make the capture measure this script's own overhead, not
# what colorado.py actually receives in normal operation.
#
# Usage (from the computer, with the board connected over USB):
#   mpremote connect PORT run capture_dakbot.py > dakbot_capture.log
#
# `mpremote run` interrupts whatever's currently running on the board
# (including a normally auto-running main.py) and takes exclusive use of
# the UART for the duration of the capture — main.py is NOT running while
# this is active, so the board won't be serving JSON/MQTT during the test.
# Press Ctrl-C (or just let CAPTURE_SECONDS elapse) to stop; a partial
# buffer is still flushed before exit either way. Power-cycle or
# `mpremote reset` the board afterward to resume normal operation.
#
# Output format, one line per byte (printed only after capture ends):
#   <seq> <ms_since_start> <hex_byte>
# e.g.:
#   482 1734215 bc

import time
import array
from machine import UART, Pin

import config
import settings

settings.load()

CAPTURE_SECONDS = 25  # stop automatically after this long; Ctrl-C also works
MAX_BYTES = 15_000     # board only has ~128KB free heap (gc.mem_free()) — keep well under it

uart = UART(
    config.UART_ID,
    baudrate=config.COLORADO_BAUD,
    rx=Pin(settings.current['uart_rx']),
    tx=Pin(settings.current.get('uart_tx', 17)),
    bits=8,
    parity=None,
    stop=1,
    timeout=0,
    rxbuf=4096,  # generous ring buffer so brief scheduling jitter can't drop bytes
)

buf = bytearray(MAX_BYTES)
# Milliseconds, not microseconds: fits CAPTURE_SECONDS comfortably in an
# unsigned short (array('H')) at 2 bytes/entry instead of a plain Python
# list of ints, which allocates a pointer-sized slot per element and is
# what actually ran the board out of heap here (not the raw byte buffer).
times = array.array('H', bytes(2 * MAX_BYTES))
n = 0

start_us = time.ticks_us()
deadline_us = time.ticks_add(start_us, CAPTURE_SECONDS * 1_000_000)

try:
    while n < MAX_BYTES and time.ticks_diff(deadline_us, time.ticks_us()) > 0:
        avail = uart.any()
        if avail:
            chunk = uart.read(avail)
            if chunk:
                now_ms = time.ticks_diff(time.ticks_us(), start_us) // 1000
                for b in chunk:
                    if n >= MAX_BYTES:
                        break
                    buf[n] = b
                    times[n] = now_ms  # whole-chunk timestamp; fine-grained enough for alignment
                    n += 1
        # No sleep: colorado.py's own loop yields via asyncio, not a real
        # delay, so busy-polling here best matches its actual receive
        # timing instead of adding artificial gaps that could miss bytes.
except KeyboardInterrupt:
    pass

# Flush in small batches with brief pauses rather than one continuous
# burst of 10-15k print() calls. A chained back-to-back run once caught
# the *next* mpremote session reconnecting while this dump was still
# mid-flight, and left the board wedged (unresponsive to Ctrl-C, needing
# a full USB-level reset to recover) — almost certainly a USB-CDC
# flow-control stall from a new raw-REPL session grabbing the port while
# a print() was blocked waiting for buffer space. Small batches + pauses
# don't fix a badly-timed reconnect on their own (see the chaining
# script's settle delay + readiness check for that), but they shrink the
# window where the port is mid-transfer, and a stalled write recovers
# faster once the reader comes back instead of sitting on a huge backlog.
BATCH = 200
for start in range(0, n, BATCH):
    for i in range(start, min(start + BATCH, n)):
        print(i, times[i], '%02x' % buf[i])
    time.sleep_ms(5)

print('CAPTURE_DONE', n)
