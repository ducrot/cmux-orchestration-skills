<?php
declare(strict_types=1);

namespace TimeTracker\Infrastructure\Storage;

use PDO;
use RuntimeException;
use TimeTracker\Infrastructure\Migrations\Migrator;

final class Database
{
    public static function open(string $path): PDO
    {
        if ($path !== ':memory:') {
            $directory = dirname($path);
            if (!is_dir($directory) && !mkdir($directory, 0777, true) && !is_dir($directory)) {
                throw new RuntimeException('Cannot create database directory.');
            }
        }
        $pdo = new PDO('sqlite:' . $path, null, null, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION, PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC]);
        $pdo->exec('PRAGMA foreign_keys = ON');
        (new Migrator())->migrate($pdo);
        return $pdo;
    }
}
