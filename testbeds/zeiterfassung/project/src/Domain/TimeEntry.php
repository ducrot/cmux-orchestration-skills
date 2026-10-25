<?php
declare(strict_types=1);
namespace TimeTracker\Domain;
final readonly class TimeEntry
{
    public function __construct(public int $id, public int $projectId, public int $start, public int $end, public string $description, public ?int $roundingMinutes, public bool $billed = false) {}

    public static function interval(int $start, int $end): void
    {
        if ($end <= $start) { throw new ValidationException(['End must be after start.']); }
    }

    public function rawDuration(): int { return $this->end - $this->start; }

    public function billableDuration(): int
    {
        if ($this->roundingMinutes === null) { return $this->rawDuration(); }
        $step = $this->roundingMinutes * 60;
        return (intdiv($this->rawDuration() - 1, $step) + 1) * $step;
    }

    public function overlaps(self $other): bool { return $this->start < $other->end && $this->end > $other->start; }
}
