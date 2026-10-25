<?php
declare(strict_types=1);
namespace TimeTracker\Tests\Unit;
use PHPUnit\Framework\TestCase;
use TimeTracker\Domain\CsvImport;
use TimeTracker\Domain\TimeEntry;
use TimeTracker\Domain\ValidationException;
final class CsvImportTest extends TestCase
{
    private const HEADER = "project_id;start;end;description\n";
    /** @return list<string> */
    private function errors(string $csv): array
    {
        try { CsvImport::validate($csv, [1, 2], []); self::fail('Invalid CSV accepted'); }
        catch (ValidationException $error) { return $error->errors; }
    }
    public function testHeaderIsValidatedBeforeData(): void
    {
        foreach (['', "project_id,start,end,description\ninvalid", "start;project_id;end;description\ninvalid", "project_id;start;end;description;extra\ninvalid"] as $csv) {
            self::assertSame(['Expected semicolon-separated CSV with header project_id;start;end;description.'], $this->errors($csv));
        }
    }
    public function testLeadingUtf8ByteOrderMarkIsIgnored(): void
    {
        self::assertCount(1, CsvImport::validate("\xEF\xBB\xBF" . self::HEADER . "1;2026-10-25T09:00:00Z;2026-10-25T10:00:00Z;Work\n", [1], []));
    }
    public function testInvalidFieldsCollectAllReasons(): void
    {
        foreach (['0', '-1', '1.5', '999999999999999999999', '999'] as $project) {
            $errors = $this->errors(self::HEADER . "$project;bad;2026-02-30T10:00:00Z; \n");
            self::assertCount(4, $errors);
            foreach (['Unknown project', 'Start must', 'End must', 'Description must'] as $index => $reason) {
                self::assertStringContainsString('Row 2: ' . $reason, $errors[$index]);
            }
        }
        foreach (['tomorrow', '2026-10-25T09:00:00', '2026-10-25T25:00:00Z', '2026-10-25T09:00:00+14:30', "2026-10-25T09:00:00Z\0"] as $start) {
            self::assertStringContainsString('Row 2: Start', $this->errors(self::HEADER . "1;$start;2026-10-25T10:00:00Z;Work")[0]);
        }
        self::assertStringContainsString('Description must', $this->errors(self::HEADER . "1;2026-10-25T09:00:00Z;2026-10-25T10:00:00Z;\xff")[0]);
        foreach (['09:00', '08:00'] as $end) {
            self::assertSame(['Row 2: End must be after start.'], $this->errors(self::HEADER . "1;2026-10-25T09:00:00Z;2026-10-25T$end:00Z;Work"));
        }
    }
    public function testFieldCountsAndPhysicalRowNumbers(): void
    {
        $csv = self::HEADER . "1;2026-10-25T09:00:00Z;2026-10-25T10:00:00Z;\"Two\nlines\"\n1;missing\n\n1;too;many;fields;here\n";
        self::assertSame(['Row 4: Expected four semicolon-separated fields.', 'Row 5: Expected four semicolon-separated fields.', 'Row 6: Expected four semicolon-separated fields.'], $this->errors($csv));
    }
    public function testOverlapsAcrossProjectsReportEveryConflictingRow(): void
    {
        $csv = self::HEADER . "1;2026-10-25T09:00:00Z;2026-10-25T10:00:00Z;First\n2;2026-10-25T11:15:00+02:00;2026-10-25T11:30:00+02:00;Second\n1;2026-10-25T09:20:00Z;2026-10-25T11:00:00Z;Third\n";
        $errors = $this->errors($csv);
        self::assertCount(6, $errors);
        foreach (['Row 2: Overlaps CSV row 3.', 'Row 3: Overlaps CSV row 2.', 'Row 2: Overlaps CSV row 4.', 'Row 4: Overlaps CSV row 2.', 'Row 3: Overlaps CSV row 4.', 'Row 4: Overlaps CSV row 3.'] as $error) { self::assertContains($error, $errors); }
        $existing = new TimeEntry(42, 2, strtotime('2026-10-25T09:00:00Z'), strtotime('2026-10-25T10:00:00Z'), 'Existing', null);
        try { CsvImport::validate(self::HEADER . "1;2026-10-25T08:00:00Z;2026-10-25T11:00:00Z;Contains", [1], [$existing]); self::fail('Overlap accepted'); }
        catch (ValidationException $error) { self::assertSame(['Row 2: Overlaps time entry 42.'], $error->errors); }
    }
    public function testTouchingIntervalsAndHeaderOnlyAreValid(): void
    {
        $csv = self::HEADER . "1;2026-10-25T09:00:00Z;2026-10-25T09:16:00Z; First \n2;2026-10-25T09:16:00Z;2026-10-25T09:17:00Z;Second";
        $existing = new TimeEntry(1, 2, strtotime('2026-10-25T08:00:00Z'), strtotime('2026-10-25T09:00:00Z'), 'Existing', null);
        $rows = CsvImport::validate($csv, [1, 2], [$existing]);
        self::assertCount(2, $rows);
        self::assertSame('First', $rows[0]['description']);
        self::assertSame(960, $rows[0]['end'] - $rows[0]['start']);
        self::assertSame([], CsvImport::validate(self::HEADER, [], []));
    }
}
