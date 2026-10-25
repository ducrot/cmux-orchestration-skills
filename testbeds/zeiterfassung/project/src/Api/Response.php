<?php
declare(strict_types=1);

namespace TimeTracker\Api;

final readonly class Response
{
    /** @param array<mixed>|string $body */
    public function __construct(public int $status, public array|string $body, public string $contentType = 'application/json') {}

    public function serialize(): string
    {
        return is_string($this->body) ? $this->body : $this->json();
    }

    public function json(): string
    {
        return json_encode($this->body, JSON_THROW_ON_ERROR | JSON_PRESERVE_ZERO_FRACTION);
    }
}
