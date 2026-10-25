<?php
declare(strict_types=1);

namespace TimeTracker\Infrastructure\Storage;

use PDO;
use PDOException;
use TimeTracker\Domain\Customer;
use TimeTracker\Domain\CustomerDetails;
use TimeTracker\Domain\ValidationException;

final readonly class CustomerRepository
{
    public function __construct(private PDO $pdo) {}

    public function projects(): ProjectRepository { return new ProjectRepository($this->pdo); }

    public function create(CustomerDetails $details): Customer
    {
        $statement = $this->pdo->prepare('INSERT INTO customers (name, address, email) VALUES (?, ?, ?)');
        $statement->execute([$details->name, $details->address, $details->email]);
        return new Customer((int) $this->pdo->lastInsertId(), $details->name, $details->address, $details->email);
    }

    /** @return list<Customer> */
    public function all(): array
    {
        return array_map($this->hydrate(...), $this->pdo->query('SELECT * FROM customers ORDER BY id')->fetchAll());
    }

    public function find(int $id): ?Customer
    {
        $statement = $this->pdo->prepare('SELECT * FROM customers WHERE id = ?');
        $statement->execute([$id]);
        $row = $statement->fetch();
        return $row === false ? null : $this->hydrate($row);
    }

    public function update(int $id, CustomerDetails $details): Customer
    {
        $statement = $this->pdo->prepare('UPDATE customers SET name = ?, address = ?, email = ? WHERE id = ?');
        $statement->execute([$details->name, $details->address, $details->email, $id]);
        return new Customer($id, $details->name, $details->address, $details->email);
    }

    public function delete(int $id): void
    {
        $statement = $this->pdo->prepare('DELETE FROM customers WHERE id = ?');
        try {
            $statement->execute([$id]);
        } catch (PDOException $error) {
            if ($error->getCode() === '23000') {
                throw new ValidationException(['Customer with projects cannot be deleted.']);
            }
            throw $error;
        }
    }

    /** @param array<string, mixed> $row */
    private function hydrate(array $row): Customer
    {
        return new Customer((int) $row['id'], (string) $row['name'], (string) $row['address'], (string) $row['email']);
    }
}
