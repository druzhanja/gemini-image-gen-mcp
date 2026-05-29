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

define('UPLOAD_TOKEN',  'REPLACE_WITH_YOUR_SECRET_TOKEN');
define('BASE_UPLOAD',   __DIR__ . '/images/');
define('BASE_URL',      'https://aselex.app/uploads/images/');
define('MAX_SIZE',      16 * 1024 * 1024); // 16 MB
define('CLEANUP_DAYS',  1);               // 0 = ніколи не видаляти

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

// 6. Директорія images/YYYY/MM/
$date_subdir = date('Y/m');
$upload_dir  = BASE_UPLOAD . $date_subdir . '/';

if (!is_dir($upload_dir)) {
    mkdir($upload_dir, 0755, true);
}

// 7. Вирішуємо конфлікти імен: file.jpg → file-2.jpg → file-3.jpg
$info    = pathinfo($safe_name);
$stem    = $info['filename'];
$ext     = isset($info['extension']) ? '.' . $info['extension'] : '';
$dest    = $upload_dir . $safe_name;
$counter = 2;
while (file_exists($dest)) {
    $dest = $upload_dir . $stem . '-' . $counter . $ext;
    $counter++;
}
$final_name = basename($dest);

// 8. Видаляємо файли в поточному місяці старші CLEANUP_DAYS (0 = не видаляти)
if (CLEANUP_DAYS > 0) {
    $cutoff = time() - CLEANUP_DAYS * 86400;
    foreach (glob($upload_dir . '*') ?: [] as $f) {
        if (is_file($f) && filemtime($f) < $cutoff) {
            unlink($f);
        }
    }
}

// 9. Зберігаємо
if (!move_uploaded_file($file['tmp_name'], $dest)) {
    error_response(500, 'Failed to save file');
}

chmod($dest, 0644);

// 10. Відповідь
echo json_encode([
    'ok'  => true,
    'url' => BASE_URL . $date_subdir . '/' . rawurlencode($final_name),
], JSON_UNESCAPED_SLASHES);
