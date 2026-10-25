<?php
declare(strict_types=1);

namespace TimeTracker\Domain;

final readonly class Customer
{
    public function __construct(public int $id, public string $name, public string $address, public string $email) {}

    /** @return array{id: int, name: string, address: string, email: string} */
    public function toArray(): array
    {
        return ['id' => $this->id, 'name' => $this->name, 'address' => $this->address, 'email' => $this->email];
    }
}
