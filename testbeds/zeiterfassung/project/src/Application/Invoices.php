<?php
declare(strict_types=1);
namespace TimeTracker\Application;
use TimeTracker\Domain\Invoice;
use TimeTracker\Domain\Rate;
use TimeTracker\Domain\ValidationException;
use TimeTracker\Infrastructure\Storage\InvoiceRepository;
final readonly class Invoices
{
    public function __construct(private InvoiceRepository $repository, private Customers $customers) {}
    public function create(int $customerId, ?string $issueDate = null, ?string $from = null, ?string $to = null): Invoice
    {
        $this->customers->show($customerId);
        $issueDate = Rate::date($issueDate ?? gmdate('Y-m-d'));
        if ($from !== null) { Rate::date($from); }
        if ($to !== null) { Rate::date($to); }
        if ($from !== null && $to !== null && $to <= $from) { throw new ValidationException(['Period end must be after start.']); }
        return $this->repository->create($customerId, $issueDate, $from, $to);
    }
    /** @return list<Invoice> */
    public function all(int $customerId): array
    {
        $this->customers->show($customerId);
        return $this->repository->all($customerId);
    }
    public function show(int $id): Invoice { return $this->repository->find($id) ?? throw new InvoiceNotFound(); }
}
