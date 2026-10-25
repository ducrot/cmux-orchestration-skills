<?php
declare(strict_types=1);

namespace TimeTracker\Infrastructure;

use TimeTracker\Application\Customers;
use TimeTracker\Infrastructure\Storage\CustomerRepository;
use TimeTracker\Infrastructure\Storage\Database;

final class Bootstrap
{
    public static function customers(Configuration $configuration): Customers
    {
        return new Customers(new CustomerRepository(Database::open($configuration->databasePath)));
    }
}
