<?php
declare(strict_types=1);

namespace TimeTracker\Tests\Unit;

use PHPUnit\Framework\TestCase;
use TimeTracker\Domain\Rate;
use TimeTracker\Domain\ValidationException;

final class RateTest extends TestCase
{
    private function rate(string $start, ?string $end): Rate
    {
        return Rate::fromArray(1, ['amount' => '123.45', 'currency' => 'EUR', 'start' => $start, 'end' => $end]);
    }

    public function testInclusiveBoundariesOpenEndAndGap(): void
    {
        $closed = $this->rate('2024-02-01', '2024-02-29');
        $open = $this->rate('2024-04-01', null);
        self::assertFalse($closed->contains('2024-01-31'));
        self::assertTrue($closed->contains('2024-02-01'));
        self::assertTrue($closed->contains('2024-02-29'));
        self::assertFalse($closed->contains('2024-03-01'));
        self::assertFalse($open->contains('2024-03-31'));
        self::assertTrue($open->contains('2024-04-01'));
        self::assertTrue($open->contains('9999-12-31'));
        self::assertFalse($closed->overlaps($open));
        self::assertFalse($open->overlaps($closed));
        self::assertTrue($this->rate('2024-02-29', '2024-02-29')->contains('2024-02-29'));
    }

    public function testOverlapInBothDirectionsIncludingContainingAndOpenPeriods(): void
    {
        $rate = $this->rate('2026-02-01', '2026-02-28');
        foreach ([['2026-01-01', '2026-02-01'], ['2026-02-28', '2026-03-01'], ['2026-02-02', '2026-02-03'], ['2026-01-01', '2026-12-31'], ['2026-02-01', '2026-02-28'], ['2026-01-01', null]] as [$start, $end]) {
            $other = $this->rate($start, $end);
            self::assertTrue($rate->overlaps($other));
            self::assertTrue($other->overlaps($rate));
        }
        self::assertFalse($rate->overlaps($this->rate('2026-03-01', null)));
    }

    public function testDecimalConversionIsExact(): void
    {
        foreach (['0' => [0, '0.00'], '0.01' => [1, '0.01'], '12.3' => [1230, '12.30'], '999999999.99' => [99999999999, '999999999.99']] as $amount => [$cents, $formatted]) {
            $rate = Rate::fromArray(1, ['amount' => (string) $amount, 'currency' => 'EUR', 'start' => '2026-01-01']);
            self::assertSame($cents, $rate->cents);
            self::assertSame($formatted, $rate->toArray()['amount']);
        }
    }

    public function testLookupRejectsInvalidDate(): void
    {
        $this->expectException(ValidationException::class);
        $this->rate('2026-01-01', null)->contains('2026-02-29');
    }
}
