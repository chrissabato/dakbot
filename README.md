# dakbot

MicroPython firmware for the **Waveshare ESP32-S3-ETH** that reads live scoreboard data from a **Daktronics AllSport 5000** controller and serves it as JSON over Ethernet.

---

## How it works

The AllSport 5000 continuously broadcasts **RTD (Real Time Data)** packets over a serial port at 19200 baud. Each packet encodes a position and a text value that slots into a fixed-width string buffer. Field names and their byte positions are defined in `daksports.json` for each supported sport.

The ESP32 reads each packet over UART, updates the in-memory scoreboard state, and serves it as JSON on demand via a lightweight HTTP server. No SD card or file writes are needed — data lives in RAM and is always current.

Supported sports: `baseball`, `basketball`, `volleyball`, `football`, `hockeylacrosse`

---

## Hardware

- [Waveshare ESP32-S3-ETH](https://a.co/d/0aZ7pFHl)
- [MAX3232 level shifter](https://a.co/d/0iYqtyU6)
- AllSport 5000 RTD serial output → MAX3232 level shifter → GPIO16

> The AllSport 5000 outputs RS-232 voltage levels (±12 V). A level shifter such as the MAX3232 is required to convert to the 3.3 V logic the ESP32 expects. Connecting RS-232 directly will damage the board.

### Serial cable

The AllSport 5000 has a DB25 male RTD output. Wire it to a DB9 female connector for a standard MAX3232 module:

| AllSport 5000 DB25 Male | DB9 Female | Signal |
|---|---|---|
| Pin 7 | Pin 5 | GND |
| Pin 2 | Pin 3 | TX → RX |
| Pin 3 | Pin 2 | RX → TX (unused — receive only) |

### ESP Wiring

| MAX3232 | ESP32-S3-ETH |
|---|---|
| ACC | 3V3 |
| GND | GND |
| R1OUT | GPIO16 (UART RX) |
| R1IN | — |

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

## Installation

### 1. Install tools

Requires Python 3.

```bash
pip install esptool mpremote
```

### 2. Download MicroPython firmware

Go to **https://micropython.org/download/ESP32_GENERIC_S3/** and download the latest `.bin` file.

### 3. Put the board in bootloader mode

1. Hold the **BOOT** button
2. Press and release **RESET**
3. Release **BOOT**

The board will appear as a serial port:
- **Windows:** `COM3`, `COM4`, etc. — check Device Manager
- **Mac:** `/dev/cu.usbmodem*` or `/dev/cu.usbserial*`
- **Linux:** `/dev/ttyACM0` or `/dev/ttyUSB0`

### 4. Flash the firmware

Replace `PORT` with your port and `FIRMWARE.bin` with the filename you downloaded:

```bash
esptool.py --chip esp32s3 --port PORT erase_flash
esptool.py --chip esp32s3 --port PORT write_flash -z 0 FIRMWARE.bin
```

Press **RESET** after flashing.

### 5. Verify W5500 support

```bash
mpremote connect PORT
```

At the `>>>` prompt:

```python
import network
print(hasattr(network, 'PHY_W5500'))   # must print True
```

Press `Ctrl+X` to exit. If it prints `False`, try the `ESP32_GENERIC_S3-SPIRAM` variant from the same download page.

### 6. Copy the project files

From inside the `dakbot` repo folder, use the included script:

```bash
./flash.sh PORT
```

Replace `PORT` with your serial port (e.g. `/dev/ttyACM0`). The script copies all required files and exits with an error if any transfer fails.

### 7. Boot and verify

Press **RESET**. Connect to the REPL to see startup output:

```
Settings loaded from settings.json
Ethernet connected: ('192.168.x.x', '255.255.255.0', ...)
Sport: baseball | RTD buffer: 343 chars
HTTP server listening on port 80
Serial reader started
```

Open `http://<ip-shown-above>/settings` in a browser to confirm the UI is up.

---

## Configuration

User settings (sport, network, UART RX pin) are managed through the web UI at `/settings` and stored in `settings.json` on the device. Default values are defined in `settings.py`.

`config.py` contains only hardware pin constants fixed by the PCB — these should not need to change.

---

## Flashing updated code

After the initial install, copy individual changed files with `mpremote`:

```bash
mpremote connect PORT cp main.py :main.py
```

`settings.json` lives only on the device and is not overwritten by copying project files.

---

## Settings UI

Navigate to `http://<device-ip>/settings` to configure the device without reflashing.

| Setting | Notes |
|---|---|
| Sport | Updates field mapping immediately on next reboot |
| DHCP / Static IP | Reboot required |
| HTTP Port | Reboot required |
| UART RX Pin | GPIO wired to the MAX3232 output — reboot required |
| MQTT Enable | Toggle MQTT publishing — reboot required |
| MQTT Broker | Hostname of the MQTT broker (TLS port 8883) |
| MQTT Topic | Topic to publish score data to (default: `dakbot/score`) |

Settings are persisted to `settings.json` on the device flash and survive reboots. Hardware pin constants (W5500 SPI lines, UART baud) stay in `config.py` and require reflashing to change.

---

## API

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Live scoreboard JSON |
| `/data` | GET | Same (alias) |
| `/health` | GET | `{"status":"ok"}` |
| `/settings` | GET | Settings UI (HTML) |
| `/settings` | POST | Save settings to flash |
| `/reboot` | POST | Reboot device |

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
| `mqtt_publisher.py` | Optional async MQTT publisher (TLS, port 8883) |
| `index.html` | Browser scoreboard — connects via MQTT WebSocket (WSS, port 8884); hosted at [chrissabato.github.io/dakbot](https://chrissabato.github.io/dakbot) |
| `config.py` | Hardware pin constants (PCB-fixed, do not change) |
| `settings.py` | Persistent user settings — loads/saves `settings.json` on flash |
| `daksports.json` | Field name → [position, length] mappings per sport |

---

## MQTT / Public scoreboard

Enable MQTT in the `/settings` UI to push live scores to any MQTT broker. The browser client (`client.html`) connects to the same broker via WebSocket and displays the scoreboard in real time.

### Quick setup with HiveMQ Cloud (free tier)

1. Create a free cluster at [hivemq.com](https://www.hivemq.com/mqtt-cloud-broker/) — 10 connections, unlimited messages.
2. Create two credentials: one for the ESP32 (publish), one for the browser (subscribe-only).
3. In the Dakbot settings UI:
   - Enable MQTT
   - Broker: `xxxx.s1.eu.hivemq.cloud` (your cluster hostname)
   - Port: `8883` (TLS)
   - Fill in the ESP32 username/password
   - Topic: `dakbot/score` (or any string)
4. Install `umqtt.simple` on the device (one-time):
   ```bash
   mpremote connect PORT mip install umqtt.simple
   ```
5. Open `client.html` in any browser, enter the broker hostname, WSS port `8884`, and the browser credential.

The ESP32 publishes with `retain=True`, so late-joining browsers immediately receive the current score.

---

## Credits

RTD serial parsing based on original work by [Alex Riviere](https://github.com/fimion) — [scoredata](https://github.com/chrisdeely/scoredata).
