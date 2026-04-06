# =============================================================================
# main.py — ESP32-S3 Daktronics AllSport 5000 → JSON web server
#
# Reads RTD serial data from a Daktronics AllSport 5000 scoreboard controller,
# parses it into a dict, and serves the current state as JSON over Ethernet.
#
# MicroPython build requirement:
#   The standard ESP32-S3 MicroPython binary does NOT include W5500 support.
#   You need a build compiled with: MICROPY_PY_NETWORK_WIZNET5K=5500
#   Pre-built binaries are available from the MicroPython firmware page, or
#   build from source:
#     make BOARD=ESP32_GENERIC_S3 MICROPY_PY_NETWORK_WIZNET5K=5500
#
# Flash the following files to the device root (/):
#   main.py, config.py, daktronics.py, webserver.py, daksports.json
# =============================================================================

import ujson
import uasyncio as asyncio
from machine import SPI, Pin

import config
import webserver
from daktronics import Daktronics


# =============================================================================
# Ethernet initialisation
# =============================================================================
def init_ethernet():
    """
    Bring up the W5500 Ethernet chip using the ESP32-port network.LAN API.

    IMPORTANT: network.WIZNET5K is the RP2040/Pico API and does NOT exist on
    ESP32. The correct ESP32 API is network.LAN with phy_type=network.PHY_W5500.
    The INT pin is mandatory for this driver.

    For LAN8720 RMII boards (plain ESP32, not S3) use instead:
        nic = network.LAN(mdc=Pin(23), mdio=Pin(18),
                          phy_type=network.PHY_LAN8720, phy_addr=1)
    """
    import network
    import time

    spi = SPI(
        config.SPI_ID,              # SPI2 — SPI0/1 reserved for internal flash
        baudrate=40_000_000,
        sck=Pin(config.SPI_SCK),    # GPIO13
        mosi=Pin(config.SPI_MOSI),  # GPIO11
        miso=Pin(config.SPI_MISO),  # GPIO12
    )

    nic = network.LAN(
        spi=spi,
        phy_type=network.PHY_W5500,
        phy_addr=0,                     # always 0 for SPI-based W5500
        cs=Pin(config.W5500_CS),        # GPIO14
        int=Pin(config.W5500_INT),      # GPIO10 — required by driver
        reset=Pin(config.W5500_RST),    # GPIO9  — optional but recommended
    )

    nic.active(True)

    if config.USE_DHCP:
        nic.ifconfig('dhcp')
        for _ in range(30):             # wait up to 15 s for DHCP lease
            if nic.isconnected():
                break
            time.sleep(0.5)
    else:
        nic.ifconfig((
            config.STATIC_IP,
            config.STATIC_MASK,
            config.STATIC_GW,
            config.STATIC_DNS,
        ))

    if nic.isconnected():
        print('Ethernet connected:', nic.ifconfig())
    else:
        print('WARNING: Ethernet not connected — check wiring / config')

    return nic


# =============================================================================
# Score processing  (baseball-specific derived fields)
# =============================================================================
def _outs_display(out_str):
    out_str = out_str.strip()
    if out_str == '3': return '\u26ab\u26ab\u26ab'   # ⚫⚫⚫
    if out_str == '2': return '\u26ab\u26ab\u26aa'   # ⚫⚫⚪
    if out_str == '1': return '\u26ab\u26aa\u26aa'   # ⚫⚪⚪
    if out_str == '0': return '\u26aa\u26aa\u26aa'   # ⚪⚪⚪
    return ''


def _top_bottom(inning_desc):
    if 'bot' in inning_desc.lower():
        return '\u25bc'   # ▼
    return '\u25b2'       # ▲


def build_score_dict(dak, sport_config):
    """
    Extract all sport fields from the dak buffer, add derived baseball fields,
    and return a plain dict suitable for JSON serialisation.
    """
    data = {}
    for key in sport_config:
        data[key] = dak[key].strip()

    # --- Derived baseball fields (safe to compute for other sports too) ------
    if 'HomeAtBat' in data:
        data['HomeAtBat'] = data['HomeAtBat'].replace('<', '>')

    ball   = data.get('Ball', '')
    strike = data.get('Strike', '')
    if ball and strike:
        data['Count'] = f'{ball}-{strike}'
    else:
        data['Count'] = ''

    out_val = data.get('Out', '')
    data['Outs'] = _outs_display(out_val)

    inning_desc = data.get('InningDescription', '')
    tb = _top_bottom(inning_desc)
    data['TB']     = tb
    data['top']    = '\u25b2' if tb == '\u25b2' else ''
    data['bottom'] = '\u25bc' if tb == '\u25bc' else ''

    return data


# =============================================================================
# Async tasks
# =============================================================================
async def serial_reader_task(dak, sport_config):
    """
    Continuously read RTD packets and update the shared score_data dict.
    Yields to the event loop between bytes so the HTTP server stays live.
    """
    print('Serial reader started')
    while True:
        try:
            await dak.update()
            new_data = build_score_dict(dak, sport_config)

            # Merge: keep last known non-empty values for fields that may
            # temporarily report blank (mirrors original scorebug.py logic)
            for key, val in new_data.items():
                if key not in ('AwayAtBat', 'HomeAtBat'):
                    if val == '' and key in webserver.score_data:
                        new_data[key] = webserver.score_data[key]

            webserver.score_data.update(new_data)

        except Exception as e:
            print('Serial reader error:', e)
            await asyncio.sleep_ms(500)


# =============================================================================
# Entry point
# =============================================================================
async def main():
    # 1. Ethernet
    init_ethernet()

    # 2. Load sport config from flash
    with open('daksports.json') as f:
        all_sports = ujson.load(f)

    sport_name   = config.SPORT
    sport_config = all_sports[sport_name]
    print(f'Sport: {sport_name}  |  RTD buffer size: {sport_config["dakSize"][1]} chars')

    # 3. Initialise the Daktronics parser
    dak = Daktronics(
        sport_config,
        uart_id=config.UART_ID,
        rx_pin=config.UART_RX,
        tx_pin=config.UART_TX,
        baud=config.UART_BAUD,
    )

    # 4. Seed score_data with blank values so the endpoint always returns valid JSON
    webserver.score_data = {key: '' for key in sport_config}

    # 5. Start HTTP server and serial reader concurrently
    await webserver.start(port=config.HTTP_PORT)
    await serial_reader_task(dak, sport_config)   # runs forever


asyncio.run(main())
