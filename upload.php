<?php
/**
 * aselex.app — Image Upload Endpoint
 *
 * Розмістити на сервері: /uploads/upload.php
 * Директорія для зображень: /uploads/images/  (права 755)
 *
 * Використання:
 *   POST /uploads/upload.php
 *   Header: X-Upload-Token: <your-secret-token>
 *   Body:   multipart/form-data, поле "file"
 *
 * Відповідь (JSON):
 *   {"ok": true,  "url": "https://aselex.app/uploads/images/file.jpg"}
 *   {"ok": false, "error": "..."}
 */

define('UPLOAD_TOKEN', 'REPLACE_WITH_YOUR_SECRET_TOKEN');
define('UPLOAD_DIR',   __DIR__ . '/images/');
define('BASE_URL',     'https://aselex.app/uploads/images/');
define('MAX_SIZE',     16 * 1024 * 1024); // 16 MB

header('Content-Type: application/json; charset=utf-8');

function error_response(int $code, string $message): void {
    http_response_code($code);
    echo json_encode(['ok' => false, 'error' => $message]);
    exit;
}

// 1. Метод
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    error_response(405, 'Method Not Allowed');
}

// 2. Токен
$token = $_SERVER['HTTP_X_UPLOAD_TOKEN'] ?? '';
if (!hash_equals(UPLOAD_TOKEN, $token)) {
    error_response(403, 'Forbidden');
}

// 3. Файл
if (empty($_FILES['file']) || $_FILES['file']['error'] !== UPLOAD_ERR_OK) {
    $err = $_FILES['file']['error'] ?? 'no file';
    error_response(400, 'Upload error: ' . $err);
}

$file = $_FILES['file'];

if ($file['size'] > MAX_SIZE) {
    error_response(413, 'File too large (max 5 MB)');
}

// 4. MIME через finfo (не довіряємо Content-Type від клієнта)
$finfo    = new finfo(FILEINFO_MIME_TYPE);
$mime     = $finfo->file($file['tmp_name']);
$allowed  = ['image/jpeg', 'image/webp', 'image/png'];

if (!in_array($mime, $allowed, true)) {
    error_response(415, 'Unsupported media type: ' . $mime);
}

// 5. Безпечне ім'я файлу
$original  = basename($file['name']);
$safe_name = preg_replace('/[^a-zA-Z0-9._-]/', '_', $original);
$safe_name = ltrim($safe_name, '.');
if ($safe_name === '' || $safe_name === '_') {
    $safe_name = 'image_' . time() . '.jpg';
}

// 6. Видаляємо файли старші 24 годин
foreach (glob(UPLOAD_DIR . '*') ?: [] as $f) {
    if (is_file($f) && time() - filemtime($f) > 86400) {
        unlink($f);
    }
}

// 7. Зберігаємо
if (!is_dir(UPLOAD_DIR)) {
    mkdir(UPLOAD_DIR, 0755, true);
}

$dest = UPLOAD_DIR . $safe_name;

if (!move_uploaded_file($file['tmp_name'], $dest)) {
    error_response(500, 'Failed to save file');
}

chmod($dest, 0644);

// 8. Відповідь
echo json_encode([
    'ok'  => true,
    'url' => BASE_URL . rawurlencode($safe_name),
], JSON_UNESCAPED_SLASHES);
