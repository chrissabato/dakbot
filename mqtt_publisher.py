# =============================================================================
# mqtt_publisher.py — Async MQTT publisher for scoreboard data
#
# Publishes score_data immediately when signalled by serial_reader_task via
# an asyncio.Event, rather than polling on a timer.  Pings every 30 s to
# maintain the broker keepalive.  Reconnects automatically on failure.
#
# Requires umqtt.simple — install once with:
#   mpremote mip install umqtt.simple
# =============================================================================

import uasyncio as asyncio
import ujson
import ssl
import utime
import settings as _settings

# Event set by serial_reader_task whenever score_data changes
data_ready = asyncio.Event()


def _make_client():
    from umqtt.simple import MQTTClient
    s = _settings.current
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_ctx.verify_mode = ssl.CERT_NONE
    client = MQTTClient(
        client_id = b'dakbot',
        server    = s['mqtt_broker'].encode(),
        port      = s.get('mqtt_port', 8883),
        user      = s['mqtt_user'].encode()     if s.get('mqtt_user')     else None,
        password  = s['mqtt_password'].encode() if s.get('mqtt_password') else None,
        keepalive = 60,
        ssl       = ssl_ctx,
    )
    return client


async def run(get_score):
    """
    Async task.  Waits on data_ready event (set by serial_reader_task on each
    new RTD packet), publishes immediately, then waits again.  A separate ping
    task keeps the broker connection alive every 30 s.
    """
    s     = _settings.current
    topic = s.get('mqtt_topic', 'dakbot/score').encode()
    print('MQTT publisher starting — broker:', s.get('mqtt_broker'))

    while True:
        # --- Connect --------------------------------------------------------
        try:
            client = _make_client()
            client.connect()
            print('MQTT connected')
        except Exception as e:
            print('MQTT connect failed:', e)
            await asyncio.sleep(10)
            continue

        # --- Publish loop ---------------------------------------------------
        last_payload = None
        last_ping    = utime.ticks_ms()

        try:
            while True:
                # Wait for new data (or wake every 5 s to check ping deadline)
                try:
                    await asyncio.wait_for(data_ready.wait(), 5)
                    data_ready.clear()
                except asyncio.TimeoutError:
                    pass

                # Publish if data changed
                score = get_score()
                if score:
                    payload = ujson.dumps(score).encode()
                    if payload != last_payload:
                        client.publish(topic, payload, retain=True)
                        last_payload = payload

                # Ping every 30 s
                now = utime.ticks_ms()
                if utime.ticks_diff(now, last_ping) >= 30_000:
                    client.ping()
                    last_ping = now

        except Exception as e:
            print('MQTT error:', e)
            try:
                client.disconnect()
            except Exception:
                pass
            await asyncio.sleep(5)
