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
            4 => 'CREATE TABLE invoices (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE RESTRICT, year INTEGER NOT NULL, counter INTEGER NOT NULL, number TEXT NOT NULL UNIQUE, issue_date TEXT NOT NULL, net REAL NOT NULL, vat REAL NOT NULL, gross REAL NOT NULL, UNIQUE(year, counter));
                  CREATE TABLE invoice_positions (id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER NOT NULL REFERENCES invoices(id), entry_id INTEGER NOT NULL UNIQUE REFERENCES entries(id), date TEXT NOT NULL, description TEXT NOT NULL, hours REAL NOT NULL, rate_cents INTEGER NOT NULL, currency TEXT NOT NULL, amount REAL NOT NULL);
                  ALTER TABLE entries ADD COLUMN invoice_id INTEGER REFERENCES invoices(id)',
        ];
    }
}
