<?php
declare(strict_types=1);

namespace TimeTracker\Tests\Integration;

use PHPUnit\Framework\TestCase;
use TimeTracker\Api\Handler;
use TimeTracker\Api\Request;
use TimeTracker\Api\Response;
use TimeTracker\Application\Customers;
use TimeTracker\Application\Projects;
use TimeTracker\Console\Application;
use TimeTracker\Infrastructure\Storage\CustomerRepository;
use TimeTracker\Infrastructure\Storage\Database;

final class ProjectsTest extends TestCase
{
    private Application $console;
    private Handler $api;
    private Projects $projects;
    private \PDO $pdo;

    protected function setUp(): void
    {
        $this->pdo = Database::open(':memory:');
        $customers = new Customers(new CustomerRepository($this->pdo));
        $customers->create(['name' => 'Ada', 'address' => 'Street', 'email' => 'ada@example.com']);
        $customers->create(['name' => 'Grace', 'address' => 'Street', 'email' => 'grace@example.com']);
        $this->projects = $customers->projects();
        $this->console = new Application($customers);
        $this->api = new Handler($customers);
    }

    /** @param list<string> $args
     * @return array{int, string, string}
     */
    private function cli(array $args): array
    {
        $out = $err = '';
        $code = $this->console->run($args, static function (string $s) use (&$out): void { $out .= $s; }, static function (string $s) use (&$err): void { $err .= $s; });
        return [$code, $out, $err];
    }

    /** @param array<string, mixed>|null $body */
    private function api(string $method, string $path, ?array $body = null): Response
    {
        return $this->api->handle(new Request($method, $path, $body === null ? '' : json_encode($body, JSON_THROW_ON_ERROR)));
    }

    public function testConsoleLifecycleAndRules(): void
    {
        self::assertSame([0, "[]\n", ''], $this->cli(['project:list', '1']));
        self::assertSame(1, $this->cli(['project:create', '999', 'Work'])[0]);
        self::assertSame(1, $this->cli(['project:create', '1', ' '])[0]);
        [$code, $out] = $this->cli(['project:create', '1', ' Work ']);
        self::assertSame(0, $code);
        self::assertSame(['id' => 1, 'customer_id' => 1, 'name' => 'Work'], json_decode($out, true));
        self::assertSame($out, $this->cli(['project:show', '1', '1'])[1]);
        self::assertSame(1, $this->cli(['customer:delete', '1'])[0]);
        self::assertSame(1, $this->cli(['project:show', '2', '1'])[0]);
        self::assertSame(0, $this->cli(['project:update', '1', '1', 'Changed'])[0]);
        self::assertSame('Changed', $this->api('GET', '/customers/1/projects/1')->body['name']);
        self::assertSame(0, $this->cli(['rate:add', '1', '1', '12.30', 'EUR', '2026-01-01', '2026-01-31'])[0]);
        self::assertSame(0, $this->cli(['rate:add', '1', '1', '15', 'EUR', '2026-03-01'])[0]);
        self::assertSame(1, $this->cli(['rate:add', '1', '1', '20', 'EUR', '2026-01-31', '2026-02-01'])[0]);
        self::assertSame(1, $this->cli(['rate:add', '1', '1', '20', 'EUR', '2027-01-01'])[0]);
        $rates = json_decode($this->cli(['rate:list', '1', '1'])[1], true);
        self::assertSame(['12.30', '15.00'], array_column($rates, 'amount'));
        self::assertSame(1230, (int) $this->pdo->query('SELECT cents FROM rates WHERE id = 1')->fetchColumn());
        self::assertSame('integer', $this->pdo->query('SELECT typeof(cents) FROM rates WHERE id = 1')->fetchColumn());
        self::assertSame(1, $this->cli(['rate:remove', '2', '1', '1'])[0]);
        self::assertSame(0, $this->cli(['rate:remove', '1', '1', '1'])[0]);
        self::assertSame(1, $this->cli(['rate:remove', '1', '1', '1'])[0]);
        self::assertSame(0, $this->cli(['project:delete', '1', '1'])[0]);
        self::assertSame(0, (int) $this->pdo->query('SELECT COUNT(*) FROM rates')->fetchColumn());
        self::assertSame(0, $this->cli(['customer:delete', '1'])[0]);
        foreach ([['project:list', '0'], ['project:list', '999999999999999999999'], ['rate:add', '1'], ['project:list', '1', 'extra']] as $args) {
            self::assertSame(1, $this->cli($args)[0]);
        }
    }

