# =============================================================================
# updater.py — OTA firmware update from GitHub
#
# Fetches each project file from the main branch of the GitHub repo and
# writes it to flash.  settings.json is never touched.
# Uses raw sockets + TLS — no extra packages required.
# =============================================================================

import uos
import usocket
import ssl
import utime

_HOST  = 'raw.githubusercontent.com'
_BASE  = '/chrissabato/dakbot/main/'
_FILES = [
    'config.py',
    'settings.py',
    'daktronics.py',
    'colorado.py',
    'webserver.py',
    'mqtt_publisher.py',
    'main.py',
    'daksports.json',
    'updater.py',
    'version.py',
]


_TIMEOUT = 10  # seconds


def _fetch_to(filename, dest):
    """Download a single file from GitHub over HTTPS, streaming the body
    straight into `dest` (an open binary file). Returns the byte count.

    Deliberately never holds the whole response in memory: accumulating it
    in a growing bytes object (via `response += chunk`) reallocates a bigger
    buffer on every chunk, which reliably raised MemoryError on the ESP32's
    fragmented heap for anything above ~15KB (webserver.py, daksports.json)
    — especially while the async webserver/serial-reader/MQTT tasks were
    also live and holding their own memory.
    """
    # Cache-busting query string: raw.githubusercontent.com's CDN doesn't
    # invalidate every edge instantly after a push, so a plain URL can
    # serve a stale cached file for a while after the OTA prompt appears.
    path = '{}{}?_={}'.format(_BASE, filename, utime.time())
    addr = usocket.getaddrinfo(_HOST, 443, 0, usocket.SOCK_STREAM)[0][-1]
    sock = usocket.socket(usocket.AF_INET, usocket.SOCK_STREAM)
    sock.settimeout(_TIMEOUT)
    try:
        sock.connect(addr)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.verify_mode = ssl.CERT_NONE
        sock = ctx.wrap_socket(sock, server_hostname=_HOST)

        request = (
            'GET {} HTTP/1.0\r\n'
            'Host: {}\r\n'
            'User-Agent: dakbot-updater\r\n'
            'Connection: close\r\n\r\n'
        ).format(path, _HOST)
        sock.write(request.encode())

        # Headers are small and bounded — buffer just those in memory until
        # we find the terminator, then stream everything else to disk.
        header_buf = b''
        sep = -1
        while sep == -1:
            chunk = sock.read(512)
            if not chunk:
                raise Exception('connection closed before headers received')
            header_buf += chunk
            sep = header_buf.find(b'\r\n\r\n')
            if sep == -1 and len(header_buf) > 4096:
                raise Exception('HTTP headers too large')

        header_text = header_buf[:sep].decode()
        status_line = header_text.split('\r\n', 1)[0]
        if ' 200 ' not in status_line:
            raise Exception(status_line.strip())

        content_length = None
        for line in header_text.split('\r\n')[1:]:
            if line.lower().startswith('content-length:'):
                content_length = int(line.split(':', 1)[1].strip())

        # Body bytes that arrived in the same read as the header terminator
        received = header_buf[sep + 4:]
        dest.write(received)
        body_len = len(received)

        # Read exactly Content-Length bytes rather than reading until the
        # connection closes — raw.githubusercontent.com (Fastly) doesn't
        # always close the socket after an HTTP/1.0 response, which made an
        # earlier "read until empty" loop hang indefinitely on some fetches.
        # settimeout() above is a backstop in case Content-Length is missing
        # or a read stalls outright.
        while content_length is None or body_len < content_length:
            chunk = sock.read(4096)
            if not chunk:
                break
            dest.write(chunk)
            body_len += len(chunk)
    finally:
        sock.close()

    return body_len


def update_all():
    """
    Download and install all project files.
    Returns a list of (filename, ok, detail) tuples.
    detail is byte count on success, error string on failure.
    """
    results = []
    for filename in _FILES:
        tmp = filename + '.tmp'
        try:
            with open(tmp, 'wb') as f:
                size = _fetch_to(filename, f)
            uos.rename(tmp, filename)
            results.append((filename, True, size))
        except Exception as ex:
            try:
                uos.remove(tmp)
            except Exception:
                pass
            results.append((filename, False, str(ex)))
    return results
