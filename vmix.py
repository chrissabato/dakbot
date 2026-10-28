# =============================================================================
# vmix.py — Push the Colorado running clock straight into a vMix title
#
# vMix's own Data Sources poll the JSON endpoint on a timer, which puts the
# on-air clock up to a second (or more) behind the console. This instead
# holds one persistent connection to vMix's TCP API (default port 8099) and
# sends a SetText the moment Clock changes:
#
#   FUNCTION SetText Input=<input>&SelectedName=<field>&Value=<clock>\r\n
#
# A persistent TCP socket avoids the per-request connect/HTTP overhead of
# the HTTP API (port 8088), so each update is one small write.
#
# Only the latest value matters — if several clock changes land while a
# write is in flight, the next send just carries the newest one.
# =============================================================================

import uasyncio as asyncio
import settings as _settings
import webserver as _webserver

# Set by colorado_reader_task whenever Clock changes
clock_ready = asyncio.Event()


def _quote(s):
    """Percent-encode a query-string value (input names may contain spaces,
    '&', etc.)."""
    out = []
    for b in str(s).encode('utf-8'):
        c = chr(b)
        if c.isalpha() or c.isdigit() or c in '-_.~:':
            out.append(c)
        else:
            out.append('%{:02X}'.format(b))
    return ''.join(out)


async def _drain(reader):
    """Discard vMix's 'FUNCTION OK ...' replies so its side never blocks on
    a full socket, and return once the connection drops."""
    while True:
        line = await reader.readline()
        if not line:
            return


async def run():
    s      = _settings.current
    host   = s.get('vmix_host', '')
    port   = int(s.get('vmix_port', 8099))
    prefix = 'FUNCTION SetText Input={}&SelectedName={}&Value='.format(
        _quote(s.get('vmix_input', '')),
        _quote(s.get('vmix_field', 'Clock.Text')),
    )
    print('vMix pusher starting —', host, port)

    while True:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            print('vMix connected')
        except Exception as e:
            print('vMix connect failed:', e)
            await asyncio.sleep(5)
            continue

        drain_task = asyncio.create_task(_drain(reader))
        last_sent  = None
        try:
            while True:
                # Resend at least every 5 s so a vMix restart or a re-added
                # title picks the clock back up even while it's stopped
                try:
                    await asyncio.wait_for(clock_ready.wait(), 5)
                    clock_ready.clear()
                except asyncio.TimeoutError:
                    last_sent = None

                if drain_task.done():
                    raise OSError('connection closed by vMix')

                clock = _webserver.score_data.get('Clock', '')
                if clock != last_sent:
                    writer.write((prefix + _quote(clock) + '\r\n').encode())
                    await writer.drain()
                    last_sent = clock

        except Exception as e:
            print('vMix error:', e)
            drain_task.cancel()
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            await asyncio.sleep(2)
