<?php
declare(strict_types=1);
namespace TimeTracker\Infrastructure\Storage;
use PDO;
use Throwable;
use TimeTracker\Application\EntryNotFound;
use TimeTracker\Application\ProjectNotFound;
use TimeTracker\Domain\CsvImport;
use TimeTracker\Domain\TimeEntry;
use TimeTracker\Domain\ValidationException;
final readonly class EntryRepository
{
    private const SELECT = 'SELECT e.*, p.rounding_minutes, i.number AS invoice_number FROM entries e JOIN projects p ON p.id = e.project_id LEFT JOIN invoices i ON i.id = e.invoice_id';
    public function __construct(private PDO $pdo) {}
    public function find(int $id): ?TimeEntry
    {
        $s = $this->pdo->prepare(self::SELECT . ' WHERE e.id = ?');
        $s->execute([$id]);
        $row = $s->fetch();
        return $row === false ? null : $this->hydrate($row);
    }
    /** @return list<TimeEntry> */
    public function all(?int $projectId, ?int $from, ?int $to): array
    {
        $s = $this->pdo->prepare(self::SELECT . ' WHERE (? IS NULL OR e.project_id = ?) AND (? IS NULL OR e.start >= ?) AND (? IS NULL OR e.start < ?) ORDER BY e.start, e.id');
        $s->execute([$projectId, $projectId, $from, $from, $to, $to]);
        return array_map($this->hydrate(...), $s->fetchAll());
    }
    public function save(int $projectId, int $start, int $end, string $description, ?int $id): TimeEntry
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            if ($id !== null) { $this->assertUnlocked($id); }
            $s = $this->pdo->prepare('SELECT id FROM projects WHERE id = ?');
            $s->execute([$projectId]);
            if ($s->fetch() === false) { throw new ProjectNotFound(); }
            $s = $this->pdo->prepare('SELECT id FROM entries WHERE start < ? AND end > ? AND id != ? ORDER BY id LIMIT 1');
            $s->execute([$end, $start, $id ?? 0]);
            $conflict = $s->fetchColumn();
            if ($conflict !== false) { throw new ValidationException(['Overlaps time entry ' . $conflict . '.']); }
            if ($id === null) {
                $s = $this->pdo->prepare('INSERT INTO entries (project_id, start, end, description) VALUES (?, ?, ?, ?)');
                $s->execute([$projectId, $start, $end, $description]);
                $id = (int) $this->pdo->lastInsertId();
            } else {
                $s = $this->pdo->prepare('UPDATE entries SET project_id = ?, start = ?, end = ?, description = ? WHERE id = ?');
                $s->execute([$projectId, $start, $end, $description, $id]);
            }
            $entry = $this->find($id);
            $this->pdo->exec('COMMIT');
            return $entry ?? throw new \LogicException('Saved entry missing.');
        } catch (Throwable $error) {
            try {
                $this->pdo->exec('ROLLBACK');
            } catch (Throwable) {
                // SQLite may already have rolled back; keep the original error.
            }
            throw $error;
        }
    }
    /** @return array{count: int, ids: list<int>} */
    public function importCsv(string $csv): array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $projects = array_map('intval', $this->pdo->query('SELECT id FROM projects')->fetchAll(PDO::FETCH_COLUMN));
            $rows = CsvImport::validate($csv, $projects, $this->all(null, null, null));
            $statement = $this->pdo->prepare('INSERT INTO entries (project_id, start, end, description) VALUES (?, ?, ?, ?)');
            $ids = [];
            foreach ($rows as $row) {
                $statement->execute([$row['project_id'], $row['start'], $row['end'], $row['description']]);
                $ids[] = (int) $this->pdo->lastInsertId();
            }
            $this->pdo->exec('COMMIT');
            return ['count' => count($ids), 'ids' => $ids];
        } catch (Throwable $error) {
            try { $this->pdo->exec('ROLLBACK'); } catch (Throwable) { /* Keep the original error. */ }
            throw $error;
        }
    }
    public function delete(int $id): void
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $this->assertUnlocked($id);
            $s = $this->pdo->prepare('DELETE FROM entries WHERE id = ?');
            $s->execute([$id]);
            $this->pdo->exec('COMMIT');
        } catch (Throwable $error) {
            try { $this->pdo->exec('ROLLBACK'); } catch (Throwable) { /* Keep the original error. */ }
            throw $error;
        }
    }
    private function assertUnlocked(int $id): void
    {
        $entry = $this->find($id) ?? throw new EntryNotFound();
        if ($entry->billed) { throw new ValidationException(['Time entry ' . $id . ' is locked by invoice ' . $entry->invoiceNumber . '.']); }
    }
    /** @param array<string, mixed> $row */
    private function hydrate(array $row): TimeEntry
    {
        return new TimeEntry((int) $row['id'], (int) $row['project_id'], (int) $row['start'], (int) $row['end'], (string) $row['description'], $row['rounding_minutes'] === null ? null : (int) $row['rounding_minutes'], (bool) $row['billed'], $row['invoice_number'] === null ? null : (string) $row['invoice_number']);
    }
}
