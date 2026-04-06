# =============================================================================
# daktronics.py — Async AllSport 5000 RTD serial parser for MicroPython
#
# Ported from the original Python/pyserial implementation by Alex Riviere.
# RTD packet format:  SYN ... SOH [code] STX [text] EOT [checksum] ETX
#   SYN = 0x16, SOH = 0x01, STX = 0x02, EOT = 0x04, ETX = 0x17
#
# update() is a coroutine so it can yield to the HTTP server between bytes.
# =============================================================================

import uasyncio as asyncio
from machine import UART, Pin


class Daktronics:
    def __init__(self, sport_config, uart_id, rx_pin, tx_pin, baud=19200):
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
        self.sport = sport_config
        self.dak_string = ' ' * self.sport['dakSize'][1]

        self.header   = b''
        self.code     = b''
        self.rtd      = b''
        self.checksum = b''
        self.text     = b''

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
        Read one complete RTD packet and update the internal string buffer.
        Yields between byte reads so the HTTP server stays responsive.
        """
        # 1. Wait for SYN (0x16) — start-of-packet marker
        c = b''
        while c != b'\x16':
            c = await self._read_byte()

        # 2. Collect everything up to ETX (0x17) — end-of-packet
        self.rtd = b''
        c = b'\x16'
        while c != b'\x17':
            c = await self._read_byte()
            self.rtd += c

        # 3. Parse packet fields
        self.header   = self.rtd.partition(b'\x16')[2].partition(b'\x01')[0]
        self.code     = (self.rtd.partition(b'\x01')[2]
                                 .partition(b'\x02')[0]
                                 .partition(b'\x04')[0])
        self.text     = self.rtd.partition(b'\x02')[2].partition(b'\x04')[0]
        self.checksum = self.rtd.partition(b'\x04')[2].partition(b'\x17')[0]

        # 4. Decode and splice text into the positional string buffer
        try:
            code_str = self.code.decode('ascii')
            text_str = self.text.decode('ascii')
            pos = int(code_str[-4:])
            self.dak_string = (
                self.dak_string[:pos]
                + text_str
                + self.dak_string[pos + len(text_str):]
            )
        except (ValueError, UnicodeError):
            pass   # malformed packet — keep previous buffer

    # -------------------------------------------------------------------------
    def __getitem__(self, key):
        """Return the field value for a sport key, using 1-based positions."""
        if key in self.sport:
            start  = self.sport[key][0] - 1      # convert 1-based → 0-based
            length = self.sport[key][1]
            return self.dak_string[start:start + length]
        return ''
