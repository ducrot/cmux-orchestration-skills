<?php
declare(strict_types=1);

namespace TimeTracker\Api;

final readonly class Response
{
    /** @param array<mixed> $body */
    public function __construct(public int $status, public array $body) {}

    public function json(): string
    {
        return json_encode($this->body, JSON_THROW_ON_ERROR);
    }
}
