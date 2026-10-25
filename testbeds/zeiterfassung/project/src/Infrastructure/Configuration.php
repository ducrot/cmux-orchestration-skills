<?php
declare(strict_types=1);

namespace TimeTracker\Infrastructure;

use RuntimeException;

final readonly class Configuration
{
    /** @param array{name: string, address: string, email: string} $issuer */
    public function __construct(public string $databasePath, public array $issuer) {}

    public static function fromEnvironment(): self
    {
        return self::fromFile(getenv('TIME_TRACKER_CONFIG') ?: dirname(__DIR__, 2) . '/config/project.php');
    }

    public static function fromFile(string $path): self
    {
        $values = require $path;
        if (!is_array($values) || !is_string($values['database_path'] ?? null) || trim($values['database_path']) === '') {
            throw new RuntimeException('Configuration requires a database_path.');
        }
        $issuer = $values['issuer'] ?? null;
        if (!is_array($issuer)) {
            throw new RuntimeException('Configuration requires issuer name, address and email.');
        }
        foreach (['name', 'address', 'email'] as $field) {
            if (!is_string($issuer[$field] ?? null)) {
                throw new RuntimeException('Configuration requires issuer name, address and email.');
            }
        }
        return new self($values['database_path'], ['name' => $issuer['name'], 'address' => $issuer['address'], 'email' => $issuer['email']]);
    }
}
