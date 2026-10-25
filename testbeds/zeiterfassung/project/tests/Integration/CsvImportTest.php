<?php
declare(strict_types=1);
namespace TimeTracker\Tests\Integration;
use PDO;
use PHPUnit\Framework\TestCase;
use TimeTracker\Api\Handler;
use TimeTracker\Api\Request;
use TimeTracker\Application\Customers;
use TimeTracker\Console\Application;
use TimeTracker\Infrastructure\Storage\CustomerRepository;
use TimeTracker\Infrastructure\Storage\Database;
final class CsvImportTest extends TestCase
{
    private PDO $pdo;
    private Customers $customers;
    private Handler $api;
    private string $file;
    protected function setUp(): void
    {
        $this->pdo = Database::open(':memory:');
        $this->customers = new Customers(new CustomerRepository($this->pdo));
        $this->customers->create(['name' => 'Ada', 'address' => 'Street', 'email' => 'ada@example.com']);
        $this->customers->projects()->create(1, ['name' => 'Rounded', 'rounding_minutes' => 15]);
        $this->customers->projects()->create(1, ['name' => 'Raw']);
        $this->api = new Handler($this->customers);
        $this->file = tempnam(sys_get_temp_dir(), 'csv-import-');
    }
    protected function tearDown(): void { unlink($this->file); }
    /** @return array{int, string, string} */
    private function cli(string $csv): array
    {
        file_put_contents($this->file, $csv);
        $out = $err = '';
        $code = (new Application($this->customers))->run(['entry:import', $this->file], static function (string $s) use (&$out): void { $out .= $s; }, static function (string $s) use (&$err): void { $err .= $s; });
        return [$code, $out, $err];
    }
    public function testValidFileThroughConsoleAndApi(): void
    {
        $csv = "project_id;start;end;description\r\n1;2026-10-25T09:00:00Z;2026-10-25T09:16:00Z;\" Work; \"\"quoted\"\"\nnext line\"\r\n2;2026-10-25T11:16:00+02:00;2026-10-25T11:17:00+02:00;Raw\r\n";
        [$code, $out, $err] = $this->cli($csv);
        self::assertSame(0, $code, $err);
        self::assertSame(['count' => 2, 'ids' => [1, 2]], json_decode($out, true));
        $entries = $this->customers->entries()->all();
        self::assertSame(1800, $entries[0]->billableDuration());
        self::assertSame(960, $entries[0]->rawDuration());
        self::assertSame("Work; \"quoted\"\nnext line", $entries[0]->description);
        self::assertSame(60, $entries[1]->billableDuration());
        $response = $this->api->handle(new Request('POST', '/entries/import', str_replace('2026-10-25', '2026-10-26', $csv)));
        self::assertSame(201, $response->status);
        self::assertSame(['count' => 2, 'ids' => [3, 4]], $response->body);
        self::assertSame(1800, $this->customers->entries()->show(3)->billableDuration());
        self::assertSame(60, $this->customers->entries()->show(4)->billableDuration());
        self::assertSame(405, $this->api->handle(new Request('GET', '/entries/import'))->status);
    }
    public function testAllErrorsAreSharedAndNothingIsWritten(): void
    {
        $this->customers->entries()->save(1, strtotime('2026-10-25T09:00:00Z'), strtotime('2026-10-25T10:00:00Z'), 'Existing');
        $csv = "project_id;start;end;description\n999;2026-10-25T12:00:00Z;2026-10-25T13:00:00Z;Unknown\n1;bad;2026-02-30T10:00:00Z;Bad dates\n1;2026-10-25T11:00:00Z;2026-10-25T10:00:00Z;Reversed\n2;2026-10-25T09:15:00Z;2026-10-25T09:30:00Z;Existing overlap\n1;2026-10-25T14:00:00Z;2026-10-25T15:00:00Z;First\n2;2026-10-25T14:30:00Z;2026-10-25T16:00:00Z;Second\n";
        $response = $this->api->handle(new Request('POST', '/entries/import', $csv));
        self::assertSame(422, $response->status);
        $errors = $response->body['errors'];
        foreach (['Row 2: Unknown project', 'Row 3: Start', 'Row 3: End', 'Row 4: End must be after start', 'Row 5: Overlaps time entry 1', 'Row 6: Overlaps CSV row 7', 'Row 7: Overlaps CSV row 6'] as $reason) {
            self::assertStringContainsString($reason, implode("\n", $errors));
        }
        [$code, $out, $err] = $this->cli($csv);
        self::assertSame(1, $code);
        self::assertSame('', $out);
        self::assertSame(implode("\n", $errors) . "\n", $err);
        self::assertCount(1, $this->customers->entries()->all());
    }
    public function testWrongFormatRejectedByBothInterfaces(): void
    {
        foreach (["project_id,start,end,description\n999,bad,bad,bad", "project;start;end;description\n999;bad;bad;bad", ''] as $csv) {
            $response = $this->api->handle(new Request('POST', '/entries/import', $csv));
            self::assertSame(422, $response->status);
            self::assertCount(1, $response->body['errors']);
            self::assertStringContainsString('semicolon-separated CSV with header project_id;start;end;description', $response->body['errors'][0]);
            [$code, , $err] = $this->cli($csv);
            self::assertSame(1, $code);
            self::assertSame(implode("\n", $response->body['errors']) . "\n", $err);
        }
        self::assertSame([], $this->customers->entries()->all());
    }
    public function testDatabaseFailureRollsBackAllRows(): void
    {
        $this->pdo->exec("CREATE TRIGGER fail_second BEFORE INSERT ON entries WHEN NEW.description = 'Fail' BEGIN SELECT RAISE(ABORT, 'simulated failure'); END");
        try {
            $this->customers->entries()->importCsv("project_id;start;end;description\n1;2026-10-25T09:00:00Z;2026-10-25T09:16:00Z;First\n1;2026-10-25T10:00:00Z;2026-10-25T10:16:00Z;Fail\n");
            self::fail('Expected database failure');
        } catch (\PDOException $error) { self::assertStringContainsString('simulated failure', $error->getMessage()); }
        self::assertSame([], $this->customers->entries()->all());
        self::assertSame(1, $this->customers->entries()->save(1, 100, 200, 'After rollback')->id);
    }
    public function testUnreadableFileAndMissingArguments(): void
    {
        $err = '';
        $console = new Application($this->customers);
        foreach ([['entry:import'], ['entry:import', $this->file . '-missing'], ['entry:import', dirname($this->file)]] as $args) {
            self::assertSame(1, $console->run($args, static function (string $s): void {}, static function (string $s) use (&$err): void { $err .= $s; }));
        }
        self::assertStringContainsString('Cannot read CSV file', $err);
    }
}
