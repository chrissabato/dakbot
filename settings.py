# =============================================================================
# settings.py — Persistent user settings stored in settings.json on flash
#
# Hardware pin constants stay in config.py.
# Everything here is user-editable (sport, network, UART RX pin).
#
# Usage:
#   import settings
#   settings.current['sport']        → active sport
#   settings.save({'sport': 'football'})  → persist change
# =============================================================================

import ujson

DEFAULTS = {
    "sport":     "baseball",
    "uart_rx":   16,
    "uart_tx":   17,
    "use_dhcp":  False,
    "ip":        "192.168.1.100",
    "mask":      "255.255.255.0",
    "gateway":   "192.168.1.1",
    "dns":       "8.8.8.8",
    "http_port": 80,
}

_FILE = "settings.json"
current = {}


def load():
    global current
    try:
        with open(_FILE) as f:
            saved = ujson.load(f)
        current = dict(DEFAULTS)
        current.update(saved)
        print("Settings loaded from", _FILE)
    except:
        current = dict(DEFAULTS)
        print("No settings.json found — using defaults")


def save(data):
    """Merge data into current settings and persist to flash."""
    current.update(data)
    with open(_FILE, "w") as f:
        ujson.dump(current, f)
    print("Settings saved to", _FILE)


load()
