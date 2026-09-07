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


def _fetch(filename):
    """Download a single file from GitHub over HTTPS. Returns bytes."""
    path = _BASE + filename
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

        # Read exactly Content-Length bytes of body rather than reading until
        # the connection closes — raw.githubusercontent.com (Fastly) doesn't
        # always close the socket after an HTTP/1.0 response, which made the
        # old "read until empty" loop hang indefinitely on some fetches.
        # settimeout() above is a backstop in case Content-Length is missing
        # or a read stalls outright.
        response = b''
        header_end = -1
        content_length = None
        while True:
            chunk = sock.read(4096)
            if not chunk:
                break
            response += chunk

            if header_end == -1:
                header_end = response.find(b'\r\n\r\n')
                if header_end != -1:
                    for line in response[:header_end].decode().split('\r\n')[1:]:
                        if line.lower().startswith('content-length:'):
                            content_length = int(line.split(':', 1)[1].strip())

            if content_length is not None and len(response) - (header_end + 4) >= content_length:
                break
    finally:
        sock.close()

    # Split headers from body
    sep = response.find(b'\r\n\r\n')
    if sep == -1:
        raise Exception('No HTTP header separator')

    status_line = response[:response.find(b'\r\n')].decode()
    if ' 200 ' not in status_line:
        raise Exception(status_line.strip())

    return response[sep + 4:]


def update_all():
    """
    Download and install all project files.
    Returns a list of (filename, ok, detail) tuples.
    detail is byte count on success, error string on failure.
    """
    results = []
    for filename in _FILES:
        try:
            data = _fetch(filename)
            tmp  = filename + '.tmp'
            with open(tmp, 'wb') as f:
                f.write(data)
            uos.rename(tmp, filename)
            results.append((filename, True, len(data)))
        except Exception as ex:
            results.append((filename, False, str(ex)))
    return results
