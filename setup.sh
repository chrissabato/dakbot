#!/bin/bash
# setup.sh — Full setup of a blank ESP32-S3-ETH: install tools, flash MicroPython,
# verify W5500 support, and copy the dakbot project files.
#
# Usage:
#   ./setup.sh PORT
#
# Example:
#   ./setup.sh /dev/ttyACM0

set -e

PORT=${1:?"Usage: $0 PORT   (e.g. $0 /dev/ttyACM0)"}
FIRMWARE_DIR="/tmp/dakbot-firmware"
FILES="config.py settings.py daktronics.py colorado.py webserver.py mqtt_publisher.py updater.py version.py main.py daksports.json"

# 1. Install tools
echo "==> Checking for esptool and mpremote..."
if ! command -v esptool.py >/dev/null 2>&1 || ! command -v mpremote >/dev/null 2>&1; then
    pip install esptool mpremote
else
    echo "    already installed."
fi

# 2. Download latest stable MicroPython firmware for ESP32_GENERIC_S3
echo "==> Finding latest MicroPython firmware for ESP32_GENERIC_S3..."
mkdir -p "$FIRMWARE_DIR"
FIRMWARE_PATH=$(ls "$FIRMWARE_DIR"/ESP32_GENERIC_S3-*.bin 2>/dev/null | sort | tail -n1)
if [ -z "$FIRMWARE_PATH" ]; then
    FIRMWARE_URL=$(curl -s https://micropython.org/download/ESP32_GENERIC_S3/ \
        | grep -oE 'href="/resources/firmware/ESP32_GENERIC_S3-[0-9]{8}-v[0-9.]+\.bin"' \
        | grep -v SPIRAM \
        | head -n1 \
        | sed -E 's/href="(.*)"/\1/')
    if [ -z "$FIRMWARE_URL" ]; then
        echo "ERROR: could not find a firmware download link on micropython.org"
        exit 1
    fi
    FIRMWARE_PATH="$FIRMWARE_DIR/$(basename "$FIRMWARE_URL")"
    echo "    downloading https://micropython.org$FIRMWARE_URL"
    curl -s -o "$FIRMWARE_PATH" "https://micropython.org$FIRMWARE_URL"
else
    echo "    using cached $FIRMWARE_PATH"
fi

# 3. Bootloader mode
echo ""
echo "==> Put the board in bootloader mode:"
echo "    1. Hold the BOOT button"
echo "    2. Press and release RESET"
echo "    3. Release BOOT"
read -rp "    Press Enter once the board is in bootloader mode on $PORT... "

# 4. Flash firmware
echo "==> Erasing flash on $PORT..."
esptool.py --chip esp32s3 --port "$PORT" erase_flash

echo "==> Writing firmware ($FIRMWARE_PATH)..."
esptool.py --chip esp32s3 --port "$PORT" write_flash -z 0 "$FIRMWARE_PATH"

echo ""
echo "==> Press RESET on the board to boot MicroPython."
read -rp "    Press Enter once the board has rebooted... "

# Boards with native USB-JTAG-serial (e.g. Waveshare ESP32-S3-ETH) can drop
# and re-enumerate the port, or otherwise flake, right after esptool's
# post-flash reset — so any single mpremote call here may need a few tries.
mpremote_retry() {
    local tries=10 out
    for i in $(seq 1 "$tries"); do
        if out=$(mpremote connect "$PORT" "$@" 2>&1); then
            printf '%s' "$out"
            return 0
        fi
        sleep 1
    done
    echo "$out" >&2
    return 1
}

echo "==> Waiting for $PORT to come back..."
if ! mpremote_retry exec "print(1)" >/dev/null; then
    echo "ERROR: could not connect to $PORT after reboot"
    exit 1
fi

# 5. Verify W5500 support
echo "==> Verifying W5500 (Ethernet) support..."
W5500_OK=$(mpremote_retry exec "import network; print(hasattr(network, 'PHY_W5500'))")
if [ "$W5500_OK" != "True" ]; then
    echo "ERROR: this firmware build does not support PHY_W5500."
    echo "Try the ESP32_GENERIC_S3-SPIRAM variant from https://micropython.org/download/ESP32_GENERIC_S3/"
    exit 1
fi
echo "    OK."

# 6. Copy project files
echo "==> Copying project files to $PORT..."
for f in $FILES; do
    echo "    $f"
    mpremote_retry cp "$f" ":$f" >/dev/null
done

echo ""
echo "Done. Press RESET on the board to boot dakbot."
echo "Connect to http://<device-ip>/settings once it's up to configure sport, network, and MQTT."
