# =============================================================================
# webserver.py — Async HTTP server: JSON data endpoint + settings UI
#
# Endpoints:
#   GET  /            → live scoreboard JSON
#   GET  /data        → same (alias)
#   GET  /health      → {"status":"ok"}
#   GET  /settings    → settings form (HTML)
#   POST /settings    → save settings to flash, redirect back
#   POST /reboot      → reboot the device
# =============================================================================

import uasyncio as asyncio
import ujson
import machine
import settings as _settings

score_data = {}

# =============================================================================
# Helpers
# =============================================================================

def _url_decode(s):
    s = s.replace('+', ' ')
    out = []
    i = 0
    while i < len(s):
        if s[i] == '%' and i + 2 < len(s):
            out.append(chr(int(s[i+1:i+3], 16)))
            i += 3
        else:
            out.append(s[i])
            i += 1
    return ''.join(out)


def _parse_form(body):
    if isinstance(body, (bytes, bytearray)):
        body = body.decode('utf-8')
    data = {}
    for pair in body.split('&'):
        if '=' in pair:
            k, v = pair.split('=', 1)
            data[_url_decode(k)] = _url_decode(v)
    return data


async def _send(writer, status, content_type, body):
    if isinstance(body, str):
        body = body.encode('utf-8')
    writer.write(
        b'HTTP/1.0 ' + status + b'\r\n'
        b'Content-Type: ' + content_type + b'\r\n'
        b'Content-Length: ' + str(len(body)).encode() + b'\r\n'
        b'Access-Control-Allow-Origin: *\r\n'
        b'Connection: close\r\n\r\n'
    )
    writer.write(body)
    await writer.drain()


async def _redirect(writer, location):
    writer.write(
        b'HTTP/1.0 303 See Other\r\n'
        b'Location: ' + location.encode() + b'\r\n'
        b'Content-Length: 0\r\n'
        b'Connection: close\r\n\r\n'
    )
    await writer.drain()


# =============================================================================
# Settings page HTML
# =============================================================================

_CSS = (
    '*{box-sizing:border-box;margin:0;padding:0}'
    'body{font-family:sans-serif;background:#f0f2f5;color:#222;padding:1rem;max-width:520px;margin:0 auto}'
    'h1{font-size:1.3rem;font-weight:700;margin-bottom:1rem;color:#111}'
    '.card{background:#fff;border-radius:8px;padding:1.25rem;margin-bottom:1rem;box-shadow:0 1px 3px rgba(0,0,0,.1)}'
    'h2{font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#888;margin-bottom:1rem}'
    'label{display:block;font-size:.875rem;font-weight:500;margin-bottom:.3rem;color:#333}'
    'input[type=text],input[type=number],select{width:100%;padding:.5rem .75rem;border:1px solid #ddd;'
    'border-radius:6px;font-size:.9rem;margin-bottom:.9rem;background:#fafafa}'
    'input[type=text]:focus,input[type=number]:focus,select:focus{outline:none;border-color:#2563eb;background:#fff}'
    '.check-row{display:flex;align-items:center;gap:.6rem;margin-bottom:.9rem}'
    '.check-row input{width:1rem;height:1rem;margin:0}'
    '.check-row label{margin:0;font-weight:400}'
    '.btn{display:inline-block;padding:.6rem 1.4rem;border:none;border-radius:6px;'
    'font-size:.9rem;font-weight:600;cursor:pointer}'
    '.btn-primary{background:#2563eb;color:#fff}'
    '.btn-danger{background:#dc2626;color:#fff}'
    '.note{font-size:.8rem;color:#888;margin-top:.6rem;line-height:1.4}'
    '.banner{padding:.75rem 1rem;border-radius:6px;margin-bottom:1rem;font-size:.875rem}'
    '.ok{background:#dcfce7;color:#166534;border:1px solid #bbf7d0}'
)

