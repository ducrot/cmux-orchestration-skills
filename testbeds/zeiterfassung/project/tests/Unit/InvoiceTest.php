<?php
declare(strict_types=1);
namespace TimeTracker\Tests\Unit;
use PHPUnit\Framework\TestCase;
use TimeTracker\Domain\Invoice;
use TimeTracker\Domain\InvoicePosition;
use TimeTracker\Domain\Rate;
use TimeTracker\Domain\TimeEntry;
final class InvoiceTest extends TestCase
{
    public function testTotalsRateChangesAndRoundedHours(): void
    {
        $old = new Rate(1, 1, 12345, 'EUR', '2026-01-01', '2026-06-30');
        $new = new Rate(2, 1, 15000, 'EUR', '2026-07-01', null);
        $first = InvoicePosition::fromEntry(new TimeEntry(1, 1, 0, 960, 'First', 15), $old);
        $second = InvoicePosition::fromEntry(new TimeEntry(2, 1, 3600, 7200, 'Second', 15), $new);
        $third = InvoicePosition::fromEntry(new TimeEntry(3, 1, 8000, 8060, 'Third', null), $new);
        self::assertSame(0.5, $first->hours);
        self::assertSame(61.73, $first->amount);
        self::assertSame(150.0, $second->amount);
        self::assertSame(2.5, $third->amount);
        $invoice = new Invoice(1, 1, '2026-1', '2026-10-31', [$first, $second, $third]);
        self::assertSame(214.23, $invoice->net);
        self::assertSame(40.7, $invoice->vat);
        self::assertEqualsWithDelta(254.93, $invoice->gross, 0.0000001);
    }
}
