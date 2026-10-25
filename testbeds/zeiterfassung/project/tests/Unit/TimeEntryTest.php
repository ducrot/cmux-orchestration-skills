<?php
declare(strict_types=1);
namespace TimeTracker\Tests\Unit;
use PHPUnit\Framework\TestCase;
use TimeTracker\Domain\TimeEntry;
use TimeTracker\Domain\ValidationException;
final class TimeEntryTest extends TestCase
{
    public function testRounding(): void
    {
        foreach ([[null, 61, 61], [15, 900, 900], [15, 960, 1800], [15, 1, 900], [1, 61, 120], [30, 960, 1800]] as [$step, $duration, $expected]) {
            $entry = new TimeEntry(1, 1, 0, $duration, 'Work', $step);
            self::assertSame($duration, $entry->rawDuration());
            self::assertSame($expected, $entry->billableDuration());
        }
    }
    public function testRehydratedEntryUsesChangedProjectStep(): void
    {
        $original = new TimeEntry(1, 1, 100, 1060, 'Work', 15);
        $changed = new TimeEntry($original->id, $original->projectId, $original->start, $original->end, $original->description, 10);
        self::assertSame(1800, $original->billableDuration());
        self::assertSame(1200, $changed->billableDuration());
        self::assertSame($original->rawDuration(), $changed->rawDuration());
    }
    public function testOverlapIntervals(): void
    {
        $entry = new TimeEntry(1, 1, 100, 200, 'Work', null);
        foreach ([[0, 100, false], [200, 300, false], [110, 190, true], [0, 300, true], [50, 150, true], [150, 250, true], [100, 200, true]] as [$start, $end, $expected]) {
            self::assertSame($expected, $entry->overlaps(new TimeEntry(2, 2, $start, $end, 'Other', null)));
        }
    }
    public function testInvalidInterval(): void
    {
        $this->expectException(ValidationException::class);
        TimeEntry::interval(100, 100);
    }
}
