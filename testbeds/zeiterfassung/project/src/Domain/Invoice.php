<?php
declare(strict_types=1);
namespace TimeTracker\Domain;
final readonly class Invoice
{
    public const VAT_RATE = 0.19;
    public float $net;
    public float $vat;
    public float $gross;
    /** @param list<InvoicePosition> $positions */
    public function __construct(public int $id, public int $customerId, public string $number, public string $issueDate, public array $positions, ?float $net = null, ?float $vat = null, ?float $gross = null)
    {
        $this->net = $net ?? round(array_sum(array_map(fn (InvoicePosition $p): float => $p->amount, $positions)), 2);
        $this->vat = $vat ?? round($this->net * self::VAT_RATE, 2);
        $this->gross = $gross ?? round($this->net + $this->vat, 2);
    }
    /** @return array<string, mixed> */
    public function toArray(): array
    {
        return ['id' => $this->id, 'customer_id' => $this->customerId, 'number' => $this->number, 'issue_date' => $this->issueDate, 'positions' => array_map(fn (InvoicePosition $p) => $p->toArray(), $this->positions), 'net' => $this->net, 'vat' => $this->vat, 'gross' => $this->gross];
    }
}
