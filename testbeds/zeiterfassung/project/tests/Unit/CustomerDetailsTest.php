<?php
declare(strict_types=1);

namespace TimeTracker\Tests\Unit;

use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;
use TimeTracker\Domain\CustomerDetails;
use TimeTracker\Domain\ValidationException;

final class CustomerDetailsTest extends TestCase
{
    public function testTrimsCustomerDetails(): void
    {
        $details = CustomerDetails::fromArray(['name' => ' Ada ', 'address' => ' Main Street ', 'email' => ' ada@example.com ']);
        self::assertSame('Ada', $details->name);
        self::assertSame('Main Street', $details->address);
        self::assertSame('ada@example.com', $details->email);
    }

    /** @return iterable<string, array{array<string, mixed>}> */
    public static function invalidDetails(): iterable
    {
        yield 'missing' => [[]];
        yield 'blank' => [['name' => ' ', 'address' => '', 'email' => '']];
        yield 'wrong types' => [['name' => [], 'address' => 7, 'email' => false]];
        yield 'invalid email' => [['name' => 'Ada', 'address' => 'Street', 'email' => 'bad']];
    }

    /** @param array<string, mixed> $input */
    #[DataProvider('invalidDetails')]
    public function testRejectsInvalidDetails(array $input): void
    {
        $this->expectException(ValidationException::class);
        CustomerDetails::fromArray($input);
    }
}