def _mqtt_html(s):
    chk     = ' checked' if s.get('mqtt_enabled') else ''
    hidden  = '' if s.get('mqtt_enabled') else ' style="display:none"'
    return (
        '<div class="card"><h2>MQTT</h2>'
        '<div class="check-row">'
        '<input type="checkbox" name="mqtt_enabled" id="mqtt_en"' + chk +
        ' onchange="document.getElementById(\'mqttcfg\').style.display=this.checked?\'\':\'none\';">'
        '<label for="mqtt_en">Enable MQTT publishing</label>'
        '</div>'
        '<div id="mqttcfg"' + hidden + '>'
        '<label>Broker hostname</label>'
        '<input type="text" name="mqtt_broker" value="' + s.get('mqtt_broker', '') + '" '
        'placeholder="xxxx.s1.eu.hivemq.cloud">'
        '<label>Port (TLS)</label>'
        '<input type="number" name="mqtt_port" value="' + str(s.get('mqtt_port', 8883)) + '">'
        '<label>Username</label>'
        '<input type="text" name="mqtt_user" value="' + s.get('mqtt_user', '') + '">'
        '<label>Password</label>'
        '<input type="text" name="mqtt_password" value="' + s.get('mqtt_password', '') + '">'
        '<label>Topic</label>'
        '<input type="text" name="mqtt_topic" value="' + s.get('mqtt_topic', 'dakbot/score') + '">'
        '<p class="note">Requires umqtt.simple on the device. '
        'Install once: <code>mpremote mip install umqtt.simple</code>. '
        'Reboot required after changing.</p>'
        '</div>'
        '</div>'
    )


def _settings_html(saved=False):
    s = _settings.current
    sports = [
        ('baseball',       'Baseball'),
        ('basketball',     'Basketball'),
        ('volleyball',     'Volleyball'),
        ('football',       'Football'),
        ('hockeylacrosse', 'Hockey / Lacrosse'),
    ]
    opts = ''.join(
        '<option value="{}"{}>{}</option>'.format(
            v, ' selected' if s['sport'] == v else '', lbl
        )
        for v, lbl in sports
    )
    chk    = ' checked' if s.get('use_dhcp') else ''
    hidden = ' style="display:none"' if s.get('use_dhcp') else ''
    banner = (
        '<div class="banner ok">Settings saved — reboot to apply network or pin changes.</div>'
        if saved else ''
    )

    return (
        '<!DOCTYPE html><html><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Dakbot Settings</title>'
        '<style>' + _CSS + '</style>'
        '</head><body>'
        '<h1>Dakbot Settings</h1>'
        + banner +

        # ---- Sport -----------------------------------------------------------
        '<form method="POST" action="/settings">'
        '<div class="card"><h2>Sport</h2>'
        '<label for="sport">Active sport</label>'
        '<select name="sport" id="sport">' + opts + '</select>'
        '</div>'

        # ---- Network ---------------------------------------------------------
        '<div class="card"><h2>Network</h2>'
        '<div class="check-row">'
        '<input type="checkbox" name="use_dhcp" id="dhcp"' + chk +
        ' onchange="document.getElementById(\'st\').style.display=this.checked?\'none\':\'\';">'
        '<label for="dhcp">Use DHCP</label>'
        '</div>'
        '<div id="st"' + hidden + '>'
        '<label>IP Address</label>'
        '<input type="text" name="ip" value="' + s.get('ip', '') + '">'
        '<label>Subnet Mask</label>'
        '<input type="text" name="mask" value="' + s.get('mask', '') + '">'
        '<label>Gateway</label>'
        '<input type="text" name="gateway" value="' + s.get('gateway', '') + '">'
        '<label>DNS Server</label>'
        '<input type="text" name="dns" value="' + s.get('dns', '') + '">'
        '</div>'
        '<label>HTTP Port</label>'
        '<input type="number" name="http_port" value="' + str(s.get('http_port', 80)) + '">'
        '</div>'

        # ---- Serial ----------------------------------------------------------
        '<div class="card"><h2>Serial</h2>'
        '<label>UART RX Pin (GPIO number)</label>'
        '<input type="number" name="uart_rx" value="' + str(s.get('uart_rx', 16)) + '">'
        '<p class="note">Wire the AllSport 5000 RTD output (via MAX3232) to this GPIO. '
        'Reboot required after changing.</p>'
        '</div>'

        # ---- MQTT ------------------------------------------------------------
        + _mqtt_html(s) +

        # ---- Save ------------------------------------------------------------
        '<div class="card"><h2>Save</h2>'
        '<button type="submit" class="btn btn-primary">Save Settings</button>'
        '<p class="note">Network and pin changes require a reboot to take effect.</p>'
        '</div>'
        '</form>'

        # ---- Reboot ----------------------------------------------------------
        '<form method="POST" action="/reboot"'
        ' onsubmit="return confirm(\'Reboot the device now?\');">'
        '<div class="card"><h2>Device</h2>'
        '<button type="submit" class="btn btn-danger">Reboot Device</button>'
        '<p class="note">Applies all saved settings and restarts the firmware.</p>'
        '</div>'
        '</form>'

        '</body></html>'
    )


