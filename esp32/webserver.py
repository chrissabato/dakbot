# =============================================================================
# webserver.py — Minimal async HTTP server that serves scoreboard JSON
#
# Endpoints:
#   GET /          → JSON scoreboard data  (application/json)
#   GET /data      → same JSON (alias)
#   GET /health    → {"status":"ok"}
#   anything else  → 404
# =============================================================================

import uasyncio as asyncio
import ujson

# Shared reference — main.py sets this after each serial update
score_data = {}


# -----------------------------------------------------------------------------
async def _handle_client(reader, writer):
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=3)
        # Drain remaining headers (we don't need them)
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=3)
            if line in (b'\r\n', b'', b'\n'):
                break

        parts = request_line.split()
        path  = parts[1].decode() if len(parts) >= 2 else '/'

        if path in ('/', '/data'):
            body    = ujson.dumps(score_data)
            status  = b'200 OK'
            ctype   = b'application/json'
        elif path == '/health':
            body    = '{"status":"ok"}'
            status  = b'200 OK'
            ctype   = b'application/json'
        else:
            body    = '{"error":"not found"}'
            status  = b'404 Not Found'
            ctype   = b'application/json'

        body_bytes = body.encode('utf-8')
        writer.write(
            b'HTTP/1.0 ' + status + b'\r\n'
            b'Content-Type: ' + ctype + b'; charset=utf-8\r\n'
            b'Access-Control-Allow-Origin: *\r\n'
            b'Content-Length: ' + str(len(body_bytes)).encode() + b'\r\n'
            b'Connection: close\r\n'
            b'\r\n'
        )
        writer.write(body_bytes)
        await writer.drain()

    except Exception as e:
        print('HTTP error:', e)
    finally:
        writer.close()
        await writer.wait_closed()


# -----------------------------------------------------------------------------
async def start(port=80):
    server = await asyncio.start_server(_handle_client, '0.0.0.0', port)
    print(f'HTTP server listening on port {port}')
    return server
