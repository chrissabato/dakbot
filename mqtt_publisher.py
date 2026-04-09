# =============================================================================
# mqtt_publisher.py — Async MQTT publisher for scoreboard data
#
# Connects to an MQTT broker over TLS (port 8883) and publishes score_data
# as JSON whenever it changes.  Pings every 30 s to maintain the keepalive.
# Reconnects automatically on failure.
#
# Requires umqtt.simple — install once with:
#   mpremote mip install umqtt.simple
# =============================================================================

import uasyncio as asyncio
import ujson
import ssl
import settings as _settings

# Shared reference — main.py sets this after webserver.score_data is live
score_ref = None


def _make_client():
    from umqtt.simple import MQTTClient
    s = _settings.current
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_ctx.verify_mode = ssl.CERT_NONE          # broker cert not verified (HiveMQ Cloud is valid CA-signed)
    client = MQTTClient(
        client_id   = b'dakbot',
        server      = s['mqtt_broker'].encode(),
        port        = s.get('mqtt_port', 8883),
        user        = s['mqtt_user'].encode()     if s.get('mqtt_user')     else None,
        password    = s['mqtt_password'].encode() if s.get('mqtt_password') else None,
        keepalive   = 60,
        ssl         = ssl_ctx,
    )
    return client


async def run(get_score):
    """
    Async task.  get_score is a callable that returns the current score dict.
    Loop forever: connect, publish on change, ping to stay alive, reconnect on error.
    """
    s            = _settings.current
    topic        = s.get('mqtt_topic', 'dakbot/score').encode()
    last_payload = None
    client       = None

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
        ping_counter = 0
        try:
            while True:
                score = get_score()
                if score:
                    payload = ujson.dumps(score).encode()
                    if payload != last_payload:
                        client.publish(topic, payload, retain=True)
                        last_payload = payload

                # Ping every 30 s (called every 1 s, so every 30 iterations)
                ping_counter += 1
                if ping_counter >= 30:
                    client.ping()
                    ping_counter = 0

                await asyncio.sleep(1)

        except Exception as e:
            print('MQTT error:', e)
            try:
                client.disconnect()
            except Exception:
                pass
            await asyncio.sleep(5)
