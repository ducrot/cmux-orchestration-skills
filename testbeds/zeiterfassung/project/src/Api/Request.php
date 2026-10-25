<?php
declare(strict_types=1);

namespace TimeTracker\Api;

final readonly class Request
{
    /** @param array<string, mixed> $query */
    public function __construct(public string $method, public string $path, public string $body = '', public array $query = []) {}
}
