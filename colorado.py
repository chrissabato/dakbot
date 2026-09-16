# =============================================================================
# colorado.py — Async Colorado System 7 swim-timing console serial parser
#
# Ported from a Raspberry Pi/pyserial reference script (continuous byte-stream
# protocol, no packet framing). Unlike the AllSport 5000's SYN...ETX-delimited
# RTD packets, Colorado System 7 output is a steady stream of display-update
# bytes: address bytes (>127) select a Channel (0-31) and whether the byte
# that follows is data or format, and data bytes (<128) carry one 4-bit
# 7-segment-style nibble, XORed with 0x0F, into a Channel/Segment position of
# an internal display matrix.
#
#   Channel 0        = running main clock
#   Channels 1..lanes = pool lanes (label, place, time)
#   Channel 12       = event / heat number display
#
# update() is a coroutine so it can yield to the HTTP server between bytes.
# It loops internally until a field visible in to_dict() actually changes,
# mirroring Daktronics.update()'s "read until one full packet" idiom.
#
# The original reference script wrote its decoded state to JSON/text files on
# a CIFS-mounted share for a separate, unrelated display pipeline. That
# file-writing/CIFS logic is intentionally dropped here — this module only
# maintains in-memory state, read via to_dict() and served the same way as
# the Daktronics path (in-memory + HTTP JSON + MQTT).
# =============================================================================

import uasyncio as asyncio
from machine import UART, Pin


