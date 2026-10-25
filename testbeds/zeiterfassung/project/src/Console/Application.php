<?php
declare(strict_types=1);

namespace TimeTracker\Console;

use TimeTracker\Application\Customers;
use TimeTracker\Application\EntryNotFound;
use TimeTracker\Domain\TimeEntry;
use TimeTracker\Application\ProjectNotFound;
use TimeTracker\Application\CustomerNotFound;
use TimeTracker\Domain\ValidationException;

final readonly class Application
{
    private const FIELDS = ['name', 'address', 'email'];

    private const COMMANDS = [
        'customer:create' => ['id' => false, 'fields' => true],
        'customer:list' => ['id' => false, 'fields' => false],
        'customer:show' => ['id' => true, 'fields' => false],
        'customer:update' => ['id' => true, 'fields' => true],
        'customer:delete' => ['id' => true, 'fields' => false],
    ];

    public function __construct(private Customers $customers) {}

    /**
     * @param list<string> $arguments
     * @param callable(string): void $stdout
     * @param callable(string): void $stderr
     */
    public function run(array $arguments, callable $stdout, callable $stderr): int
    {
        try {
            $command = $arguments[0] ?? 'help';
            if (in_array($command, ['help', '--help', 'list'], true)) {
                $stdout("Commands:\n  customer:create NAME ADDRESS EMAIL\n  customer:list\n  customer:show ID\n  customer:update ID NAME ADDRESS EMAIL\n  customer:delete ID\n  project:create CUSTOMER_ID NAME [ROUNDING_MINUTES|none]\n  project:list CUSTOMER_ID\n  project:show CUSTOMER_ID PROJECT_ID\n  project:update CUSTOMER_ID PROJECT_ID NAME [ROUNDING_MINUTES|none]\n  project:delete CUSTOMER_ID PROJECT_ID\n  rate:add CUSTOMER_ID PROJECT_ID AMOUNT CURRENCY START [END]\n  rate:list CUSTOMER_ID PROJECT_ID\n  rate:remove CUSTOMER_ID PROJECT_ID RATE_ID\n  entry:create PROJECT_ID START END DESCRIPTION\n  entry:list [PROJECT_ID|all [FROM [TO]]]\n  entry:show ID\n  entry:update ID PROJECT_ID START END DESCRIPTION\n  entry:delete ID\n  entry:import FILE\n");
                return 0;
            }
            if ($command === 'entry:import') {
                if (count($arguments) !== 2) { throw new ValidationException(['Usage: entry:import FILE']); }
                $csv = is_file($arguments[1]) ? @file_get_contents($arguments[1]) : false;
                if ($csv === false) { throw new ValidationException(['Cannot read CSV file: ' . $arguments[1]]); }
                try {
                    $stdout(json_encode($this->customers->entries()->importCsv($csv), JSON_THROW_ON_ERROR) . "\n");
                } catch (ValidationException $error) {
                    $stderr(implode("\n", $error->errors) . "\n");
                    return 1;
                }
                return 0;
            }
            if (str_starts_with($command, 'entry:')) {
                $stdout(json_encode($this->entryCommand($arguments), JSON_THROW_ON_ERROR) . "\n");
                return 0;
            }
            if (str_starts_with($command, 'project:') || str_starts_with($command, 'rate:')) {
                $result = $this->projectCommand($arguments);
                $stdout(json_encode($result, JSON_THROW_ON_ERROR) . "\n");
                return 0;
            }
            $spec = self::COMMANDS[$command] ?? null;
            if (!array_key_exists($command, self::COMMANDS) || count($arguments) !== 1 + (int) $spec['id'] + ($spec['fields'] ? count(self::FIELDS) : 0)) {
                throw new ValidationException(['Unknown command or invalid arguments. Run help for usage.']);
            }
            $id = 0;
            if ($spec['id']) {
                $id = $this->id($arguments[1], 'Customer ID');
            }
            $input = $spec['fields'] ? array_combine(self::FIELDS, array_slice($arguments, 1 + (int) $spec['id'])) : [];
            $result = match ($command) {
                'customer:create' => $this->customers->create($input)->toArray(),
                'customer:list' => array_map(fn ($customer) => $customer->toArray(), $this->customers->all()),
                'customer:show' => $this->customers->show($id)->toArray(),
                'customer:update' => $this->customers->update($id, $input)->toArray(),
                'customer:delete' => $this->delete($id),
            };
            $stdout(json_encode($result, JSON_THROW_ON_ERROR) . "\n");
            return 0;
        } catch (ValidationException|CustomerNotFound|ProjectNotFound|EntryNotFound $error) {
            $stderr($error->getMessage() . "\n");
            return 1;
        }
    }

    /** @param list<string> $arguments
     * @return array<mixed>
     */
    private function projectCommand(array $arguments): array
    {
        $command = $arguments[0];
        $counts = ['project:create' => [3, 4], 'project:list' => [2], 'project:show' => [3], 'project:update' => [4, 5], 'project:delete' => [3], 'rate:add' => [6, 7], 'rate:list' => [3], 'rate:remove' => [4]];
        if (!in_array(count($arguments), $counts[$command] ?? [], true)) {
            throw new ValidationException(['Unknown command or invalid arguments. Run help for usage.']);
        }
        $customerId = $this->id($arguments[1], 'Customer ID');
        $projectId = in_array($command, ['project:create', 'project:list'], true) ? 0 : $this->id($arguments[2], 'Project ID');
        $projects = $this->customers->projects();
        if ($command === 'project:delete') {
            $projects->delete($customerId, $projectId);
            return ['deleted' => $projectId];
        }
        if ($command === 'rate:remove') {
            $rateId = $this->id($arguments[3], 'Rate ID');
            $projects->removeRate($customerId, $projectId, $rateId);
            return ['deleted' => $rateId];
        }
        $value = match ($command) { 'project:create' => $arguments[3] ?? null, 'project:update' => $arguments[4] ?? null, default => null };
        $rounding = $value === null ? [] : ['rounding_minutes' => $value === 'none' ? null : $this->id($value, 'Rounding minutes')];
        return match ($command) {
            'project:create' => $projects->create($customerId, ['name' => $arguments[2]] + $rounding)->toArray(),
            'project:list' => array_map(fn ($project) => $project->toArray(), $projects->all($customerId)),
            'project:show' => $projects->show($customerId, $projectId)->toArray(),
            'project:update' => $projects->update($customerId, $projectId, ['name' => $arguments[3]] + $rounding)->toArray(),
            'rate:list' => array_map(fn ($rate) => $rate->toArray(), $projects->rates($customerId, $projectId)),
            'rate:add' => $projects->addRate($customerId, $projectId, ['amount' => $arguments[3], 'currency' => $arguments[4], 'start' => $arguments[5], 'end' => $arguments[6] ?? null])->toArray(),
            default => throw new ValidationException(['Unknown command. Run help for usage.']),
        };
    }

    /** @param list<string> $args
     * @return array<mixed>
     */
    private function entryCommand(array $args): array
    {
        $command = $args[0];
        $counts = ['entry:create' => [5], 'entry:update' => [6], 'entry:show' => [2], 'entry:delete' => [2], 'entry:list' => [1, 2, 3, 4]];
        if (!in_array(count($args), $counts[$command] ?? [], true)) { throw new ValidationException(['Unknown command or invalid arguments. Run help for usage.']); }
        $entries = $this->customers->entries();
        if ($command === 'entry:list') {
            $project = !isset($args[1]) || $args[1] === 'all' ? null : $this->id($args[1], 'Project ID');
            $from = isset($args[2]) ? $this->entryTimestamp($args[2]) : null;
            $to = isset($args[3]) ? $this->entryTimestamp($args[3]) : null;
            return array_map($this->entryRepresentation(...), $entries->all($project, $from, $to));
        }
        $id = $command === 'entry:create' ? null : $this->id($args[1], 'Entry ID');
        if ($command === 'entry:show') { return $this->entryRepresentation($entries->show($id)); }
        if ($command === 'entry:delete') { $entries->delete($id); return ['deleted' => $id]; }
        $offset = $command === 'entry:create' ? 1 : 2;
        $project = $this->id($args[$offset], 'Project ID');
        $start = $this->entryTimestamp($args[$offset + 1]);
        $end = $this->entryTimestamp($args[$offset + 2]);
        if ($end <= $start) { throw new ValidationException(['End must be after start.']); }
        $description = $args[$offset + 3];
        if (trim($description) === '' || preg_match('//u', $description) !== 1) { throw new ValidationException(['Description must be a non-empty UTF-8 string.']); }
        return $this->entryRepresentation($entries->save($project, $start, $end, trim($description), $id));
    }

    private function entryTimestamp(string $value): int
    {
        if (preg_match('/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-](?:(?:0[0-9]|1[0-3]):[0-5][0-9]|14:00))$/D', $value) !== 1) {
            throw new ValidationException(['Timestamps must use YYYY-MM-DDTHH:MM:SS with Z or a timezone offset.']);
        }
        $date = \DateTimeImmutable::createFromFormat('!Y-m-d\\TH:i:sP', $value);
        $errors = \DateTimeImmutable::getLastErrors();
        if ($date === false || ($errors !== false && ($errors['warning_count'] > 0 || $errors['error_count'] > 0))) {
            throw new ValidationException(['Timestamps must be valid calendar dates and times.']);
        }
        return $date->getTimestamp();
    }

    /** @return array{id: int, project_id: int, start: string, end: string, description: string, raw_duration_seconds: int, billable_duration_seconds: int, billed: bool} */
    private function entryRepresentation(TimeEntry $entry): array
    {
        return ['id' => $entry->id, 'project_id' => $entry->projectId, 'start' => gmdate('Y-m-d\\TH:i:s\\Z', $entry->start), 'end' => gmdate('Y-m-d\\TH:i:s\\Z', $entry->end), 'description' => $entry->description, 'raw_duration_seconds' => $entry->rawDuration(), 'billable_duration_seconds' => $entry->billableDuration(), 'billed' => $entry->billed];
    }

    private function id(string $value, string $label): int
    {
        $id = preg_match('/^[1-9][0-9]*$/D', $value) === 1 ? filter_var($value, FILTER_VALIDATE_INT) : false;
        if ($id === false) {
            throw new ValidationException([$label . ' must be a positive integer.']);
        }
        return $id;
    }

    /** @return array{deleted: int} */
    private function delete(int $id): array
    {
        $this->customers->delete($id);
        return ['deleted' => $id];
    }
}
