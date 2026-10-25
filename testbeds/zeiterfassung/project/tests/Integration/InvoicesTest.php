<?php
declare(strict_types=1);
namespace TimeTracker\Tests\Integration;
use PHPUnit\Framework\TestCase;
use TimeTracker\Api\Handler;
use TimeTracker\Api\Request;
use TimeTracker\Application\Customers;
use TimeTracker\Console\Application;
use TimeTracker\Infrastructure\Storage\CustomerRepository;
use TimeTracker\Infrastructure\Storage\Database;
final class InvoicesTest extends TestCase
{
    private \PDO $pdo;
    private Customers $customers;
    private Handler $api;
    private Application $console;
    protected function setUp(): void
    {
        $this->pdo = Database::open(':memory:');
        $this->customers = new Customers(new CustomerRepository($this->pdo));
        $this->customers->create(['name' => 'Ada', 'address' => 'Street', 'email' => 'ada@example.com']);
        $this->customers->projects()->create(1, ['name' => 'Work', 'rounding_minutes' => 15]);
        $this->api = new Handler($this->customers);
        $this->console = new Application($this->customers);
    }
    /** @param list<string> $args
     * @return array{int, string, string} */
    private function cli(array $args): array
    {
        $out = $err = '';
        $code = $this->console->run($args, static function (string $s) use (&$out): void { $out .= $s; }, static function (string $s) use (&$err): void { $err .= $s; });
        return [$code, $out, $err];
    }
    private function entry(string $date): void
    {
        $this->customers->entries()->save(1, (int) strtotime($date . 'T09:00:00Z'), (int) strtotime($date . 'T09:16:00Z'), 'Work');
    }
    private function rate(): void
    {
        $this->customers->projects()->addRate(1, 1, ['amount' => '100', 'currency' => 'EUR', 'start' => '2026-01-01']);
    }
    public function testCreationListingShowingAndSnapshots(): void
    {
        $this->rate();
        $this->entry('2026-10-25');
        $response = $this->api->handle(new Request('POST', '/customers/1/invoices', '{"issue_date":"2026-10-31"}'));
        self::assertSame(201, $response->status);
        self::assertSame('2026-1', $response->body['number']);
        self::assertSame(50.0, $response->body['net']);
        self::assertSame(9.5, $response->body['vat']);
        self::assertSame(59.5, $response->body['gross']);
        self::assertSame(0.5, $response->body['positions'][0]['hours']);
        self::assertSame(10000, $response->body['positions'][0]['rate_cents']);
        self::assertSame(50.0, $response->body['positions'][0]['amount']);
        self::assertStringContainsString('50.0', $response->json());
        self::assertSame($response->body, $this->api->handle(new Request('GET', '/invoices/1'))->body);
        self::assertSame([$response->body], $this->api->handle(new Request('GET', '/customers/1/invoices'))->body);
        self::assertSame(0, $this->cli(['invoice:list', '1'])[0]);
        self::assertSame($response->body, json_decode($this->cli(['invoice:show', '1'])[1], true));
        self::assertStringContainsString('50.0', $this->cli(['invoice:show', '1'])[1]);
        $this->customers->projects()->update(1, 1, ['name' => 'Changed', 'rounding_minutes' => 60]);
        $this->customers->projects()->removeRate(1, 1, 1);
        self::assertSame($response->body, $this->api->handle(new Request('GET', '/invoices/1'))->body);
    }
    public function testFailuresPeriodsAndGaplessYears(): void
    {
        $this->entry('2026-10-25');
        $request = new Request('POST', '/customers/1/invoices', '{"issue_date":"2026-10-31"}');
        self::assertSame(422, $this->api->handle($request)->status);
        self::assertStringContainsString('entry 1', $this->api->handle($request)->json());
        self::assertStringContainsString('entry 1', $this->cli(['invoice:create', '1', '2026-10-31'])[2]);
        self::assertFalse($this->customers->entries()->show(1)->billed);
        $this->rate();
        self::assertSame(422, $this->api->handle(new Request('POST', '/customers/1/invoices', '{"from":"2026-11-01"}'))->status);
        self::assertSame(1, $this->cli(['invoice:create', '1', '2026-10-31', '2026-11-01'])[0]);
        [$code, $out] = $this->cli(['invoice:create', '1', '2026-10-31', '2026-10-25', '2026-10-26']);
        self::assertSame(0, $code);
        self::assertSame('2026-1', json_decode($out, true)['number']);
        self::assertSame(422, $this->api->handle($request)->status);
        $this->entry('2026-10-26');
        self::assertSame('2026-2', $this->api->handle($request)->body['number']);
        $this->entry('2026-10-27');
        self::assertSame('2027-1', json_decode($this->cli(['invoice:create', '1', '2027-01-01'])[1], true)['number']);
        self::assertSame(404, $this->api->handle(new Request('GET', '/invoices/999'))->status);
        self::assertSame(404, $this->api->handle(new Request('POST', '/customers/999/invoices', '{}'))->status);
        self::assertSame(422, $this->api->handle(new Request('POST', '/customers/1/invoices', '{"issue_date":"2026-02-30"}'))->status);
        self::assertSame(422, $this->api->handle(new Request('POST', '/customers/1/invoices', '{"from":"2026-10-26","to":"2026-10-25"}'))->status);
    }
    public function testUnknownCustomerTakesPrecedenceOverNonStringInvoiceDate(): void
    {
        $response = $this->api->handle(new Request('POST', '/customers/999/invoices', '{"issue_date":2}'));
        self::assertSame(404, $response->status);
    }
    public function testApplicableRatesAndCustomerPeriodSelection(): void
    {
        $projects = $this->customers->projects();
        $projects->addRate(1, 1, ['amount' => '100', 'currency' => 'EUR', 'start' => '2026-01-01', 'end' => '2026-10-25']);
        $projects->addRate(1, 1, ['amount' => '120', 'currency' => 'EUR', 'start' => '2026-10-26']);
        $this->entry('2026-10-25'); $this->entry('2026-10-26'); $this->entry('2026-10-27');
        $this->customers->create(['name' => 'Other', 'address' => 'Street', 'email' => 'other@example.com']);
        $projects->create(2, ['name' => 'Other']);
        $this->customers->entries()->save(2, (int) strtotime('2026-10-25T11:00:00Z'), (int) strtotime('2026-10-25T12:00:00Z'), 'Other');
        $r = $this->api->handle(new Request('POST', '/customers/1/invoices', '{"issue_date":"2026-10-31","from":"2026-10-25","to":"2026-10-27"}'));
        self::assertSame(201, $r->status);
        self::assertSame([10000, 12000], array_column($r->body['positions'], 'rate_cents'));
        self::assertSame(110.0, $r->body['net']);
        self::assertFalse($this->customers->entries()->show(3)->billed);
        self::assertFalse($this->customers->entries()->show(4)->billed);
        self::assertSame([], $this->customers->invoices()->all(2));
    }
    public function testWriteFailureRollsBackInvoicePositionsLocksAndCounter(): void
    {
        $this->rate(); $this->entry('2026-10-25'); $this->entry('2026-10-26');
        $this->pdo->exec("CREATE TRIGGER fail_position BEFORE INSERT ON invoice_positions WHEN NEW.entry_id = 2 BEGIN SELECT RAISE(ABORT, 'simulated failure'); END");
        try {
            $this->customers->invoices()->create(1, '2026-10-31');
            self::fail('Expected storage failure');
        } catch (\PDOException $error) {
            self::assertStringContainsString('simulated failure', $error->getMessage());
        }
        self::assertSame([], $this->customers->invoices()->all(1));
        self::assertSame(0, (int) $this->pdo->query('SELECT COUNT(*) FROM invoice_positions')->fetchColumn());
        self::assertFalse($this->customers->entries()->show(1)->billed);
        self::assertFalse($this->customers->entries()->show(2)->billed);
        $this->pdo->exec('DROP TRIGGER fail_position');
        self::assertSame('2026-1', $this->customers->invoices()->create(1, '2026-10-31')->number);
        foreach (['net', 'vat', 'gross'] as $column) {
            self::assertSame('real', $this->pdo->query('SELECT typeof(' . $column . ') FROM invoices')->fetchColumn());
        }
        self::assertSame('real', $this->pdo->query('SELECT typeof(amount) FROM invoice_positions LIMIT 1')->fetchColumn());
    }
    public function testInvalidInvoiceInputsAndMethods(): void
    {
        foreach (['{"issue_date":2}', '{"from":[]}', '{"to":"bad"}', '{"issue_date":"2026-02-30"}'] as $body) {
            self::assertSame(422, $this->api->handle(new Request('POST', '/customers/1/invoices', $body))->status);
        }
        self::assertSame(400, $this->api->handle(new Request('POST', '/customers/1/invoices', '{'))->status);
        self::assertSame(422, $this->api->handle(new Request('POST', '/customers/1/invoices', '[]'))->status);
        foreach (['/invoices/0', '/invoices/999999999999999999999', '/customers/0/invoices', '/invoices/1/extra'] as $path) {
            self::assertSame(404, $this->api->handle(new Request('GET', $path))->status);
        }
        self::assertSame(405, $this->api->handle(new Request('PUT', '/customers/1/invoices'))->status);
        self::assertSame(405, $this->api->handle(new Request('DELETE', '/invoices/1'))->status);
        foreach ([['invoice:create'], ['invoice:show', '0'], ['invoice:show', '999'], ['invoice:unknown', '1'], ['invoice:create', '1', 'bad']] as $args) {
            self::assertSame(1, $this->cli($args)[0]);
        }
    }
    public function testLocksAcrossBothAdaptersAndImport(): void
    {
        $this->rate(); $this->entry('2026-10-25');
        self::assertSame(0, $this->cli(['invoice:create', '1', '2026-10-31'])[0]);
        $body = '{"project_id":1,"start":"2026-10-25T09:00:00Z","end":"2026-10-25T09:30:00Z","description":"Changed"}';
        foreach (['PUT', 'DELETE'] as $method) {
            $r = $this->api->handle(new Request($method, '/entries/1', $body));
            self::assertSame(422, $r->status);
            self::assertStringContainsString('2026-1', $r->json());
        }
        foreach ([['entry:delete', '1'], ['entry:update', '1', '1', '2026-10-26T09:00:00Z', '2026-10-26T10:00:00Z', 'Changed']] as $args) {
            [$code, , $err] = $this->cli($args);
            self::assertSame(1, $code); self::assertStringContainsString('2026-1', $err);
        }
        $csv = "project_id;start;end;description\n1;2026-10-25T09:00:00Z;2026-10-25T10:00:00Z;Overlap\n";
        $r = $this->api->handle(new Request('POST', '/entries/import', $csv));
        self::assertSame(422, $r->status); self::assertStringContainsString('2026-1', $r->json());
        $file = tempnam(sys_get_temp_dir(), 'invoice-csv-');
        self::assertNotFalse($file);
        try {
            file_put_contents($file, $csv);
            [$code, , $err] = $this->cli(['entry:import', $file]);
            self::assertSame(1, $code); self::assertStringContainsString('2026-1', $err);
        } finally { unlink($file); }
        self::assertTrue($this->api->handle(new Request('GET', '/entries'))->body[0]['billed']);
        self::assertTrue(json_decode($this->cli(['entry:list'])[1], true)[0]['billed']);
    }
}
