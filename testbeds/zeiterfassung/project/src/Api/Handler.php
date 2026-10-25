<?php
declare(strict_types=1);

namespace TimeTracker\Api;

use JsonException;
use TimeTracker\Application\Customers;
use TimeTracker\Application\CustomerNotFound;
use TimeTracker\Domain\ValidationException;

final readonly class Handler
{
    public function __construct(private Customers $customers) {}

    public function handle(Request $request): Response
    {
        try {
            if ($request->path === '/customers') {
                return match ($request->method) {
                    'GET' => new Response(200, array_map(fn ($customer) => $customer->toArray(), $this->customers->all())),
                    'POST' => new Response(201, $this->customers->create($this->input($request))->toArray()),
                    default => new Response(405, ['errors' => ['Method not allowed.']]),
                };
            }
            if (preg_match('#^/customers/([1-9][0-9]*)$#D', $request->path, $matches) !== 1) {
                return new Response(404, ['errors' => ['Route not found.']]);
            }
            $id = filter_var($matches[1], FILTER_VALIDATE_INT);
            if ($id === false) {
                return new Response(404, ['errors' => ['Customer not found.']]);
            }
            return match ($request->method) {
                'GET' => new Response(200, $this->customers->show($id)->toArray()),
                'PUT' => new Response(200, $this->customers->update($id, $this->input($request))->toArray()),
                'DELETE' => $this->delete($id),
                default => new Response(405, ['errors' => ['Method not allowed.']]),
            };
        } catch (ValidationException $error) {
            return new Response(422, ['errors' => $error->errors]);
        } catch (CustomerNotFound $error) {
            return new Response(404, ['errors' => [$error->getMessage()]]);
        } catch (JsonException) {
            return new Response(400, ['errors' => ['Malformed JSON body.']]);
        }
    }

    /** @return array<string, mixed> */
    private function input(Request $request): array
    {
        $value = json_decode($request->body, false, 512, JSON_THROW_ON_ERROR);
        if (!$value instanceof \stdClass) {
            throw new ValidationException(['JSON body must be an object.']);
        }
        return get_object_vars($value);
    }

    private function delete(int $id): Response
    {
        $this->customers->delete($id);
        return new Response(200, ['deleted' => $id]);
    }
}
