#!/bin/bash
# flash.sh — Copy dakbot project files to the ESP32-S3-ETH

PORT=${1:-/dev/ttyACM0}

echo "Copying files to $PORT..."

mpremote connect "$PORT" cp config.py :config.py \
  + cp settings.py :settings.py \
  + cp daktronics.py :daktronics.py \
  + cp webserver.py :webserver.py \
  + cp main.py :main.py \
  + cp daksports.json :daksports.json

echo "Done. Press RESET on the board to boot."
