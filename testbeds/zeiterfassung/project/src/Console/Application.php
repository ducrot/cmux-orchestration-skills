<?php
declare(strict_types=1);

namespace TimeTracker\Console;

use TimeTracker\Application\Customers;
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
                $stdout("Commands:\n  customer:create NAME ADDRESS EMAIL\n  customer:list\n  customer:show ID\n  customer:update ID NAME ADDRESS EMAIL\n  customer:delete ID\n");
                return 0;
            }
            $spec = self::COMMANDS[$command] ?? null;
            if (!array_key_exists($command, self::COMMANDS) || count($arguments) !== 1 + (int) $spec['id'] + ($spec['fields'] ? count(self::FIELDS) : 0)) {
                throw new ValidationException(['Unknown command or invalid arguments. Run help for usage.']);
            }
            $id = 0;
            if ($spec['id']) {
                $id = preg_match('/^[1-9][0-9]*$/D', $arguments[1]) === 1 ? filter_var($arguments[1], FILTER_VALIDATE_INT) : false;
                if ($id === false) {
                    throw new ValidationException(['Customer ID must be a positive integer.']);
                }
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
        } catch (ValidationException|CustomerNotFound $error) {
            $stderr($error->getMessage() . "\n");
            return 1;
        }
    }

    /** @return array{deleted: int} */
    private function delete(int $id): array
    {
        $this->customers->delete($id);
        return ['deleted' => $id];
    }
}
