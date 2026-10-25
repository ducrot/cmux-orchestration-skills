<?php
declare(strict_types=1);
namespace TimeTracker\Application;
use TimeTracker\Domain\TimeEntry;
use TimeTracker\Domain\ValidationException;
use TimeTracker\Infrastructure\Storage\EntryRepository;
final readonly class Entries
{
    public function __construct(private EntryRepository $repository) {}
    public function save(int $projectId, int $start, int $end, string $description, ?int $id = null): TimeEntry
    {
        TimeEntry::interval($start, $end);
        return $this->repository->save($projectId, $start, $end, $description, $id);
    }
    /** @return array{count: int, ids: list<int>} */
    public function importCsv(string $csv): array { return $this->repository->importCsv($csv); }
    public function show(int $id): TimeEntry { return $this->repository->find($id) ?? throw new EntryNotFound(); }
    /** @return list<TimeEntry> */
    public function all(?int $projectId = null, ?int $from = null, ?int $to = null): array
    {
        if ($from !== null && $to !== null && $to <= $from) { throw new ValidationException(['Filter end must be after filter start.']); }
        return $this->repository->all($projectId, $from, $to);
    }
    public function delete(int $id): void { $this->repository->delete($id); }
}
