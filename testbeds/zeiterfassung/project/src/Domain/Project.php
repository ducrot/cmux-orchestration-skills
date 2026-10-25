<?php
declare(strict_types=1);

namespace TimeTracker\Domain;

final readonly class Project
{
    public function __construct(public int $id, public int $customerId, public string $name) {}

    /** @param array<string, mixed> $input */
    public static function name(array $input): string
    {
        $name = $input['name'] ?? null;
        if (!is_string($name) || trim($name) === '' || preg_match('//u', $name) !== 1) {
            throw new ValidationException(['Name must be a non-empty UTF-8 string.']);
        }
        return trim($name);
    }

    /** @return array{id: int, customer_id: int, name: string} */
    public function toArray(): array
    {
        return ['id' => $this->id, 'customer_id' => $this->customerId, 'name' => $this->name];
    }
}
