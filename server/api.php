<?php
    require __DIR__ . '/config.php';

    $cmd = sprintf(
        'timeout 3 mosquitto_sub -h %s -p %s -u %s -P %s -v -t %s 2>/dev/null',
        escapeshellarg(MQTT_HOST),
        escapeshellarg((string) MQTT_PORT),
        escapeshellarg(MQTT_USER),
        escapeshellarg(MQTT_PASS),
        escapeshellarg('dakbot/score/#')
    );
    $output = shell_exec($cmd);

    $devices = [];
    if ($output) {
        foreach (explode("\n", trim($output)) as $line) {
            if ($line === '') continue;
            [$topic, $payload] = array_pad(explode(' ', $line, 2), 2, '');
            // Skip anything that isn't a per-device topic (e.g. a leftover
            // retained message on the bare "dakbot/score" topic — the '#'
            // wildcard matches its own parent level too).
            if (!preg_match('#^dakbot/score/(.+)$#', $topic, $m)) continue;
            $decoded = json_decode($payload, true);
            if (!is_array($decoded)) continue;
            $decoded['device'] = $m[1];
            ksort($decoded, SORT_STRING | SORT_FLAG_CASE);
            // Keep only the most recent message per device — a live device
            // can publish several times during the collection window.
            $devices[$m[1]] = $decoded;
        }
    }

    header('Content-Type: application/json');
    header('Access-Control-Allow-Origin: *');

    if (isset($_GET['device'])) {
        if (isset($devices[$_GET['device']])) {
            echo json_encode($devices[$_GET['device']]);
        } else {
            http_response_code(404);
            echo json_encode(['error' => 'device not found']);
        }
    } else {
        echo json_encode(array_values($devices));
    }
?>
