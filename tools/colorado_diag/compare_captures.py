#!/usr/bin/env python3
# compare_captures.py — Align and diff two raw-byte captures of the same
# tapped Colorado System 7 console signal (one from capture_dakbot.py, one
# from capture_usb_serial.py) to see whether corrupted bytes are already on
# the wire (both captures agree on the bad bytes -> shared/upstream cause:
# the console itself, or noise common to both taps) or only appear on one
# side (that side's receiver/level-shifting/wiring is the problem).
#
# The two captures are aligned by CONTENT (via difflib), not by their
# timestamps or start time — you don't need to start them in the same
# instant, just with enough overlap.
#
# Usage:
#   python3 compare_captures.py dakbot_capture.log usb_capture.log
#   python3 compare_captures.py dakbot_capture.log usb_capture.log --context 6 --max-diffs 40

import argparse
import difflib


def load_capture(path):
    """Returns (bytes_list, timestamps_us) parsed from a capture log line
    format of '<seq> <ms_since_start> <hex_byte>'."""
    values = []
    times = []
    with open(path) as f:
        for line in f:
            parts = line.split()
            if len(parts) != 3:
                continue
            try:
                us = int(parts[1])
                val = int(parts[2], 16)
            except ValueError:
                continue
            times.append(us)
            values.append(val)
    return values, times


def annotate(values):
    """Mirrors colorado.py's minimal channel/segment bookkeeping (address
    vs data byte, channel select) so each byte in a diff can be reported
    with what it actually addresses, not just its raw hex value."""
    channel = 0
    sub = 0
    show_time = False
    lane_address = False
    out = []
    for b in values:
        if b > 127:
            show_time = not (b > 190)
            lane_address = 169 < b < 190
            sub = b & 0x01
            channel = ((b >> 1) & 0x1f) ^ 0x1f
            out.append('ADDR ch=%d sub=%d show_time=%s lane_addr=%s' %
                        (channel, sub, show_time, lane_address))
        else:
            if sub == 0:
                segment = (b & 0xf0) >> 4
                nibble = b & 0x0f
                if nibble == 0:
                    digit = 'blank'
                else:
                    d = nibble ^ 0x0f
                    digit = str(d) if d <= 9 else 'INVALID(nibble=%d)' % nibble
                out.append('DATA ch=%d seg=%d nibble=%d -> %s' % (channel, segment, nibble, digit))
            else:
                out.append('DATA(sub=1, ignored by decoder) ch=%d' % channel)
    return out


def format_window(values, annotations, times, center, context, highlight=None):
    lo = max(0, center - context)
    hi = min(len(values), center + context + 1)
    lines = []
    for i in range(lo, hi):
        marker = '>>' if i == highlight else '  '
        t = times[i] if i < len(times) else -1
        lines.append('%s [%5d] t=%8dms  %02x  %s' % (marker, i, t, values[i], annotations[i]))
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('capture_a', help='e.g. dakbot_capture.log')
    ap.add_argument('capture_b', help='e.g. usb_capture.log')
    ap.add_argument('--context', type=int, default=4, help='bytes of context around each divergence')
    ap.add_argument('--max-diffs', type=int, default=30, help='stop after reporting this many divergent blocks')
    args = ap.parse_args()

    a_vals, a_times = load_capture(args.capture_a)
    b_vals, b_times = load_capture(args.capture_b)

    print(f'{args.capture_a}: {len(a_vals)} bytes')
    print(f'{args.capture_b}: {len(b_vals)} bytes')

    if not a_vals or not b_vals:
        print('One or both captures are empty — nothing to compare.')
        return

    a_anno = annotate(a_vals)
    b_anno = annotate(b_vals)

    sm = difflib.SequenceMatcher(None, a_vals, b_vals, autojunk=False)
    opcodes = sm.get_opcodes()

    total = len(opcodes)
    equal_bytes = sum((i2 - i1) for tag, i1, i2, j1, j2 in opcodes if tag == 'equal')
    match_ratio = equal_bytes / max(len(a_vals), len(b_vals))
    diff_blocks = [op for op in opcodes if op[0] != 'equal']

    print(f'Match ratio: {match_ratio:.4%}  ({equal_bytes} bytes agree)')
    print(f'Divergent blocks: {len(diff_blocks)}')
    print()

    if not diff_blocks:
        print('No divergences found — the two captures agree byte-for-byte. '
              'Whatever is producing the garbage in dakbot\'s JSON is happening '
              'after the raw bytes are received (i.e. in decode logic), not on the wire.')
        return

    shown = 0
    for tag, i1, i2, j1, j2 in diff_blocks:
        if shown >= args.max_diffs:
            print(f'... {len(diff_blocks) - shown} more divergent blocks not shown (--max-diffs)')
            break
        shown += 1
        print('=' * 78)
        print(f'Divergence #{shown}: {tag}  '
              f'{args.capture_a}[{i1}:{i2}] ({i2 - i1} bytes)  vs  '
              f'{args.capture_b}[{j1}:{j2}] ({j2 - j1} bytes)')
        print(f'-- {args.capture_a} --')
        center_a = i1 if i1 == i2 else (i1 + i2 - 1) // 2
        print(format_window(a_vals, a_anno, a_times, center_a, args.context,
                             highlight=center_a if i2 > i1 else None))
        print(f'-- {args.capture_b} --')
        center_b = j1 if j1 == j2 else (j1 + j2 - 1) // 2
        print(format_window(b_vals, b_anno, b_times, center_b, args.context,
                             highlight=center_b if j2 > j1 else None))
        print()

    print('=' * 78)
    print('How to read this:')
    print('  - If divergent bytes on BOTH sides look like plausible-but-different')
    print('    real data (not just one side blank), the bytes differ upstream of')
    print('    both receivers -- check the console output itself / a shared tap point.')
    print('  - If one side is consistently blank/missing where the other has data')
    print('    (or one side matches known garbage like repeated 0x?b nibbles while')
    print('    the other reads cleanly), that side\'s wiring/level-shifter/receiver')
    print('    is introducing the corruption independently -- focus there.')


if __name__ == '__main__':
    main()
