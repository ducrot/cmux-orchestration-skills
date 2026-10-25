<?php
declare(strict_types=1);

namespace TimeTracker\Application;

use RuntimeException;

final class CustomerNotFound extends RuntimeException
{
    public function __construct(int $id)
    {
        parent::__construct('Customer ' . $id . ' was not found.');
    }
}
