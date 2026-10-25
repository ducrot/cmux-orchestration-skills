<?php
declare(strict_types=1);
namespace TimeTracker\Domain;
final readonly class InvoicePosition
{
    public float $amount;
    public function __construct(public int $entryId, public string $date, public string $description, public float $hours, public int $rateCents, public string $currency, ?float $amount = null)
    {
        $this->amount = $amount ?? round($hours * $rateCents / 100, 2);
    }
    public static function fromEntry(TimeEntry $entry, Rate $rate): self
    {
        return new self($entry->id, gmdate('Y-m-d', $entry->start), $entry->description, $entry->billableDuration() / 3600, $rate->cents, $rate->currency);
    }
    /** @return array<string, int|float|string> */
    public function toArray(): array
    {
        return ['entry_id' => $this->entryId, 'date' => $this->date, 'description' => $this->description, 'hours' => $this->hours, 'rate_cents' => $this->rateCents, 'currency' => $this->currency, 'amount' => $this->amount];
    }
}
