<?php
declare(strict_types=1);

namespace TimeTracker\Domain;

final readonly class Project
{
    public function __construct(public int $id, public int $customerId, public string $name, public ?int $roundingMinutes = null) {}

    /** @param array<string, mixed> $input */
    public static function name(array $input): string
    {
        $name = $input['name'] ?? null;
        if (!is_string($name) || trim($name) === '' || preg_match('//u', $name) !== 1) {
            throw new ValidationException(['Name must be a non-empty UTF-8 string.']);
        }
        return trim($name);
    }

    /** @param mixed $value */
    public static function rounding(mixed $value): ?int
    {
        if ($value === null || $value === 'none') { return null; }
        if (!is_int($value) || $value < 1 || $value > intdiv(PHP_INT_MAX, 60)) {
            throw new ValidationException(['Rounding must be none or a positive integer number of minutes within the supported integer range.']);
        }
        return $value;
    }

    /** @return array{id: int, customer_id: int, name: string, rounding_minutes: ?int} */
    public function toArray(): array
    {
        return ['id' => $this->id, 'customer_id' => $this->customerId, 'name' => $this->name, 'rounding_minutes' => $this->roundingMinutes];
    }
}
