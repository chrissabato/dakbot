# =============================================================================
# config.py — Hardware-only constants for the Waveshare ESP32-S3-ETH
#
# These are fixed by the PCB and should not be changed.
# User-configurable settings (sport, IP, etc.) live in settings.py and are
# persisted to settings.json on the device flash.
#
# Pin assignments verified against the ESP32-S3-ETH schematic:
#   https://files.waveshare.com/wiki/ESP32-S3-ETH/ESP32-S3-ETH-Schematic.pdf
# =============================================================================

# --- UART hardware -----------------------------------------------------------
UART_ID   = 1
UART_BAUD = 19200   # AllSport 5000 RTD fixed baud rate

# --- Ethernet (W5500 via SPI) ------------------------------------------------
# On ESP32-S3, W5500 uses network.LAN(phy_type=network.PHY_W5500, ...).
# network.WIZNET5K is the RP2040/Pico API and does not exist on ESP32.
# The INT pin is required — the driver is interrupt-driven, not polling.
SPI_ID    = 2    # SPI2 (HSPI) — SPI0/1 are reserved for internal flash
SPI_SCK   = 13   # W5500 SCLK
SPI_MOSI  = 11   # W5500 MOSI
SPI_MISO  = 12   # W5500 MISO
W5500_CS  = 14   # W5500 SCSn (chip select)
W5500_RST = 9    # W5500 RSTn (active-low reset)
W5500_INT = 10   # W5500 INTn (interrupt — required by network.LAN driver)
