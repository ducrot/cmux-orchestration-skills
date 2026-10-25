<?php
declare(strict_types=1);
namespace TimeTracker\Infrastructure\Storage;
use PDO;
use Throwable;
use TimeTracker\Domain\Invoice;
use TimeTracker\Domain\InvoicePosition;
use TimeTracker\Domain\ValidationException;
final readonly class InvoiceRepository
{
    public function __construct(private PDO $pdo) {}
    public function create(int $customerId, string $issueDate, ?string $from, ?string $to): Invoice
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $projects = new ProjectRepository($this->pdo);
            $entries = new EntryRepository($this->pdo);
            $start = $from === null ? null : (int) strtotime($from . 'T00:00:00Z');
            $end = $to === null ? null : (int) strtotime($to . 'T00:00:00Z');
            $positions = [];
            foreach ($projects->all($customerId) as $project) {
                $rates = $projects->rates($project->id);
                foreach ($entries->all($project->id, $start, $end) as $entry) {
                    if ($entry->billed) { continue; }
                    $rate = null;
                    foreach ($rates as $candidate) {
                        if ($candidate->contains(gmdate('Y-m-d', $entry->start))) { $rate = $candidate; break; }
                    }
                    if ($rate === null) { throw new ValidationException(['No applicable rate for time entry ' . $entry->id . '.']); }
                    $positions[] = InvoicePosition::fromEntry($entry, $rate);
                }
            }
            if ($positions === []) { throw new ValidationException(['No unbilled time entries in the period.']); }
            usort($positions, fn (InvoicePosition $a, InvoicePosition $b) => [$a->date, $a->entryId] <=> [$b->date, $b->entryId]);
            $year = (int) substr($issueDate, 0, 4);
            $s = $this->pdo->prepare('SELECT COALESCE(MAX(counter), 0) + 1 FROM invoices WHERE year = ?');
            $s->execute([$year]);
            $counter = (int) $s->fetchColumn();
            $invoice = new Invoice(0, $customerId, $year . '-' . $counter, $issueDate, $positions);
            $s = $this->pdo->prepare('INSERT INTO invoices (customer_id, year, counter, number, issue_date, net, vat, gross) VALUES (?, ?, ?, ?, ?, ?, ?, ?)');
            $s->execute([$customerId, $year, $counter, $invoice->number, $issueDate, $invoice->net, $invoice->vat, $invoice->gross]);
            $id = (int) $this->pdo->lastInsertId();
            $s = $this->pdo->prepare('INSERT INTO invoice_positions (invoice_id, entry_id, date, description, hours, rate_cents, currency, amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?)');
            $lock = $this->pdo->prepare('UPDATE entries SET billed = 1, invoice_id = ? WHERE id = ?');
            foreach ($positions as $position) {
                $s->execute([$id, $position->entryId, $position->date, $position->description, $position->hours, $position->rateCents, $position->currency, $position->amount]);
                $lock->execute([$id, $position->entryId]);
            }
            $this->pdo->exec('COMMIT');
            return new Invoice($id, $customerId, $invoice->number, $issueDate, $positions);
        } catch (Throwable $error) {
            try { $this->pdo->exec('ROLLBACK'); } catch (Throwable) { /* Keep the original error. */ }
            throw $error;
        }
    }
    /** @return list<Invoice> */
    public function all(int $customerId): array
    {
        $s = $this->pdo->prepare('SELECT * FROM invoices WHERE customer_id = ? ORDER BY id');
        $s->execute([$customerId]);
        return array_map($this->hydrate(...), $s->fetchAll());
    }
    public function find(int $id): ?Invoice
    {
        $s = $this->pdo->prepare('SELECT * FROM invoices WHERE id = ?');
        $s->execute([$id]);
        $row = $s->fetch();
        return $row === false ? null : $this->hydrate($row);
    }
    /** @param array<string, mixed> $row */
    private function hydrate(array $row): Invoice
    {
        $s = $this->pdo->prepare('SELECT * FROM invoice_positions WHERE invoice_id = ? ORDER BY id');
        $s->execute([$row['id']]);
        $positions = array_map(static fn (array $p) => new InvoicePosition((int) $p['entry_id'], (string) $p['date'], (string) $p['description'], (float) $p['hours'], (int) $p['rate_cents'], (string) $p['currency'], (float) $p['amount']), $s->fetchAll());
        return new Invoice((int) $row['id'], (int) $row['customer_id'], (string) $row['number'], (string) $row['issue_date'], $positions, (float) $row['net'], (float) $row['vat'], (float) $row['gross']);
    }
}
