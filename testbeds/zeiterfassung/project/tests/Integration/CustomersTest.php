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

final class CustomersTest extends TestCase
{
    private Application $console;
    private Handler $api;

    protected function setUp(): void
    {
        $customers = new Customers(new CustomerRepository(Database::open(':memory:')));
        $this->console = new Application($customers);
        $this->api = new Handler($customers);
    }

    /**
     * @param list<string> $args
     * @return array{int, string, string}
     */
    private function cli(array $args): array
    {
        $out = $err = '';
        $code = $this->console->run($args, static function (string $s) use (&$out): void { $out .= $s; }, static function (string $s) use (&$err): void { $err .= $s; });
        return [$code, $out, $err];
    }

    public function testConsoleCustomerLifecycleAndSharedApiStorage(): void
    {
        [$code, $help] = $this->cli([]);
        self::assertSame(0, $code);
        foreach (['create', 'list', 'show', 'update', 'delete'] as $action) {
            self::assertStringContainsString('customer:' . $action, $help);
        }
        self::assertSame([0, "[]\n", ''], $this->cli(['customer:list']));
        [$code, $out, $err] = $this->cli(['customer:create', 'Ada', 'Street', 'ada@example.com']);
        self::assertSame(0, $code);
        self::assertSame('', $err);
        self::assertSame(['id' => 1, 'name' => 'Ada', 'address' => 'Street', 'email' => 'ada@example.com'], json_decode($out, true));
        self::assertSame($out, $this->cli(['customer:show', '1'])[1]);
        self::assertCount(1, json_decode($this->cli(['customer:list'])[1], true));
        self::assertSame('Ada', $this->api->handle(new Request('GET', '/customers/1'))->body['name']);
        [$code, $out] = $this->cli(['customer:update', '1', 'Grace', 'New Street', 'grace@example.com']);
        self::assertSame(0, $code);
        self::assertSame('Grace', json_decode($out, true)['name']);
        self::assertSame([0, "{\"deleted\":1}\n", ''], $this->cli(['customer:delete', '1']));
        self::assertSame([0, "[]\n", ''], $this->cli(['customer:list']));
        foreach (['customer:show', 'customer:delete'] as $command) {
            [$code, $out, $err] = $this->cli([$command, '1']);
            self::assertSame(1, $code);
            self::assertSame('', $out);
            self::assertStringContainsString('not found', $err);
        }
    }

    public function testConsoleRejectsInvalidCommandsAndDoesNotPersistInvalidWrites(): void
    {
        foreach ([['unknown'], ['customer:create'], ['customer:list', 'extra'], ['customer:show', '0'], ['customer:show', '1junk'], ['customer:create', '', 'Street', 'bad']] as $args) {
            [$code, $out, $err] = $this->cli($args);
            self::assertSame(1, $code);
            self::assertSame('', $out);
            self::assertNotSame('', $err);
        }
        self::assertSame([], $this->api->handle(new Request('GET', '/customers'))->body);
        $this->cli(['customer:create', 'Ada', 'Street', 'ada@example.com']);
        self::assertSame(1, $this->cli(['customer:update', '1', 'Changed', 'Street', 'invalid'])[0]);
        self::assertSame('Ada', $this->api->handle(new Request('GET', '/customers/1'))->body['name']);
        self::assertSame(1, $this->cli(['customer:update', '999', 'Ada', 'Street', 'ada@example.com'])[0]);
    }

    public function testApiCustomerLifecycle(): void
    {
        self::assertSame([], $this->api->handle(new Request('GET', '/customers'))->body);
        $response = $this->api->handle(new Request('POST', '/customers', '{"name":"Ada","address":"Street","email":"ada@example.com"}'));
        self::assertSame(201, $response->status);
        self::assertSame(['id' => 1, 'name' => 'Ada', 'address' => 'Street', 'email' => 'ada@example.com'], json_decode($response->json(), true));
        self::assertSame($response->body, $this->api->handle(new Request('GET', '/customers/1'))->body);
        self::assertSame([$response->body], $this->api->handle(new Request('GET', '/customers'))->body);
        $updated = $this->api->handle(new Request('PUT', '/customers/1', '{"name":"Grace","address":"New Street","email":"grace@example.com"}'));
        self::assertSame(200, $updated->status);
        self::assertSame('Grace', $updated->body['name']);
        self::assertSame('New Street', $updated->body['address']);
        self::assertSame('grace@example.com', $updated->body['email']);
        self::assertSame($updated->body, json_decode($this->cli(['customer:show', '1'])[1], true));
        $deleted = $this->api->handle(new Request('DELETE', '/customers/1'));
        self::assertSame(200, $deleted->status);
        self::assertSame(['deleted' => 1], $deleted->body);
        self::assertSame([], $this->api->handle(new Request('GET', '/customers'))->body);
        foreach (['GET', 'PUT', 'DELETE'] as $method) {
            self::assertSame(404, $this->api->handle(new Request($method, '/customers/1', '{"name":"Ada","address":"Street","email":"ada@example.com"}'))->status);
        }
    }

    public function testApiValidationAndRoutingErrors(): void
    {
        foreach (['{}', '[]', 'null', '{"name":[],"address":5,"email":false}', '{"name":"Ada","address":"Street","email":"bad"}'] as $body) {
            $response = $this->api->handle(new Request('POST', '/customers', $body));
            self::assertSame(422, $response->status);
            self::assertNotEmpty($response->body['errors']);
        }
        self::assertSame(400, $this->api->handle(new Request('POST', '/customers', '{'))->status);
        self::assertSame([], $this->api->handle(new Request('GET', '/customers'))->body);
        $this->cli(['customer:create', 'Ada', 'Street', 'ada@example.com']);
        self::assertSame(422, $this->api->handle(new Request('PUT', '/customers/1', '{}'))->status);
        self::assertSame('Ada', $this->api->handle(new Request('GET', '/customers/1'))->body['name']);
        self::assertSame(405, $this->api->handle(new Request('PATCH', '/customers/1'))->status);
        self::assertSame(405, $this->api->handle(new Request('DELETE', '/customers'))->status);
        foreach (['/unknown', '/customers/0', '/customers/1junk', '/customers/9999999999999999999999999'] as $path) {
            self::assertSame(404, $this->api->handle(new Request('GET', $path))->status);
        }
    }
}