class Colorado:
    def __init__(self, uart_id, rx_pin, tx_pin, baud=9600, lanes=6):
        self.uart = UART(
            uart_id,
            baudrate=baud,
            rx=Pin(rx_pin),
            tx=Pin(tx_pin),
            bits=8,
            parity=None,
            stop=1,
            timeout=0,        # non-blocking reads; we poll in the coroutine
        )
        self.lanes = lanes

        self._display = [[' '] * 8 for _ in range(32)]   # Display[Channel][Segment]
        self._time    = self._reset_time()                # TIME[0..lanes] = [Label, Place, Time]
        self._clock   = ''                                 # gated, publish-ready running clock

        self._show_time    = False
        self._lane_address = False
        self._sub     = 0
        self._channel = 0
        self._segment = 0

        self.event_number = ''
        self.heat_number  = ''
        self._pending_event_heat = None   # staged (event, heat) awaiting a second, confirming read
        self._ch12_pass    = 0   # incremented on each fresh Channel 12 address byte (166/167/230/231)
        self._pending_pass = -1  # _ch12_pass value when _pending_event_heat was staged

    # -------------------------------------------------------------------------
    def _reset_time(self):
        """Fresh Label/Place/Time rows for a new heat, matching the reference
        script's resetTIME(). Rebuilding index 0 (not a real lane) here too
        is harmless — self._clock (the actually-served Clock) is gated and
        decoupled from this array, so a reset touching it has no external
        effect; the next byte's Running Time block recomputes it anyway."""
        temp = [['', '', ''] for _ in range(self.lanes + 1)]
        for line in range(self.lanes + 1):
            temp[line][0] = str(line)
        return temp

    # -------------------------------------------------------------------------
    async def _read_byte(self):
        """Yield to event loop until one byte arrives, then return it.

        Unlike a framed protocol (see daktronics.py), Colorado System 7
        streams its full display matrix continuously even when nothing
        visible has changed, so bytes are very often already available —
        without the unconditional sleep_ms(0) below, this coroutine would
        never actually suspend during those stretches, and update()'s loop
        (which can run for a full second between exposed-field changes,
        since the console keeps re-sending unchanged digits) would starve
        the HTTP server task for that whole time."""
        while True:
            b = self.uart.read(1)
            if b:
                await asyncio.sleep_ms(0)
                return b
            await asyncio.sleep_ms(1)

    # -------------------------------------------------------------------------
    async def update(self):
        """
        Read and decode bytes until some externally-visible field (clock, a
        lane's label/place/time, or the event/heat number) changes, then
        return. Yields to the event loop on every byte via _read_byte().
        """
        changed = False
        while not changed:
            b = await self._read_byte()
            changed = self._process_byte(b[0])

    # -------------------------------------------------------------------------
    def _process_byte(self, byte_val):
        """Process one raw byte, updating internal state. Returns True if a
        field exposed by to_dict() changed as a result."""
        changed = False

        # ---------------------------------------------------------------
        # Module address byte
        # ---------------------------------------------------------------
        if byte_val > 127:
            self._show_time    = not (byte_val > 190)
            self._lane_address = 169 < byte_val < 190
            self._sub     = byte_val & 0x01
            self._channel = ((byte_val >> 1) & 0x1f) ^ 0x1f
            if self._channel == 12:
                self._ch12_pass += 1

        # ---------------------------------------------------------------
        # Data byte — splice one 4-bit nibble into the display matrix
        # ---------------------------------------------------------------
        if byte_val < 128 and self._sub == 0:
            self._segment = (byte_val & 0xf0) >> 4
            nibble = byte_val & 0x0f
            data = ' ' if nibble == 0x00 else (nibble ^ 0x0f)
            # Only nibbles 6-15 XOR to a valid digit (0-9); 1-5 XOR to
            # 10-14, which isn't a legitimate value for any field this
            # module builds from digit segments (running clock, lane
            # times) — str()'ing it doubles that digit's width for one
            # frame, which is exactly the transient "twice as long" clock
            # glitch this guards against. Blank it instead so a stray
            # nibble just blanks a digit for a frame rather than showing
            # a two-character garbage value.
            if isinstance(data, int) and data > 9:
                data = ' '
            self._display[self._channel][self._segment] = data

        ch = self._channel

        # ---------------------------------------------------------------
        # Blank out lane info after Start or Split display
        # ---------------------------------------------------------------
        if not self._show_time:
            for i in range(1, 8):
                self._display[ch][i] = ' '
            # Matches the reference script (Channel < 7). Reaching ch == 0
            # here is harmless — self._clock is gated/decoupled (see the
            # Running Time block), so clearing self._time[0][2] has no
            # external effect.
            if ch <= self.lanes:
                self._time[ch][2] = ''
                self._time[ch][1] = ''

        if self._lane_address:
            if self._display[ch][0] == ' ':
                for i in range(8):
                    self._display[ch][i] = ' '

        # ---------------------------------------------------------------
        # Event / Heat number (Channel 12)
        # ---------------------------------------------------------------
        if ch == 12:
            # Gate on the last segment of each field (mirrors sec01/ten01
            # below) — without it, a byte that's landed mid-scan (only one
            # of the two digits in event/heat updated so far this pass, or
            # one blanked by the invalid-nibble guard above) reads as a
            # mismatch against the committed number, triggering a spurious
            # reset that wipes every lane/clock field to blank — visible as
            # the whole display flashing to dashes.
            if self._display[12][2] != ' ' and self._display[12][7] != ' ':
                tmp = (
                    (str(self._display[12][1]) + str(self._display[12][2])).strip(),
                    (str(self._display[12][6]) + str(self._display[12][7])).strip(),
                )

                # A misaligned/corrupted byte can decode to a plausible-
                # looking but wrong digit (unlike the out-of-range nibble
                # guard above, this can't be caught by validity checks
                # alone) — briefly showing the wrong event/heat number and,
                # worse, triggering the reset below on bogus data. Require
                # the same value read on two separate scan passes (each
                # marked by its own Channel 12 address byte) before
                # committing it — comparing against the pass number, not
                # just the previous byte, matters because a single corrupt
                # stretch can span several data bytes within the *same*
                # pass, which would otherwise "confirm" itself trivially.
                # A real change naturally repeats on the very next pass
                # (well under a second later); an isolated glitch burst
                # essentially never reproduces the same wrong value again
                # on a later, independent pass.
                if self._ch12_pass == self._pending_pass:
                    self._pending_event_heat = tmp
                elif tmp == self._pending_event_heat:
                    tmp_event, tmp_heat = tmp
                    if self.event_number != tmp_event or self.heat_number != tmp_heat:
                        self.event_number = tmp_event
                        self.heat_number  = tmp_heat
                        self._time = self._reset_time()
                        changed = True
                    self._pending_pass = self._ch12_pass
                else:
                    self._pending_event_heat = tmp
                    self._pending_pass = self._ch12_pass

        # ---------------------------------------------------------------
        # Running Time (Channel 0)
        # ---------------------------------------------------------------
        min10 = str(self._display[0][2])
        min01 = str(self._display[0][3])
        sec10 = str(self._display[0][4])
        sec01 = str(self._display[0][5])
        running_time = self._time[0][2]
        if sec01 != ' ':
            if min01 != ' ':
                running_time = (min10 + min01 + ':' + sec10 + sec01).strip()
            else:
                running_time = (sec10 + sec01).strip()
        if self._time[0][2] != running_time:
            self._time[0][2] = running_time
            # Only ever expose a fully-formed value (no embedded blank from
            # a mid-scan torn read, e.g. one digit not updated yet this
            # pass) as the served Clock — mirrors the reference Raspberry
            # Pi script's `if RunningTime.find(' ') < 0: saveClock(...)`
            # gate. That script tolerates the exact same unguarded decode
            # this module inherited (no nibble validation, no last-segment
            # gate on Channel 12, resets that touch this slot too) because
            # nothing external ever reads the internal value directly —
            # only this gated write actually publishes it. A blank/partial
            # reading here just leaves the last known-good Clock in place.
            if ' ' not in running_time and self._clock != running_time:
                self._clock = running_time
                changed = True

        # ---------------------------------------------------------------
        # Lane Times (Channels 0..lanes)
        # ---------------------------------------------------------------
        # Matches the reference script (0 <= Channel <= 6). Channel 0
        # reaching this block and clearing self._time[0][2] is harmless —
        # self._clock is gated/decoupled from this array (see the Running
        # Time block above), so it's unaffected either way.
        if 0 <= ch <= self.lanes:
            ln = ch
            min10 = str(self._display[ln][2])
            min01 = str(self._display[ln][3])
            sec10 = str(self._display[ln][4])
            sec01 = str(self._display[ln][5])
            ten10 = str(self._display[ln][6])
            ten01 = str(self._display[ln][7])

            if ten01 != ' ':
                if min01 != ' ':
                    tmp = (min10 + min01 + ':' + sec10 + sec01 + '.' + ten10 + ten01).strip()
                else:
                    tmp = (sec10 + sec01 + '.' + ten10 + ten01).strip()

                self._time[ln][0] = str(self._display[ln][0]).strip()
                self._time[ln][1] = str(self._display[ln][1]).strip()
                if self._time[ln][2] != tmp:
                    self._time[ln][2] = tmp
                    changed = True

            if min10 + min01 + sec10 + sec01 + ten10 + ten01 == '      ':
                if self._time[ln][2] != '':
                    self._time[ln][2] = ''
                    changed = True

        return changed

    # -------------------------------------------------------------------------
    def to_dict(self):
        """Flat string-keyed dict, matching dakbot's existing JSON convention."""
        data = {
            'EventNumber': str(self.event_number),
            'HeatNumber':  str(self.heat_number),
            'Clock':       str(self._clock),
        }
        for ln in range(1, self.lanes + 1):
            label, place, time_ = self._time[ln]
            data['Lane{}Label'.format(ln)] = str(label)
            data['Lane{}Place'.format(ln)] = str(place)
            data['Lane{}Time'.format(ln)]  = str(time_)
        return data
