# dakbot

Reads live scoreboard data from a **Daktronics AllSport 5000** controller over its RTD serial port and makes it available as JSON.

Two implementations are included:

| Directory | Platform | Output |
|---|---|---|
| *(root)* | Python 3 / any PC | `ScoreBoardData.json` written to disk |
| `esp32/` | MicroPython on Waveshare ESP32-S3-ETH | JSON served over HTTP on local network |

---

## How it works

The AllSport 5000 continuously broadcasts **RTD (Real Time Data)** packets over a serial port at 19200 baud. Each packet encodes a position and a text value that slots into a fixed-width string buffer. Field names and their positions within that buffer are defined in `daksports.json` for each supported sport.

Supported sports: `baseball`, `basketball`, `volleyball`, `football`, `hockeylacrosse`

---

## Python (PC) version

### Requirements

```
pip install pyserial
```

### Configuration

Edit `settings.json`:

```json
{
    "COM_PORT": "COM1",
    "SPORT": "baseball"
}
```

On Linux/Mac the port will be something like `/dev/ttyUSB0`.

### Usage

```bash
# Normal run
python scorebug.py

# Reset ScoreBoardData.json to blank defaults first
python scorebug.py -init
```

The script prints an ASCII scoreboard to the terminal whenever data changes and keeps `ScoreBoardData.json` updated with the latest values.

---

## ESP32-S3 version (Waveshare ESP32-S3-ETH)

### Hardware

- [Waveshare ESP32-S3-ETH](https://www.waveshare.com/wiki/ESP32-S3-ETH) development board
- Onboard W5500 Ethernet chip (SPI)
- AllSport 5000 RTD serial output → **MAX3232 level shifter** → ESP32 UART RX

> The AllSport 5000 outputs RS-232 voltage levels (±12 V). A level shifter such as the MAX3232 is required to convert to the 3.3 V logic the ESP32 expects. Connecting RS-232 directly will damage the board.

### Wiring

**AllSport 5000 → level shifter → ESP32-S3-ETH**

| AllSport 5000 | MAX3232 | ESP32-S3-ETH |
|---|---|---|
| RTD TX (RS-232 out) | R1IN | — |
| GND | GND | GND |
| — | R1OUT | GPIO16 (UART RX) |

GPIO17 is configured as UART TX but left unconnected — the AllSport link is receive-only.

**W5500 pins** (fixed on-board, do not change):

| Signal | GPIO |
|---|---|
| SCLK | 13 |
| MOSI | 11 |
| MISO | 12 |
| CS | 14 |
| INT | 10 |
| RST | 9 |

### MicroPython firmware

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

### Configuration

Edit `esp32/config.py` before flashing:

```python
SPORT    = "baseball"   # sport key from daksports.json

UART_RX  = 16           # GPIO wired to level shifter output
UART_TX  = 17           # unused, leave unconnected

USE_DHCP    = False      # True for DHCP, False for static IP
STATIC_IP   = '192.168.1.100'
STATIC_MASK = '255.255.255.0'
STATIC_GW   = '192.168.1.1'
STATIC_DNS  = '8.8.8.8'

HTTP_PORT = 80
```

### Flashing

Copy all five files to the root of the device using `mpremote`, Thonny, or `ampy`:

```
esp32/config.py       → /config.py
esp32/daktronics.py   → /daktronics.py
esp32/webserver.py    → /webserver.py
esp32/main.py         → /main.py
esp32/daksports.json  → /daksports.json
```

Example with `mpremote`:

```bash
mpremote cp esp32/config.py :config.py
mpremote cp esp32/daktronics.py :daktronics.py
mpremote cp esp32/webserver.py :webserver.py
mpremote cp esp32/main.py :main.py
mpremote cp esp32/daksports.json :daksports.json
```

The board auto-runs `main.py` on power-up.

### API

| Endpoint | Response |
|---|---|
| `GET /` | Live scoreboard JSON |
| `GET /data` | Same (alias) |
| `GET /health` | `{"status":"ok"}` |

All responses include `Access-Control-Allow-Origin: *` so the data can be consumed directly from a browser or any frontend.

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
    "Outs": "⚪⚪⚪",
    ...
}
```

---

## File reference

```
dakbot/
├── daktronics.py          # Python RTD serial parser (pyserial)
├── scorebug.py            # PC main loop — reads serial, writes JSON, prints scoreboard
├── daksports.json         # Field name → [position, length] mappings for each sport
├── settings.json          # PC config: COM port and sport selection
├── ScoreBoardData.json    # Last known good scoreboard state (PC version)
└── esp32/
    ├── main.py            # ESP32 entry point — Ethernet init, async task runner
    ├── daktronics.py      # Async RTD parser using machine.UART
    ├── webserver.py       # Minimal async HTTP server (uasyncio)
    ├── config.py          # ESP32 hardware and network settings
    └── daksports.json     # Same sport config, copied to device flash
```

---

## Credits

RTD serial parsing based on original work by [Alex Riviere](https://github.com/fimion) — [scoredata](https://github.com/chrisdeely/scoredata).
