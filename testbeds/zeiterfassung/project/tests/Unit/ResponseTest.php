<?php
declare(strict_types=1);
namespace TimeTracker\Tests\Unit;

use PHPUnit\Framework\TestCase;
use TimeTracker\Api\Response;

final class ResponseTest extends TestCase
{
    public function testTextBodyIsSerializedVerbatimWithItsContentType(): void
    {
        $response = new Response(200, "<p>Hello & welcome</p>\n", 'text/html');
        self::assertSame("<p>Hello & welcome</p>\n", $response->serialize());
        self::assertSame('text/html', $response->contentType);
    }

    public function testJsonResponsesKeepTheirEncodingAndDefaultType(): void
    {
        $response = new Response(422, ['errors' => ['Invalid'], 'amount' => 1.0]);
        self::assertSame('{"errors":["Invalid"],"amount":1.0}', $response->serialize());
        self::assertSame($response->json(), $response->serialize());
        self::assertSame('application/json', $response->contentType);
    }
}
