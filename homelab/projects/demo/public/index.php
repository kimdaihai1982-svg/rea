<?php
header('Content-Type: text/html; charset=utf-8');
$ok = false;
try {
    $db = new PDO('mysql:host=db;dbname=appdb;charset=utf8mb4', getenv('DB_USERNAME'), getenv('DB_PASSWORD'), [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
    $ok = $db->query('SELECT 1')->fetchColumn() == 1;
} catch (Throwable $e) { http_response_code(503); }
?>
<!doctype html><html lang="vi"><meta charset="utf-8"><title>PHP ready</title>
<style>body{background:#101827;color:#e7edf9;font:20px system-ui;padding:10vw}b{color:#63e6be}</style>
<h1>MayChu247 · PHP</h1><p>PHP: <b><?= htmlspecialchars(PHP_VERSION) ?></b></p>
<p>Database: <b><?= $ok ? 'Kết nối thành công' : 'Chưa sẵn sàng' ?></b></p>
<p>Thay dự án mẫu trong projects/demo/public để triển khai ứng dụng.</p></html>
