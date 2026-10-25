<?php
declare(strict_types=1);

namespace TimeTracker\Domain;

use InvalidArgumentException;

final class ValidationException extends InvalidArgumentException
{
    /** @param list<string> $errors */
    public function __construct(public readonly array $errors)
    {
        parent::__construct(implode(' ', $errors));
    }
}
