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

        self._show_time    = False
        self._lane_address = False
        self._sub     = 0
        self._channel = 0
        self._segment = 0

        self.event_number = ''
        self.heat_number  = ''

    # -------------------------------------------------------------------------
    def _reset_time(self):
        temp = [['', '', ''] for _ in range(self.lanes + 1)]
        for line in range(self.lanes + 1):
            temp[line][0] = str(line)
        return temp

    # -------------------------------------------------------------------------
    async def _read_byte(self):
        """Yield to event loop until one byte arrives, then return it."""
        while True:
            b = self.uart.read(1)
            if b:
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

        # ---------------------------------------------------------------
        # Data byte — splice one 4-bit nibble into the display matrix
        # ---------------------------------------------------------------
        if byte_val < 128 and self._sub == 0:
            self._segment = (byte_val & 0xf0) >> 4
            data = (byte_val << 4) & 0xf0
            data >>= 4
            data = ' ' if data == 0x00 else (data ^ 0x0f)
            self._display[self._channel][self._segment] = data

        ch = self._channel

        # ---------------------------------------------------------------
        # Blank out lane info after Start or Split display
        # ---------------------------------------------------------------
        if not self._show_time:
            for i in range(1, 8):
                self._display[ch][i] = ' '
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
            tmp_event = (str(self._display[12][1]) + str(self._display[12][2])).strip()
            tmp_heat  = (str(self._display[12][6]) + str(self._display[12][7])).strip()

            if self.event_number != tmp_event or self.heat_number != tmp_heat:
                self.event_number = tmp_event
                self.heat_number  = tmp_heat
                self._time = self._reset_time()
                changed = True

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
            changed = True

        # ---------------------------------------------------------------
        # Lane Times (Channels 0..lanes)
        # ---------------------------------------------------------------
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
            'Clock':       str(self._time[0][2]),
        }
        for ln in range(1, self.lanes + 1):
            label, place, time_ = self._time[ln]
            data['Lane{}Label'.format(ln)] = str(label)
            data['Lane{}Place'.format(ln)] = str(place)
            data['Lane{}Time'.format(ln)]  = str(time_)
        return data
