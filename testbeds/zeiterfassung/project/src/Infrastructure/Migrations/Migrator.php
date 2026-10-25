<?php
declare(strict_types=1);

namespace TimeTracker\Infrastructure\Migrations;

use PDO;
use Throwable;

final class Migrator
{
    public function migrate(PDO $pdo): void
    {
        // Acquire the write lock before inspecting versions, including on concurrent first use.
        $pdo->exec('BEGIN IMMEDIATE');
        try {
            $pdo->exec('CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)');
            $applied = array_map('intval', $pdo->query('SELECT version FROM schema_migrations')->fetchAll(PDO::FETCH_COLUMN));
            $record = $pdo->prepare('INSERT INTO schema_migrations (version) VALUES (?)');
            foreach ($this->migrations() as $version => $sql) {
                if (in_array($version, $applied, true)) {
                    continue;
                }
                $pdo->exec($sql);
                $record->execute([$version]);
            }
            $pdo->exec('COMMIT');
        } catch (Throwable $error) {
            try {
                $pdo->exec('ROLLBACK');
            } catch (Throwable) {
                // SQLite may already have rolled back; keep the original error.
            }
            throw $error;
        }
    }

    /** @return array<int, string> */
    private function migrations(): array
    {
        return [1 => 'CREATE TABLE customers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, address TEXT NOT NULL, email TEXT NOT NULL)'];
    }
}
