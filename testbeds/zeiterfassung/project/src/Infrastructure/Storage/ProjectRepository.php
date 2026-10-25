<?php
declare(strict_types=1);

namespace TimeTracker\Infrastructure\Storage;

use PDO;
use Throwable;
use TimeTracker\Domain\Project;
use TimeTracker\Domain\Rate;
use TimeTracker\Domain\ValidationException;

final readonly class ProjectRepository
{
    public function __construct(private PDO $pdo) {}

    public function create(int $customerId, string $name, ?int $rounding): Project
    {
        $statement = $this->pdo->prepare('INSERT INTO projects (customer_id, name, rounding_minutes) VALUES (?, ?, ?)');
        $statement->execute([$customerId, $name, $rounding]);
        return new Project((int) $this->pdo->lastInsertId(), $customerId, $name, $rounding);
    }

    /** @return list<Project> */
    public function all(int $customerId): array
    {
        $statement = $this->pdo->prepare('SELECT * FROM projects WHERE customer_id = ? ORDER BY id');
        $statement->execute([$customerId]);
        return array_map($this->hydrate(...), $statement->fetchAll());
    }

    public function find(int $customerId, int $id): ?Project
    {
        $statement = $this->pdo->prepare('SELECT * FROM projects WHERE customer_id = ? AND id = ?');
        $statement->execute([$customerId, $id]);
        $row = $statement->fetch();
        return $row === false ? null : $this->hydrate($row);
    }

    public function update(Project $project, string $name, ?int $rounding): Project
    {
        $statement = $this->pdo->prepare('UPDATE projects SET name = ?, rounding_minutes = ? WHERE id = ?');
        $statement->execute([$name, $rounding, $project->id]);
        return new Project($project->id, $project->customerId, $name, $rounding);
    }

    public function delete(int $id): void
    {
        $statement = $this->pdo->prepare('DELETE FROM projects WHERE id = ?');
        try {
            $statement->execute([$id]);
        } catch (\PDOException $error) {
            if ($error->getCode() === '23000') { throw new ValidationException(['Project with time entries cannot be deleted.']); }
            throw $error;
        }
    }

    /** @return list<Rate> */
    public function rates(int $projectId): array
    {
        $statement = $this->pdo->prepare('SELECT * FROM rates WHERE project_id = ? ORDER BY start, id');
        $statement->execute([$projectId]);
        return array_map($this->hydrateRate(...), $statement->fetchAll());
    }

    public function addRate(Rate $rate): Rate
    {
        // Serialize overlap validation and insert across SQLite connections.
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            foreach ($this->rates($rate->projectId) as $existing) {
                if ($rate->overlaps($existing)) {
                    throw new ValidationException(['Rate validity periods must not overlap.']);
                }
            }
            $statement = $this->pdo->prepare('INSERT INTO rates (project_id, cents, currency, start, end) VALUES (?, ?, ?, ?, ?)');
            $statement->execute([$rate->projectId, $rate->cents, $rate->currency, $rate->start, $rate->end]);
            $id = (int) $this->pdo->lastInsertId();
            $this->pdo->exec('COMMIT');
            return new Rate($id, $rate->projectId, $rate->cents, $rate->currency, $rate->start, $rate->end);
        } catch (Throwable $error) {
            try {
                $this->pdo->exec('ROLLBACK');
            } catch (Throwable) {
                // SQLite may already have rolled back; keep the original error.
            }
            throw $error;
        }
    }

    public function removeRate(int $projectId, int $id): bool
    {
        $statement = $this->pdo->prepare('DELETE FROM rates WHERE project_id = ? AND id = ?');
        $statement->execute([$projectId, $id]);
        return $statement->rowCount() > 0;
    }

    /** @param array<string, mixed> $row */
    private function hydrate(array $row): Project
    {
        return new Project((int) $row['id'], (int) $row['customer_id'], (string) $row['name'], $row['rounding_minutes'] === null ? null : (int) $row['rounding_minutes']);
    }

    /** @param array<string, mixed> $row */
    private function hydrateRate(array $row): Rate
    {
        return new Rate((int) $row['id'], (int) $row['project_id'], (int) $row['cents'], (string) $row['currency'], (string) $row['start'], $row['end'] === null ? null : (string) $row['end']);
    }
}
