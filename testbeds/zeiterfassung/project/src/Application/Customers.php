<?php
declare(strict_types=1);

namespace TimeTracker\Application;

use TimeTracker\Domain\Customer;
use TimeTracker\Domain\CustomerDetails;
use TimeTracker\Infrastructure\Storage\CustomerRepository;

final readonly class Customers
{
    public function __construct(private CustomerRepository $repository) {}

    public function projects(): Projects { return new Projects($this->repository->projects(), $this); }

    /** @param array<string, mixed> $input */
    public function create(array $input): Customer
    {
        return $this->repository->create(CustomerDetails::fromArray($input));
    }

    /** @return list<Customer> */
    public function all(): array { return $this->repository->all(); }

    public function show(int $id): Customer
    {
        return $this->repository->find($id) ?? throw new CustomerNotFound($id);
    }

    /** @param array<string, mixed> $input */
    public function update(int $id, array $input): Customer
    {
        $this->show($id);
        return $this->repository->update($id, CustomerDetails::fromArray($input));
    }

    public function delete(int $id): void
    {
        $this->show($id);
        $this->repository->delete($id);
    }
}
