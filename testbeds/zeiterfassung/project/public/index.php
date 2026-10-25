<?php
declare(strict_types=1);

require __DIR__ . '/../vendor/autoload.php';

use TimeTracker\Api\Handler;
use TimeTracker\Api\Request;
use TimeTracker\Api\Response;
use TimeTracker\Infrastructure\Bootstrap;
use TimeTracker\Infrastructure\Configuration;

try {
    $configuration = Configuration::fromEnvironment();
    $handler = new Handler(Bootstrap::customers($configuration));
    $response = $handler->handle(new Request($_SERVER['REQUEST_METHOD'] ?? 'GET', explode('?', $_SERVER['REQUEST_URI'] ?? '/', 2)[0], file_get_contents('php://input') ?: '', $_GET));
    $body = $response->json();
} catch (Throwable $error) {
    error_log($error->getMessage());
    $response = new Response(500, ['errors' => ['Internal server error.']]);
    $body = $response->json();
}
http_response_code($response->status);
header('Content-Type: application/json; charset=utf-8');
echo $body;
