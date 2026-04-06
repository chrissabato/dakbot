# dakbot

MicroPython firmware for the **Waveshare ESP32-S3-ETH** that reads live scoreboard data from a **Daktronics AllSport 5000** controller and serves it as JSON over Ethernet.

---

## How it works

The AllSport 5000 continuously broadcasts **RTD (Real Time Data)** packets over a serial port at 19200 baud. Each packet encodes a position and a text value that slots into a fixed-width string buffer. Field names and their byte positions are defined in `daksports.json` for each supported sport.

The ESP32 reads each packet over UART, updates the in-memory scoreboard state, and serves it as JSON on demand via a lightweight HTTP server. No SD card or file writes are needed — data lives in RAM and is always current.

Supported sports: `baseball`, `basketball`, `volleyball`, `football`, `hockeylacrosse`

---

## Hardware

- [Waveshare ESP32-S3-ETH](https://www.waveshare.com/wiki/ESP32-S3-ETH)
- AllSport 5000 RTD serial output → **MAX3232 level shifter** → GPIO16

> The AllSport 5000 outputs RS-232 voltage levels (±12 V). A level shifter such as the MAX3232 is required to convert to the 3.3 V logic the ESP32 expects. Connecting RS-232 directly will damage the board.

### Wiring

| AllSport 5000 | MAX3232 | ESP32-S3-ETH |
|---|---|---|
| RTD TX (RS-232 out) | R1IN | — |
| GND | GND | GND |
| — | R1OUT | GPIO16 (UART RX) |

GPIO17 is configured as UART TX but left unconnected — the AllSport link is receive-only.

### W5500 pins (fixed on-board, do not change)

| Signal | GPIO |
|---|---|
| SCLK | 13 |
| MOSI | 11 |
| MISO | 12 |
| CS | 14 |
| INT | 10 |
| RST | 9 |

---

## MicroPython firmware

The standard ESP32-S3 MicroPython binary does **not** include W5500 support. You need a build compiled with the W5500 driver enabled.

Verify your build in the REPL:

```python
import network
print(hasattr(network, 'PHY_W5500'))   # must print True
```

To build from source:

```bash
make BOARD=ESP32_GENERIC_S3 MICROPY_PY_NETWORK_WIZNET5K=5500
```

---

## Configuration

Edit `config.py` before flashing:

```python
SPORT    = "baseball"   # key from daksports.json

UART_RX  = 16           # GPIO wired to level shifter output
UART_TX  = 17           # unused, leave unconnected

USE_DHCP    = False
STATIC_IP   = '192.168.1.100'
STATIC_MASK = '255.255.255.0'
STATIC_GW   = '192.168.1.1'
STATIC_DNS  = '8.8.8.8'

HTTP_PORT = 80
```

---

## Flashing

Copy all files to the root of the device using `mpremote`, Thonny, or `ampy`:

```bash
mpremote cp config.py :config.py
mpremote cp daktronics.py :daktronics.py
mpremote cp webserver.py :webserver.py
mpremote cp main.py :main.py
mpremote cp daksports.json :daksports.json
```

The board auto-runs `main.py` on power-up.

---

## API

| Endpoint | Response |
|---|---|
| `GET /` | Live scoreboard JSON |
| `GET /data` | Same (alias) |
| `GET /health` | `{"status":"ok"}` |

All responses include `Access-Control-Allow-Origin: *`.

Example response (baseball):

```json
{
    "HomeTeamName": "HOME",
    "AwayTeamName": "GUEST",
    "HomeTeamScore": "9",
    "AwayTeamScore": "4",
    "Inning": "9",
    "InningText": "9TH",
    "InningDescription": "BOT of 9TH",
    "TB": "▼",
    "top": "",
    "bottom": "▼",
    "Ball": "0",
    "Strike": "0",
    "Out": "0",
    "Count": "0-0",
    "Outs": "⚪⚪⚪"
}
```

---

## Files

| File | Purpose |
|---|---|
| `main.py` | Entry point — Ethernet init, async task runner |
| `daktronics.py` | Async RTD serial parser (machine.UART) |
| `webserver.py` | Minimal async HTTP server (uasyncio) |
| `config.py` | Hardware and network settings |
| `daksports.json` | Field name → [position, length] mappings per sport |

---

## Credits

RTD serial parsing based on original work by [Alex Riviere](https://github.com/fimion) — [scoredata](https://github.com/chrisdeely/scoredata).