    public function testApiLifecycleAndRules(): void
    {
        $base = '/customers/1/projects';
        self::assertSame([], $this->api('GET', $base)->body);
        self::assertSame(404, $this->api('POST', '/customers/999/projects', ['name' => 'Work'])->status);
        self::assertSame(422, $this->api('POST', $base, ['name' => []])->status);
        self::assertSame(201, $this->api('POST', $base, ['name' => 'Work'])->status);
        self::assertCount(1, $this->api('GET', $base)->body);
        self::assertSame('Work', $this->api('GET', $base . '/1')->body['name']);
        self::assertSame(422, $this->api('DELETE', '/customers/1')->status);
        self::assertSame(200, $this->api('PUT', $base . '/1', ['name' => 'Changed'])->status);
        self::assertSame('Changed', json_decode($this->cli(['project:show', '1', '1'])[1], true)['name']);
        self::assertSame(422, $this->api('PUT', $base . '/1', ['name' => ''])->status);
        $rate = ['amount' => '0.01', 'currency' => 'EUR', 'start' => '2026-01-01', 'end' => '2026-01-31'];
        self::assertSame(201, $this->api('POST', $base . '/1/rates', $rate)->status);
        self::assertSame(422, $this->api('POST', $base . '/1/rates', $rate)->status);
        self::assertSame(201, $this->api('POST', $base . '/1/rates', ['amount' => '10', 'currency' => 'EUR', 'start' => '2026-03-01'])->status);
        self::assertSame('0.01', $this->api('GET', $base . '/1/rates')->body[0]['amount']);
        self::assertSame(2, $this->projects->applicableRate(1, 1, '2028-01-01')?->id);
        self::assertNull($this->projects->applicableRate(1, 1, '2026-02-01'));
        self::assertSame(1, $this->projects->applicableRate(1, 1, '2026-01-01')?->id);
        self::assertSame(1, $this->projects->applicableRate(1, 1, '2026-01-31')?->id);
        self::assertSame(404, $this->api('DELETE', '/customers/2/projects/1/rates/1')->status);
        self::assertSame(200, $this->api('DELETE', $base . '/1/rates/1')->status);
        self::assertSame(404, $this->api('DELETE', $base . '/1/rates/1')->status);
        self::assertSame(200, $this->api('DELETE', $base . '/1')->status);
        self::assertSame(404, $this->api('GET', $base . '/1')->status);
        self::assertSame(200, $this->api('DELETE', '/customers/1')->status);
    }

    public function testInvalidRatesAndRoutesDoNotWrite(): void
    {
        $this->projects->create(1, ['name' => 'Work']);
        $rate = ['amount' => '10', 'currency' => 'EUR', 'start' => '2026-01-01'];
        foreach ([['amount' => '1.001'], ['amount' => '-1'], ['amount' => '1e2'], ['amount' => 1.2], ['amount' => '9999999999'], ['currency' => 'eur'], ['start' => '2026-02-30'], ['start' => '2026-1-01'], ['end' => '2025-12-31'], ['end' => '']] as $bad) {
            $input = array_replace($rate, $bad);
            self::assertSame(422, $this->api('POST', '/customers/1/projects/1/rates', $input)->status);
            if (is_string($input['amount'])) {
                $args = ['rate:add', '1', '1', $input['amount'], $input['currency'], $input['start']];
                if (isset($input['end'])) { $args[] = $input['end']; }
                self::assertSame(1, $this->cli($args)[0]);
            }
        }
        self::assertSame([], $this->api('GET', '/customers/1/projects/1/rates')->body);
        self::assertSame(404, $this->api('GET', '/customers/1/projects/999/rates')->status);
        self::assertSame(405, $this->api('PATCH', '/customers/1/projects/1')->status);
        self::assertSame(405, $this->api('PUT', '/customers/1/projects/1/rates')->status);
        self::assertSame(405, $this->api('GET', '/customers/1/projects/1/rates/1')->status);
        self::assertSame(400, $this->api->handle(new Request('POST', '/customers/1/projects', '{'))->status);
        foreach (['/customers/0/projects', '/customers/1/projects/999999999999999999999', '/customers/1/projects/1/rates/0'] as $path) {
            self::assertSame(404, $this->api('GET', $path)->status);
        }
    }
}
