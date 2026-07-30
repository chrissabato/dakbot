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
import machine

DEFAULTS = {
    "device_name":    "",
    "sport":          "baseball",
    "uart_rx":        16,
    "uart_tx":        17,
    "use_dhcp":       True,
    "ip":             "192.168.1.100",
    "mask":           "255.255.255.0",
    "gateway":        "192.168.1.1",
    "dns":            "8.8.8.8",
    "http_port":      80,
    "mqtt_enabled":   False,
    "mqtt_broker":    "",
    "mqtt_port":      8883,
    "mqtt_user":      "",
    "mqtt_password":  "",
    "mqtt_topic":     "",
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


def _default_device_name():
    return ':'.join('{:02X}'.format(b) for b in machine.unique_id())


def device_name():
    """Effective device name: the user-set value, or the MAC-style default."""
    return current.get('device_name') or _default_device_name()


def _default_mqtt_topic():
    mac = ''.join('{:02x}'.format(b) for b in machine.unique_id())
    return 'dakbot/score/' + mac


def mqtt_topic():
    """Effective MQTT topic: the user-set value, or a MAC-scoped default."""
    return current.get('mqtt_topic') or _default_mqtt_topic()


load()
