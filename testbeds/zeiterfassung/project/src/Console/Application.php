<?php
declare(strict_types=1);

namespace TimeTracker\Console;

use TimeTracker\Application\Customers;
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
                $stdout("Commands:\n  customer:create NAME ADDRESS EMAIL\n  customer:list\n  customer:show ID\n  customer:update ID NAME ADDRESS EMAIL\n  customer:delete ID\n  project:create CUSTOMER_ID NAME\n  project:list CUSTOMER_ID\n  project:show CUSTOMER_ID PROJECT_ID\n  project:update CUSTOMER_ID PROJECT_ID NAME\n  project:delete CUSTOMER_ID PROJECT_ID\n  rate:add CUSTOMER_ID PROJECT_ID AMOUNT CURRENCY START [END]\n  rate:list CUSTOMER_ID PROJECT_ID\n  rate:remove CUSTOMER_ID PROJECT_ID RATE_ID\n");
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
        } catch (ValidationException|CustomerNotFound|ProjectNotFound $error) {
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
        $counts = ['project:create' => [3], 'project:list' => [2], 'project:show' => [3], 'project:update' => [4], 'project:delete' => [3], 'rate:add' => [6, 7], 'rate:list' => [3], 'rate:remove' => [4]];
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
        return match ($command) {
            'project:create' => $projects->create($customerId, ['name' => $arguments[2]])->toArray(),
            'project:list' => array_map(fn ($project) => $project->toArray(), $projects->all($customerId)),
            'project:show' => $projects->show($customerId, $projectId)->toArray(),
            'project:update' => $projects->update($customerId, $projectId, ['name' => $arguments[3]])->toArray(),
            'rate:list' => array_map(fn ($rate) => $rate->toArray(), $projects->rates($customerId, $projectId)),
            'rate:add' => $projects->addRate($customerId, $projectId, ['amount' => $arguments[3], 'currency' => $arguments[4], 'start' => $arguments[5], 'end' => $arguments[6] ?? null])->toArray(),
            default => throw new ValidationException(['Unknown command. Run help for usage.']),
        };
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
