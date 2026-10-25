<?php
declare(strict_types=1);
namespace TimeTracker\Tests\Integration;
use PHPUnit\Framework\TestCase;
use TimeTracker\Api\Handler;
use TimeTracker\Api\Request;
use TimeTracker\Api\Response;
use TimeTracker\Application\Customers;
use TimeTracker\Console\Application;
use TimeTracker\Infrastructure\Storage\CustomerRepository;
use TimeTracker\Infrastructure\Storage\Database;
final class EntriesTest extends TestCase
{
    private Application $console;
    private Handler $api;
    protected function setUp(): void
    {
        $customers = new Customers(new CustomerRepository(Database::open(':memory:')));
        $customers->create(['name' => 'Ada', 'address' => 'Street', 'email' => 'ada@example.com']);
        $customers->projects()->create(1, ['name' => 'One']);
        $customers->projects()->create(1, ['name' => 'Two']);
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
    /** @param array<string, mixed>|null $body
     * @param array<string, mixed> $query
     */
    private function api(string $method, string $path, ?array $body = null, array $query = []): Response
    {
        return $this->api->handle(new Request($method, $path, $body === null ? '' : json_encode($body, JSON_THROW_ON_ERROR), $query));
    }
    /** @return array{project_id: int, start: string, end: string, description: string} */
    private function input(int $project = 1, string $start = '09:00', string $end = '09:16'): array
    {
        return ['project_id' => $project, 'start' => '2026-10-25T' . $start . ':00Z', 'end' => '2026-10-25T' . $end . ':00Z', 'description' => ' Work '];
    }
    public function testConsoleLifecycleAndDynamicRounding(): void
    {
        self::assertSame(0, $this->cli(['project:update', '1', '1', 'One', '15'])[0]);
        [$code, $out] = $this->cli(['entry:create', '1', '2026-10-25T09:00:00Z', '2026-10-25T09:16:00Z', ' Work ']);
        self::assertSame(0, $code);
        $entry = json_decode($out, true);
        self::assertSame(960, $entry['raw_duration_seconds']);
        self::assertSame(1800, $entry['billable_duration_seconds']);
        self::assertSame('Work', $entry['description']);
        self::assertFalse($entry['billed']);
        self::assertSame($out, $this->cli(['entry:show', '1'])[1]);
        self::assertSame(1, $this->cli(['project:delete', '1', '1'])[0]);
        self::assertSame(0, $this->cli(['project:update', '1', '1', 'One', '10'])[0]);
        self::assertSame(1200, $this->api('GET', '/entries/1')->body['billable_duration_seconds']);
        self::assertSame(200, $this->api('PUT', '/customers/1/projects/1', ['name' => 'One'])->status);
        self::assertSame(1200, $this->api('GET', '/entries/1')->body['billable_duration_seconds']);
        self::assertSame(200, $this->api('PUT', '/customers/1/projects/1', ['name' => 'One', 'rounding_minutes' => null])->status);
        self::assertSame(960, json_decode($this->cli(['entry:show', '1'])[1], true)['billable_duration_seconds']);
        self::assertSame(0, $this->cli(['entry:update', '1', '2', '2026-10-25T10:00:00Z', '2026-10-25T10:30:00Z', 'Changed'])[0]);
        self::assertSame(2, $this->api('GET', '/entries/1')->body['project_id']);
        self::assertSame([], json_decode($this->cli(['entry:list', '1'])[1], true));
        self::assertCount(1, json_decode($this->cli(['entry:list', 'all', '2026-10-25T10:00:00Z', '2026-10-25T11:00:00Z'])[1], true));
        self::assertSame([], json_decode($this->cli(['entry:list', 'all', '2026-10-25T09:00:00Z', '2026-10-25T10:00:00Z'])[1], true));
        self::assertSame(0, $this->cli(['entry:delete', '1'])[0]);
        self::assertSame(1, $this->cli(['entry:show', '1'])[0]);
        self::assertSame(1, $this->cli(['entry:delete', '1'])[0]);
    }
    public function testApiLifecycleFiltersAndRounding(): void
    {
        self::assertSame(200, $this->api('PUT', '/customers/1/projects/1', ['name' => 'One', 'rounding_minutes' => 15])->status);
        $created = $this->api('POST', '/entries', $this->input());
        self::assertSame(201, $created->status);
        self::assertSame(1800, $created->body['billable_duration_seconds']);
        self::assertFalse($created->body['billed']);
        self::assertSame($created->body, $this->api('GET', '/entries/1')->body);
        self::assertSame(422, $this->api('DELETE', '/customers/1/projects/1')->status);
        self::assertSame(200, $this->api('PUT', '/entries/1', $this->input(2, '10:00', '10:15'))->status);
        self::assertSame(900, $this->api('GET', '/entries/1')->body['billable_duration_seconds']);
        self::assertCount(1, $this->api('GET', '/entries', null, ['project_id' => '2', 'from' => '2026-10-25T10:00:00Z', 'to' => '2026-10-25T11:00:00Z'])->body);
        self::assertSame([], $this->api('GET', '/entries', null, ['project_id' => '1'])->body);
        self::assertSame([], $this->api('GET', '/entries', null, ['to' => '2026-10-25T10:00:00Z'])->body);
        self::assertSame(200, $this->api('DELETE', '/entries/1')->status);
        self::assertSame([], $this->api('GET', '/entries')->body);
        self::assertSame(404, $this->api('GET', '/entries/1')->status);
        self::assertSame(404, $this->api('PUT', '/entries/1', $this->input())->status);
        self::assertSame(404, $this->api('DELETE', '/entries/1')->status);
        self::assertSame(0, $this->cli(['project:create', '1', 'Rounded', '5'])[0]);
        self::assertSame(5, $this->api('GET', '/customers/1/projects/3')->body['rounding_minutes']);
        self::assertSame(201, $this->api('POST', '/customers/1/projects', ['name' => 'Rounded too', 'rounding_minutes' => 10080])->status);
    }
    public function testOverlapThroughBothAdapters(): void
    {
        self::assertSame(201, $this->api('POST', '/entries', $this->input(1, '09:00', '10:00'))->status);
        foreach ([[1, '09:15', '09:45'], [2, '08:00', '11:00'], [1, '08:30', '09:30'], [2, '09:30', '10:30']] as [$project, $start, $end]) {
            $input = $this->input($project, $start, $end);
            $response = $this->api('POST', '/entries', $input);
            self::assertSame(422, $response->status);
            self::assertStringContainsString('entry 1', $response->body['errors'][0]);
            [$code, , $err] = $this->cli(['entry:create', (string) $project, $input['start'], $input['end'], 'Work']);
            self::assertSame(1, $code);
            self::assertStringContainsString('entry 1', $err);
        }
        self::assertSame(0, $this->cli(['entry:create', '2', '2026-10-25T10:00:00Z', '2026-10-25T11:00:00Z', 'Touching'])[0]);
        self::assertSame(201, $this->api('POST', '/entries', $this->input(2, '08:00', '09:00'))->status);
        $input = $this->input(1, '09:30', '10:30');
        self::assertSame(422, $this->api('PUT', '/entries/2', $input)->status);
        [$code, , $err] = $this->cli(['entry:update', '2', '1', $input['start'], $input['end'], 'Move']);
        self::assertSame(1, $code);
        self::assertStringContainsString('entry 1', $err);
        self::assertSame('2026-10-25T10:00:00Z', $this->api('GET', '/entries/2')->body['start']);
        self::assertSame(200, $this->api('PUT', '/entries/1', $this->input(1, '09:00', '10:00'))->status);
        // Equivalent instants with different offsets must still conflict.
        self::assertSame(422, $this->api('POST', '/entries', array_replace($this->input(), ['start' => '2026-10-25T11:00:00+02:00', 'end' => '2026-10-25T11:16:00+02:00']))->status);
    }
    public function testInvalidInputsAndRoutesDoNotWrite(): void
    {
        foreach ([['end' => '2026-10-25T09:00:00Z'], ['end' => '2026-10-25T08:00:00Z'], ['start' => '2026-02-30T09:00:00Z'], ['start' => 'tomorrow'], ['start' => "2026-10-25T09:00:00Z\0"], ['start' => '2026-10-25T09:00:00+14:30'], ['start' => '2026-10-25T09:00:00'], ['description' => ' ']] as $bad) {
            $input = array_replace($this->input(), $bad);
            self::assertSame(422, $this->api('POST', '/entries', $input)->status);
            self::assertSame(1, $this->cli(['entry:create', '1', $input['start'], $input['end'], $input['description']])[0]);
        }
        foreach ([['project_id' => '1'], ['project_id' => 0], ['project_id' => []], ['start' => []], ['description' => null]] as $bad) {
            self::assertSame(422, $this->api('POST', '/entries', array_replace($this->input(), $bad))->status);
        }
        self::assertSame(404, $this->api('POST', '/entries', $this->input(999))->status);
        self::assertSame(1, $this->cli(['entry:create', '999', '2026-10-25T09:00:00Z', '2026-10-25T10:00:00Z', 'Work'])[0]);
        foreach ([0, -1, PHP_INT_MAX, '15', 1.5, []] as $step) {
            self::assertSame(422, $this->api('PUT', '/customers/1/projects/1', ['name' => 'One', 'rounding_minutes' => $step])->status);
        }
        foreach (['0', '-1', (string) PHP_INT_MAX, '1.5', '999999999999999999999'] as $step) { self::assertSame(1, $this->cli(['project:update', '1', '1', 'One', $step])[0]); }
        foreach ([['project_id' => []], ['project_id' => '0'], ['from' => []], ['from' => 'bad'], ['from' => '2026-10-26T00:00:00Z', 'to' => '2026-10-25T00:00:00Z']] as $query) {
            self::assertSame(422, $this->api('GET', '/entries', null, $query)->status);
        }
        foreach ([['entry:create'], ['entry:show', '0'], ['entry:show', '999999999999999999999'], ['entry:list', 'all', 'bad'], ['entry:unknown']] as $args) { self::assertSame(1, $this->cli($args)[0]); }
        self::assertSame(400, $this->api->handle(new Request('POST', '/entries', '{'))->status);
        self::assertSame(422, $this->api->handle(new Request('POST', '/entries', '[]'))->status);
        foreach (['/entries/0', '/entries/999999999999999999999', '/entries/no'] as $path) { self::assertSame(404, $this->api('GET', $path)->status); }
        self::assertSame(405, $this->api('PATCH', '/entries')->status);
        self::assertSame(405, $this->api('POST', '/entries/1', $this->input())->status);
        self::assertSame([], $this->api('GET', '/entries')->body);
    }
}
