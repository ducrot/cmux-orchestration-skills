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
        return [
            1 => 'CREATE TABLE customers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, address TEXT NOT NULL, email TEXT NOT NULL)',
            2 => 'CREATE TABLE projects (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE RESTRICT, name TEXT NOT NULL);
                  CREATE INDEX projects_customer ON projects(customer_id);
                  CREATE TABLE rates (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE, cents INTEGER NOT NULL CHECK (cents >= 0), currency TEXT NOT NULL, start TEXT NOT NULL, end TEXT);
                  CREATE INDEX rates_project ON rates(project_id)',
            3 => 'ALTER TABLE projects ADD COLUMN rounding_minutes INTEGER CHECK (rounding_minutes > 0);
                  CREATE TABLE entries (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE RESTRICT, start INTEGER NOT NULL, end INTEGER NOT NULL CHECK (end > start), description TEXT NOT NULL, billed INTEGER NOT NULL DEFAULT 0);
                  CREATE INDEX entries_interval ON entries(start, end);
                  CREATE INDEX entries_project ON entries(project_id)',
        ];
    }
}
