<?php
// mqtt-cache-daemon.php — persistent MQTT subscriber that keeps a live
// JSON cache of the latest score message per device.
//
// api.php used to shell out to `mosquitto_sub ... timeout 3` on every
// request, blocking each page load for the full timeout even though
// retained messages arrive in milliseconds. This script instead keeps a
// single long-lived subscription open and writes the current state to
// CACHE_FILE on every message, so api.php can just read that file.
//
// Run under a process supervisor (see ../systemd/dakbot-mqtt-cache.service)
// with automatic restart: if the broker connection drops, mosquitto_sub's
// stdout pipe closes, this script exits, and the supervisor restarts it.
// CACHE_FILE keeps serving the last known state in the meantime.

if (php_sapi_name() !== 'cli') {
    exit;
}

require __DIR__ . '/config.php';

// Devices publish with retain=true, so without -R the broker would replay
// every device's last message on every (re)connect, making a dead device
// indistinguishable from one that just published. -R suppresses that
// catch-up replay entirely — only genuine live publishes come through, so
// lastSeen always reflects real activity. The on-disk cache (loaded below)
// is what survives a daemon restart instead.
$cmd = sprintf(
    'stdbuf -oL mosquitto_sub -R -h %s -p %s -u %s -P %s -v -t %s',
    escapeshellarg(MQTT_HOST),
    escapeshellarg((string) MQTT_PORT),
    escapeshellarg(MQTT_USER),
    escapeshellarg(MQTT_PASS),
    escapeshellarg('dakbot/score/#')
);

$handle = popen($cmd, 'r');
if (!$handle) {
    fwrite(STDERR, "mqtt-cache-daemon: failed to start mosquitto_sub\n");
    exit(1);
}

@mkdir(dirname(CACHE_FILE), 0700, true);

// Seed from the existing cache (if any) so previously-recorded lastSeen
// values survive a daemon restart instead of every device looking new.
$devices = [];
if (is_file(CACHE_FILE)) {
    $existing = json_decode(file_get_contents(CACHE_FILE), true);
    if (is_array($existing)) $devices = $existing;
}

while (($line = fgets($handle)) !== false) {
    $line = rtrim($line, "\n");
    if ($line === '') continue;

    [$topic, $payload] = array_pad(explode(' ', $line, 2), 2, '');
    // Skip anything that isn't a per-device topic (e.g. a leftover
    // retained message on the bare "dakbot/score" topic — the '#'
    // wildcard matches its own parent level too).
    if (!preg_match('#^dakbot/score/(.+)$#', $topic, $m)) continue;

    $decoded = json_decode($payload, true);
    if (!is_array($decoded)) continue;

    $decoded['device'] = $m[1];
    $decoded['lastSeen'] = time();
    ksort($decoded, SORT_STRING | SORT_FLAG_CASE);
    $devices[$m[1]] = $decoded;

    // Drop devices that haven't published in a long time so the cache
    // (and in-memory map) don't grow forever with decommissioned hardware.
    $cutoff = time() - DEVICE_EXPIRE_SECONDS;
    $devices = array_filter($devices, fn($d) => ($d['lastSeen'] ?? 0) >= $cutoff);

    $tmp = CACHE_FILE . '.tmp';
    file_put_contents($tmp, json_encode($devices));
    rename($tmp, CACHE_FILE);
}

pclose($handle);
fwrite(STDERR, "mqtt-cache-daemon: mosquitto_sub exited, restarting\n");
exit(1);
