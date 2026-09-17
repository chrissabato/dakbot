#!/usr/bin/env python3
# capture_usb_serial.py — Raw byte dump for a USB-to-serial adapter tapped
# into the same Colorado System 7 console signal dakbot reads, so the two
# captures can be diffed (see compare_captures.py) to tell whether garbage
# bytes are already on the wire (both captures see the same bad bytes) or
# introduced independently on one leg of the tap (only one capture sees
# them — points at that leg's wiring/level-shifting instead of the console
# or a shared noise source).
#
# Run this on the computer at the same time capture_dakbot.py is running
# on the board (order doesn't matter much — compare_captures.py aligns the
# two logs by content, not by wall-clock start time).
#
# Usage:
#   python3 capture_usb_serial.py [port] [seconds] [baud]
#   python3 capture_usb_serial.py /dev/ttyUSB0 120
#
# Output format matches capture_dakbot.py, one line per byte:
#   <seq> <ms_since_start> <hex_byte>

import sys
import time
import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else '/dev/ttyUSB0'
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 120
BAUD = int(sys.argv[3]) if len(sys.argv) > 3 else 9600  # Colorado System 7 fixed baud

print(f'Capturing {PORT} at {BAUD} baud for {SECONDS:.0f}s — Ctrl-C to stop early', file=sys.stderr)

ser = serial.Serial(PORT, BAUD, timeout=0.1)

start = time.perf_counter()
seq = 0
try:
    while time.perf_counter() - start < SECONDS:
        b = ser.read(1)
        if b:
            now_ms = int((time.perf_counter() - start) * 1_000)
            print(seq, now_ms, '%02x' % b[0])
            seq += 1
except KeyboardInterrupt:
    pass
finally:
    ser.close()
