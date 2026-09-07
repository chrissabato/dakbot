<?php
    require __DIR__ . '/config.php';

    $devices = [];
    if (is_file(CACHE_FILE)) {
        $decoded = json_decode(file_get_contents(CACHE_FILE), true);
        if (is_array($decoded)) $devices = $decoded;
    }

    header('Content-Type: application/json');
    header('Access-Control-Allow-Origin: *');

    if (isset($_GET['device'])) {
        if (isset($devices[$_GET['device']])) {
            echo json_encode([$devices[$_GET['device']]]);
        } else {
            http_response_code(404);
            echo json_encode(['error' => 'device not found']);
        }
    } else {
        echo json_encode(array_values($devices));
    }
?>
