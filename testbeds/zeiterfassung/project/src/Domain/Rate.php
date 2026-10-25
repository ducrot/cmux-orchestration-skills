<?php
declare(strict_types=1);

namespace TimeTracker\Domain;

final readonly class Rate
{
    public function __construct(public int $id, public int $projectId, public int $cents, public string $currency, public string $start, public ?string $end) {}

    public static function date(mixed $value): string
    {
        if (!is_string($value) || preg_match('/^([0-9]{4})-([0-9]{2})-([0-9]{2})$/D', $value, $parts) !== 1 || !checkdate((int) $parts[2], (int) $parts[3], (int) $parts[1])) {
            throw new ValidationException(['Dates must be valid YYYY-MM-DD calendar dates.']);
        }
        return $value;
    }

    /** @param array<string, mixed> $input */
    public static function fromArray(int $projectId, array $input): self
    {
        $amount = $input['amount'] ?? null;
        // Accept decimal strings only: no binary float or scientific notation conversion.
        if (!is_string($amount) || preg_match('/^([0-9]{1,9})(?:\.([0-9]{1,2}))?$/D', $amount, $parts) !== 1) {
            throw new ValidationException(['Amount must be a non-negative decimal string with at most two decimal places and nine integer digits.']);
        }
        $cents = (int) $parts[1] * 100 + (int) str_pad($parts[2] ?? '', 2, '0');
        $currency = $input['currency'] ?? null;
        if (!is_string($currency) || preg_match('/^[A-Z]{3}$/D', $currency) !== 1) {
            throw new ValidationException(['Currency must be a three-letter uppercase code.']);
        }
        $start = self::date($input['start'] ?? null);
        $end = ($input['end'] ?? null) === null ? null : self::date($input['end']);
        if ($end !== null && $end < $start) {
            throw new ValidationException(['Rate end must be on or after its start.']);
        }
        return new self(0, $projectId, $cents, $currency, $start, $end);
    }

    public function contains(string $date): bool
    {
        self::date($date);
        return $date >= $this->start && ($this->end === null || $date <= $this->end);
    }

    public function overlaps(self $other): bool
    {
        return ($this->end === null || $other->start <= $this->end)
            && ($other->end === null || $this->start <= $other->end);
    }

    /** @return array{id: int, project_id: int, amount: string, currency: string, start: string, end: ?string} */
    public function toArray(): array
    {
        return ['id' => $this->id, 'project_id' => $this->projectId, 'amount' => intdiv($this->cents, 100) . '.' . str_pad((string) ($this->cents % 100), 2, '0', STR_PAD_LEFT), 'currency' => $this->currency, 'start' => $this->start, 'end' => $this->end];
    }
}
