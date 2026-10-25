<?php
declare(strict_types=1);

namespace TimeTracker\Domain;

final readonly class CustomerDetails
{
    private function __construct(public string $name, public string $address, public string $email) {}

    /** @param array<string, mixed> $input */
    public static function fromArray(array $input): self
    {
        $errors = [];
        $values = [];
        foreach (['name', 'address', 'email'] as $field) {
            $values[$field] = is_string($input[$field] ?? null) ? trim($input[$field]) : '';
            if ($values[$field] === '') {
                $errors[] = ucfirst($field) . ' is required and must be a non-empty string.';
            } elseif (preg_match('//u', $values[$field]) !== 1) {
                $errors[] = ucfirst($field) . ' must be valid UTF-8.';
                $values[$field] = '';
            }
        }
        if ($values['email'] !== '' && filter_var($values['email'], FILTER_VALIDATE_EMAIL) === false) {
            $errors[] = 'Email must be a valid email address.';
        }
        if ($errors !== []) {
            throw new ValidationException($errors);
        }
        return new self($values['name'], $values['address'], $values['email']);
    }
}
