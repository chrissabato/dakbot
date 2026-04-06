# =============================================================================
# config.py — Hardware configuration for Waveshare ESP32-S3-ETH
#
# Pin assignments verified against the ESP32-S3-ETH schematic:
#   https://files.waveshare.com/wiki/ESP32-S3-ETH/ESP32-S3-ETH-Schematic.pdf
# =============================================================================

# --- Sport selection ---------------------------------------------------------
# Must match a top-level key in daksports.json:
#   "baseball", "basketball", "volleyball", "football", "hockeylacrosse"
SPORT = "baseball"

# --- UART (serial) -----------------------------------------------------------
# Connect the AllSport 5000 RTD output to RX below.
# TX is unused (AllSport is one-way) but machine.UART requires a TX pin.
# GPIO16 and GPIO17 are free header pins not reserved by W5500 or USB.
# AllSport 5000 serial spec: 19200 baud, 8N1, no flow control.
UART_ID   = 1
UART_RX   = 16   # GPIO16 — wire to AllSport 5000 RTD serial output
UART_TX   = 17   # GPIO17 — unused, leave unconnected
UART_BAUD = 19200

# --- Ethernet (W5500 via SPI) ------------------------------------------------
# Pin assignments from the ESP32-S3-ETH schematic — do not change.
#
# On ESP32/S3, MicroPython uses network.LAN(phy_type=network.PHY_W5500, ...)
# NOT network.WIZNET5K (that API is RP2040/Pico only).
# The INT pin is REQUIRED by the network.LAN driver.
SPI_ID    = 2    # Use SPI2 (HSPI); SPI0/1 are reserved for internal flash
SPI_SCK   = 13   # W5500 SCLK
SPI_MOSI  = 11   # W5500 MOSI
SPI_MISO  = 12   # W5500 MISO
W5500_CS  = 14   # W5500 SCSn (chip select)
W5500_RST = 9    # W5500 RSTn (active-low reset)
W5500_INT = 10   # W5500 INTn — required by network.LAN driver

# Static IP config — set USE_DHCP = True to use DHCP instead.
USE_DHCP    = False
STATIC_IP   = '192.168.1.100'
STATIC_MASK = '255.255.255.0'
STATIC_GW   = '192.168.1.1'
STATIC_DNS  = '8.8.8.8'

# --- Web server --------------------------------------------------------------
HTTP_PORT = 80