# =============================================================================
# Route handlers
# =============================================================================

async def _handle_settings_get(writer, saved=False):
    await _send(writer, b'200 OK', b'text/html; charset=utf-8', _settings_html(saved))


async def _handle_settings_post(writer, body):
    form = _parse_form(body)
    _settings.save({
        'sport':         form.get('sport', _settings.DEFAULTS['sport']),
        'use_dhcp':      'use_dhcp' in form,
        'ip':            form.get('ip',        _settings.current.get('ip', '')),
        'mask':          form.get('mask',      _settings.current.get('mask', '')),
        'gateway':       form.get('gateway',   _settings.current.get('gateway', '')),
        'dns':           form.get('dns',       _settings.current.get('dns', '')),
        'uart_rx':       int(form.get('uart_rx',   _settings.current.get('uart_rx', 16))),
        'http_port':     int(form.get('http_port', _settings.current.get('http_port', 80))),
        'mqtt_enabled':  'mqtt_enabled' in form,
        'mqtt_broker':   form.get('mqtt_broker',   _settings.current.get('mqtt_broker', '')),
        'mqtt_port':     int(form.get('mqtt_port', _settings.current.get('mqtt_port', 8883))),
        'mqtt_user':     form.get('mqtt_user',     _settings.current.get('mqtt_user', '')),
        'mqtt_password': form.get('mqtt_password', _settings.current.get('mqtt_password', '')),
        'mqtt_topic':    form.get('mqtt_topic',    _settings.current.get('mqtt_topic', 'dakbot/score')),
    })
    await _redirect(writer, '/settings?saved=1')


async def _handle_reboot(writer):
    await _send(
        writer, b'200 OK', b'text/html; charset=utf-8',
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<style>body{font-family:sans-serif;padding:2rem;max-width:400px;margin:0 auto}</style>'
        '<script>setTimeout(()=>{location.href="/settings"},6000)</script>'
        '</head><body>'
        '<h2>Rebooting&hellip;</h2>'
        '<p>The device is restarting. Redirecting to settings in a few seconds.</p>'
        '</body></html>'
    )
    await asyncio.sleep_ms(300)
    machine.reset()


# =============================================================================
# Main request dispatcher
# =============================================================================

async def _handle_client(reader, writer):
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=3)
        parts  = request_line.split()
        method = parts[0].decode() if len(parts) >= 1 else 'GET'
        path   = parts[1].decode() if len(parts) >= 2 else '/'

        # Read headers, pick up Content-Length
        content_length = 0
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=3)
            if line in (b'\r\n', b'', b'\n'):
                break
            if line.lower().startswith(b'content-length:'):
                content_length = int(line.split(b':')[1].strip())

        # Read POST body
        body = b''
        if method == 'POST' and content_length > 0:
            body = await asyncio.wait_for(reader.read(content_length), timeout=5)

        # Route
        base  = path.split('?')[0]
        saved = 'saved=1' in path

        if base in ('/', '/data'):
            await _send(writer, b'200 OK', b'application/json', ujson.dumps(score_data))
        elif base == '/health':
            await _send(writer, b'200 OK', b'application/json', '{"status":"ok"}')
        elif base == '/settings' and method == 'GET':
            await _handle_settings_get(writer, saved=saved)
        elif base == '/settings' and method == 'POST':
            await _handle_settings_post(writer, body)
        elif base == '/reboot' and method == 'POST':
            await _handle_reboot(writer)
        else:
            await _send(writer, b'404 Not Found', b'application/json', '{"error":"not found"}')

    except Exception as e:
        print('HTTP error:', e)
    finally:
        writer.close()
        await writer.wait_closed()


# =============================================================================
# Server startup
# =============================================================================

async def start(port=80):
    server = await asyncio.start_server(_handle_client, '0.0.0.0', port)
    print('HTTP server listening on port', port)
    return server
