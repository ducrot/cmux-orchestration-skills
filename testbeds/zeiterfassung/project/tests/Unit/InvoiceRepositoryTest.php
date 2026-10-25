<?php
declare(strict_types=1);
namespace TimeTracker\Tests\Unit;
use PHPUnit\Framework\TestCase;
use TimeTracker\Domain\ValidationException;
use TimeTracker\Infrastructure\Storage\Database;
use TimeTracker\Infrastructure\Storage\InvoiceRepository;
final class InvoiceRepositoryTest extends TestCase
{
    public function testSequenceContinuesAcrossCustomersRestartsEachYearAndSkipsFailedCreation(): void
    {
        $pdo = Database::open(':memory:');
        $pdo->exec("INSERT INTO customers VALUES (1, 'Ada', 'Street', 'ada@example.com'), (2, 'Other', 'Street', 'other@example.com');
            INSERT INTO projects (id, customer_id, name) VALUES (1, 1, 'One'), (2, 2, 'Two');
            INSERT INTO entries (project_id, start, end, description) VALUES (1, 1767225600, 1767229200, 'Work')");
        $repository = new InvoiceRepository($pdo);
        try {
            $repository->create(1, '2026-10-31', null, null);
            self::fail('Missing rate must fail');
        } catch (ValidationException $error) {
            self::assertStringContainsString('entry 1', $error->getMessage());
        }
        $pdo->exec("INSERT INTO rates (project_id, cents, currency, start) VALUES (1, 10000, 'EUR', '2026-01-01'), (2, 12000, 'EUR', '2026-01-01')");
        self::assertSame('2026-1', $repository->create(1, '2026-10-31', null, null)->number);
        $pdo->exec("INSERT INTO entries (project_id, start, end, description) VALUES (2, 1767229200, 1767232800, 'Other')");
        self::assertSame('2026-2', $repository->create(2, '2026-11-01', null, null)->number);
        $pdo->exec("INSERT INTO entries (project_id, start, end, description) VALUES (1, 1767232800, 1767236400, 'New')");
        self::assertSame('2027-1', $repository->create(1, '2027-01-01', null, null)->number);
    }
}
