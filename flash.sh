#!/bin/bash
# flash.sh — Copy dakbot project files to the ESP32-S3-ETH

PORT=${1:-/dev/ttyACM0}
FILES="config.py settings.py daktronics.py webserver.py mqtt_publisher.py updater.py main.py daksports.json"

echo "Copying files to $PORT..."

for f in $FILES; do
    echo "  $f"
    mpremote connect "$PORT" cp "$f" ":$f"
    if [ $? -ne 0 ]; then
        echo "ERROR: failed to copy $f"
        exit 1
    fi
done

echo "Done. Press RESET on the board to boot."
