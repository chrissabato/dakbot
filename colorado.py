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
            # MicroPython's default UART rx buffer is small. mqtt_publisher.py
            # calls into umqtt.simple, a synchronous library that does
            # blocking socket/TLS I/O with no await yielding — on this
            # single-threaded cooperative scheduler, that stalls every other
            # task, including this one, for however long a publish/connect
            # takes. At ~960 bytes/sec of continuous Colorado traffic, even a
            # few tens of milliseconds of that can overflow a small buffer.
            # A dedicated reference script with nothing else competing for
            # CPU time never sees this; give real headroom here instead.
            rxbuf=4096,
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
        self._pending_pass = -1            # channel-12 pass when _pending_event_heat was staged

        # Incremented per-channel on each fresh address byte selecting that
        # channel — lets a value be confirmed against an independent later
        # scan pass, not just a later byte (several data bytes typically
        # follow one address byte within the same pass).
        self._chan_pass = [0] * 32

        # Whether each lane has been observed fully blank since the last
        # heat reset. True at startup (self._time is already blank, so
        # there's nothing to wait for); a heat change sets its lane back
        # to False until a genuine all-blank read is seen. This alone
        # isn't sufficient protection (a transitional blank can itself be
        # part of the same in-flux window as the garbage that follows it),
        # so it's paired with the same pass-confirmation used for lanes
        # below and already used for event/heat.
        self._lane_seen_blank  = [True] * (self.lanes + 1)
        self._lane_pending     = [None] * (self.lanes + 1)
        self._lane_pending_pass = [-1] * (self.lanes + 1)

        # Label/Place pending state — separate from _lane_pending above
        # (Time), since they're confirmed on their own trigger (segment 1)
        # independent of whether a time is present. See the Label + Place
        # block in _process_byte for why they need their own gate.
        self._lane_lp_pending      = [None] * (self.lanes + 1)
        self._lane_lp_pending_pass = [-1] * (self.lanes + 1)

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
    async def update(self):
        """
        Read and decode bytes until some externally-visible field (clock, a
        lane's label/place/time, or the event/heat number) changes, then
        return.

        Reads every byte currently sitting in the UART's buffer in one
        uart.read(n) call and processes them in a tight loop, yielding only
        once every 64 bytes rather than after each individual byte. An
        earlier version yielded via asyncio.sleep_ms(0) after every single
        byte, on the reasoning that Colorado System 7 streams continuously
        (bytes are almost always already available), so without yielding
        this coroutine would never actually suspend and would starve the
        HTTP server / MQTT publisher tasks. That reasoning about needing to
        yield was right, but yielding on every byte went too far the other
        way: confirmed live, at ~960 bytes/sec (9600 baud) the scheduler
        round-trip cost of a yield-and-reschedule on every single byte is
        itself slower than bytes arrive, so this task could never keep up
        once any other task existed to compete for the rescheduling slot —
        the UART's receive buffer was measured climbing to its full 4096-byte
        cap and staying pinned there, tracking whole seconds behind
        real time. Batching the read and yielding periodically instead
        keeps the same fairness (still yields regularly, still bounded
        per-batch by rxbuf) while cutting the number of yields ~64x.
        """
        changed = False
        while not changed:
            avail = self.uart.any()
            if avail:
                chunk = self.uart.read(avail)
                if chunk:
                    for i, byte_val in enumerate(chunk):
                        if self._process_byte(byte_val):
                            changed = True
                        if i % 64 == 63:
                            await asyncio.sleep_ms(0)
                await asyncio.sleep_ms(0)
            else:
                await asyncio.sleep_ms(1)

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
            self._chan_pass[self._channel] += 1

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
                pass_now = self._chan_pass[12]
                if pass_now == self._pending_pass:
                    self._pending_event_heat = tmp
                elif tmp == self._pending_event_heat:
                    tmp_event, tmp_heat = tmp
                    if self.event_number != tmp_event or self.heat_number != tmp_heat:
                        self.event_number = tmp_event
                        self.heat_number  = tmp_heat
                        self._time = self._reset_time()
                        # Require each lane to be observed properly blank,
                        # and its next reading independently reconfirmed,
                        # before trusting new data for it — whatever the
                        # console sends in the gap right after a heat
                        # change, before it's ready with real per-lane
                        # data, shouldn't be displayed as if it were real.
                        self._lane_seen_blank   = [False] * (self.lanes + 1)
                        self._lane_pending      = [None] * (self.lanes + 1)
                        self._lane_pending_pass = [-1] * (self.lanes + 1)
                        self._lane_lp_pending      = [None] * (self.lanes + 1)
                        self._lane_lp_pending_pass = [-1] * (self.lanes + 1)
                        changed = True
                    self._pending_pass = pass_now
                else:
                    self._pending_event_heat = tmp
                    self._pending_pass = pass_now

        # ---------------------------------------------------------------
        # Running Time (Channel 0)
        # ---------------------------------------------------------------
        min10 = str(self._display[0][2])
        min01 = str(self._display[0][3])
        sec10 = str(self._display[0][4])
        sec01 = str(self._display[0][5])
        running_time = self._time[0][2]
        # Gate on having just written segment 5 (sec01) — the last of the
        # 4 segments (min10, min01, sec10, sec01) that make up the clock,
        # sent in that order every pass. Without this, the block below
        # re-evaluates on *every* byte, including mid-write while only
        # some of those 4 segments have this pass's fresh digits and the
        # rest still hold the previous pass's — e.g. min10/min01 freshly
        # rewritten but sec10/sec01 not yet, or vice versa. That torn mix
        # committing as a real reading is confirmed live: a real update
        # visibly went through the exact sequence '44:40' -> '44:44' ->
        # '4:44' -> '44', one spurious commit per segment write, before
        # settling. Lanes and event/heat already gate on their own last
        # segment for exactly this reason; Clock never got the same
        # treatment. Unlike sec01, sec10 is NOT required to be present —
        # confirmed live, the console legitimately blanks tens-of-seconds
        # under 10 real seconds, same as it blanks tens-of-minutes under
        # 10 minutes (e.g. a freshly reset "0:00" reads sec10=' ',
        # sec01='0'). An earlier version of this gate required sec10 too,
        # reasoning it could never be legitimately blank — which was
        # itself a mitigation for a torn-read bug whose real cause (UART
        # byte loss under scheduling load) is now fixed properly, and
        # that extra requirement was left behind permanently blocking any
        # sub-10-second reading, including every reset, from ever
        # publishing.
        if ch == 0 and self._segment == 5 and sec01 != ' ':
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

            # Label + Place (segments 0, 1) are sent every refresh cycle
            # regardless of whether this lane currently has a time —
            # unlike Time below, which only appears once a finish comes
            # in. Gating them on Time's own trigger (as both the
            # reference script and an earlier version of this module did)
            # meant a lane with no time yet this heat — the normal
            # pre-race state for every lane — never had its Label/Place
            # read at all, leaving them frozen at whatever _reset_time()
            # last initialized them to. Confirmed live: Lane1Label stayed
            # stuck at "1" indefinitely instead of reflecting the console
            # (e.g. going blank when a lane is disabled/off). Segment 1
            # (place) is the byte immediately after segment 0 (label) in
            # transmission order, so triggering on it guarantees label
            # was already freshly written this same pass.
            if self._segment == 1:
                label = str(self._display[ln][0]).strip()
                place = str(self._display[ln][1]).strip()
                lp_reading = (label, place)
                lp_pass_now = self._chan_pass[ln]
                if lp_pass_now == self._lane_lp_pending_pass[ln]:
                    self._lane_lp_pending[ln] = lp_reading
                elif lp_reading == self._lane_lp_pending[ln]:
                    if self._time[ln][0] != label:
                        self._time[ln][0] = label
                        changed = True
                    if self._time[ln][1] != place:
                        self._time[ln][1] = place
                        changed = True
                    self._lane_lp_pending_pass[ln] = lp_pass_now
                else:
                    self._lane_lp_pending[ln] = lp_reading
                    self._lane_lp_pending_pass[ln] = lp_pass_now

            min10 = str(self._display[ln][2])
            min01 = str(self._display[ln][3])
            sec10 = str(self._display[ln][4])
            sec01 = str(self._display[ln][5])
            ten10 = str(self._display[ln][6])
            ten01 = str(self._display[ln][7])

            # sec10 is NOT required to be present, even though a blank
            # there sits at position 0 of the min01==' ' branch's string
            # and gets silently eaten by .strip() below — confirmed live,
            # sec10 is legitimately blank for any real time under 10
            # seconds (e.g. a lane time of "4.44" genuinely has sec10
            # blank), the same way min10 is legitimately blank under 10
            # minutes. An earlier version required it, reasoning a torn
            # read was the only way it could be blank; that reasoning
            # doesn't hold once you allow for real sub-10-second times,
            # and the real torn-read protection here is the two-pass
            # cross-confirmation below (and the ' ' not in tmp check),
            # not this.
            if ten01 != ' ':
                if min01 != ' ':
                    tmp = (min10 + min01 + ':' + sec10 + sec01 + '.' + ten10 + ten01).strip()
                else:
                    tmp = (sec10 + sec01 + '.' + ten10 + ten01).strip()
            else:
                tmp = None

            # Reject any remaining internal blank (e.g. a torn ten10) — this
            # module's own equivalent of the Running Time block's "fully-
            # formed value" gate, which lane times never had.
            if tmp is not None and ' ' not in tmp:
                # Don't trust a non-blank reading until this lane has been
                # seen properly blank since the last heat reset — but that
                # alone isn't enough: the console's own internal state can
                # race its serial output, so a channel mid-write at the
                # exact moment of a heat transition can briefly reflect a
                # blank-then-garbage sequence as one continuous in-flux
                # window (reported as "44", "44.44", "44:44.44" landing on
                # whichever lane happened to be mid-scan). So also require
                # the value to be confirmed on an independent later pass
                # (its own address byte), the same protection already
                # applied to event/heat above.
                if self._lane_seen_blank[ln]:
                    pass_now = self._chan_pass[ln]
                    if pass_now == self._lane_pending_pass[ln]:
                        self._lane_pending[ln] = tmp
                    elif tmp == self._lane_pending[ln]:
                        if self._time[ln][2] != tmp:
                            self._time[ln][2] = tmp
                            changed = True
                        self._lane_pending_pass[ln] = pass_now
                    else:
                        self._lane_pending[ln] = tmp
                        self._lane_pending_pass[ln] = pass_now

            if min10 + min01 + sec10 + sec01 + ten10 + ten01 == '      ':
                self._lane_seen_blank[ln] = True
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
