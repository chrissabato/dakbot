# =============================================================================
# main.py — ESP32-S3 Daktronics AllSport 5000 → JSON web server
#
# Reads RTD serial data from a Daktronics AllSport 5000 scoreboard controller,
# parses it into a dict, and serves the current state as JSON over Ethernet.
# A web UI at /settings allows configuration without reflashing.
#
# MicroPython build requirement:
#   The standard ESP32-S3 MicroPython binary does NOT include W5500 support.
#   You need a build compiled with: MICROPY_PY_NETWORK_WIZNET5K=5500
#   Build from source:
#     make BOARD=ESP32_GENERIC_S3 MICROPY_PY_NETWORK_WIZNET5K=5500
#   Verify: import network; print(hasattr(network, 'PHY_W5500'))  # must be True
#
# Flash the following files to the device root (/):
#   main.py, config.py, settings.py, daktronics.py, webserver.py, daksports.json
# =============================================================================

import ujson
import uasyncio as asyncio
from machine import SPI, Pin

import config
import settings
import webserver
from daktronics import Daktronics


# =============================================================================
# Ethernet initialisation
# =============================================================================
def init_ethernet():
    """
    Bring up the W5500 using the ESP32-port network.LAN API.

    IMPORTANT: network.WIZNET5K is the RP2040/Pico API — it does not exist on
    ESP32. The correct API is network.LAN with phy_type=network.PHY_W5500.
    The INT pin is mandatory; the driver is interrupt-driven, not polling.

    For LAN8720 RMII boards (plain ESP32, not S3) swap to:
        nic = network.LAN(mdc=Pin(23), mdio=Pin(18),
                          phy_type=network.PHY_LAN8720, phy_addr=1)
    """
    import network
    import time

    spi = SPI(
        config.SPI_ID,
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
        reset=Pin(config.W5500_RST),    # GPIO9
    )

    nic.active(True)

    s = settings.current
    if s.get('use_dhcp'):
        nic.ifconfig('dhcp')
        for _ in range(30):             # wait up to 15 s for DHCP lease
            if nic.isconnected():
                break
            time.sleep(0.5)
    else:
        nic.ifconfig((
            s.get('ip',      '192.168.1.100'),
            s.get('mask',    '255.255.255.0'),
            s.get('gateway', '192.168.1.1'),
            s.get('dns',     '8.8.8.8'),
        ))

    if nic.isconnected():
        print('Ethernet connected:', nic.ifconfig())
    else:
        print('WARNING: Ethernet not connected — check wiring / settings')

    return nic


# =============================================================================
# Score processing
# =============================================================================
def _outs_display(out_str):
    out_str = out_str.strip()
    if out_str == '3': return '\u26ab\u26ab\u26ab'   # ⚫⚫⚫
    if out_str == '2': return '\u26ab\u26ab\u26aa'   # ⚫⚫⚪
    if out_str == '1': return '\u26ab\u26aa\u26aa'   # ⚫⚪⚪
    if out_str == '0': return '\u26aa\u26aa\u26aa'   # ⚪⚪⚪
    return ''


def _top_bottom(inning_desc):
    return '\u25bc' if 'bot' in inning_desc.lower() else '\u25b2'   # ▼ / ▲


def build_score_dict(dak, sport_config):
    data = {}
    for key in sport_config:
        data[key] = dak[key].strip()

    if 'HomeAtBat' in data:
        data['HomeAtBat'] = data['HomeAtBat'].replace('<', '>')

    ball, strike = data.get('Ball', ''), data.get('Strike', '')
    data['Count'] = '{}-{}'.format(ball, strike) if ball and strike else ''

    data['Outs'] = _outs_display(data.get('Out', ''))

    tb = _top_bottom(data.get('InningDescription', ''))
    data['TB']     = tb
    data['top']    = '\u25b2' if tb == '\u25b2' else ''
    data['bottom'] = '\u25bc' if tb == '\u25bc' else ''

    return data


# =============================================================================
# Async tasks
# =============================================================================
async def serial_reader_task(dak, sport_config):
    """Read RTD packets continuously, yield between bytes for HTTP responsiveness."""
    print('Serial reader started')
    while True:
        try:
            await dak.update()
            new_data = build_score_dict(dak, sport_config)

            # Keep last known non-empty value for fields that report blank mid-packet
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
    # 1. Ethernet (reads network settings from settings.current)
    init_ethernet()

    # 2. Load sport config from flash
    with open('daksports.json') as f:
        all_sports = ujson.load(f)

    sport_name   = settings.current['sport']
    sport_config = all_sports[sport_name]
    print('Sport:', sport_name, ' | RTD buffer:', sport_config['dakSize'][1], 'chars')

    # 3. Initialise the Daktronics serial parser
    dak = Daktronics(
        sport_config,
        uart_id=config.UART_ID,
        rx_pin=settings.current['uart_rx'],
        tx_pin=settings.current.get('uart_tx', 17),
        baud=config.UART_BAUD,
    )

    # 4. Seed score_data so the endpoint always returns valid JSON before first packet
    webserver.score_data = {key: '' for key in sport_config}

    # 5. Run HTTP server and serial reader concurrently
    await webserver.start(port=settings.current.get('http_port', 80))

    tasks = [asyncio.create_task(serial_reader_task(dak, sport_config))]

    # 6. Optionally start MQTT publisher
    if settings.current.get('mqtt_enabled'):
        import mqtt_publisher
        tasks.append(asyncio.create_task(
            mqtt_publisher.run(lambda: webserver.score_data)
        ))
        print('MQTT publisher task started')

    await asyncio.gather(*tasks)


asyncio.run(main())
