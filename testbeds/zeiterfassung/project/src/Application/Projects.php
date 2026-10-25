<?php
declare(strict_types=1);

namespace TimeTracker\Application;

use TimeTracker\Domain\Project;
use TimeTracker\Domain\Rate;
use TimeTracker\Infrastructure\Storage\ProjectRepository;

final readonly class Projects
{
    public function __construct(private ProjectRepository $repository, private Customers $customers) {}

    /** @param array<string, mixed> $input */
    public function create(int $customerId, array $input): Project
    {
        $this->customers->show($customerId);
        return $this->repository->create($customerId, Project::name($input), Project::rounding($input['rounding_minutes'] ?? null));
    }

    /** @return list<Project> */
    public function all(int $customerId): array
    {
        $this->customers->show($customerId);
        return $this->repository->all($customerId);
    }

    public function show(int $customerId, int $id): Project
    {
        $this->customers->show($customerId);
        return $this->repository->find($customerId, $id) ?? throw new ProjectNotFound();
    }

    /** @param array<string, mixed> $input */
    public function update(int $customerId, int $id, array $input): Project
    {
        $project = $this->show($customerId, $id);
        return $this->repository->update($project, Project::name($input), array_key_exists('rounding_minutes', $input) ? Project::rounding($input['rounding_minutes']) : $project->roundingMinutes);
    }

    public function delete(int $customerId, int $id): void
    {
        $this->show($customerId, $id);
        $this->repository->delete($id);
    }

    /** @return list<Rate> */
    public function rates(int $customerId, int $projectId): array
    {
        $this->show($customerId, $projectId);
        return $this->repository->rates($projectId);
    }

    /** @param array<string, mixed> $input */
    public function addRate(int $customerId, int $projectId, array $input): Rate
    {
        $this->show($customerId, $projectId);
        return $this->repository->addRate(Rate::fromArray($projectId, $input));
    }

    public function removeRate(int $customerId, int $projectId, int $id): void
    {
        $this->show($customerId, $projectId);
        if (!$this->repository->removeRate($projectId, $id)) {
            throw new ProjectNotFound();
        }
    }

    public function applicableRate(int $customerId, int $projectId, string $date): ?Rate
    {
        Rate::date($date);
        foreach ($this->rates($customerId, $projectId) as $rate) {
            if ($rate->contains($date)) {
                return $rate;
            }
        }
        return null;
    }
}
