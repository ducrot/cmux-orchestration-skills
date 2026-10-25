<?php
declare(strict_types=1);

namespace TimeTracker\Api;

use JsonException;
use TimeTracker\Application\Customers;
use TimeTracker\Export\InvoiceExport;
use TimeTracker\Infrastructure\Configuration;
use TimeTracker\Application\EntryNotFound;
use TimeTracker\Application\InvoiceNotFound;
use TimeTracker\Domain\TimeEntry;
use TimeTracker\Application\ProjectNotFound;
use TimeTracker\Application\CustomerNotFound;
use TimeTracker\Domain\ValidationException;

final readonly class Handler
{
    public function __construct(private Customers $customers, private ?Configuration $configuration = null) {}

    public function handle(Request $request): Response
    {
        try {
            if (str_contains($request->path, '/invoices')) { return $this->invoiceRequest($request); }
            if ($request->path === '/entries' || str_starts_with($request->path, '/entries/')) {
                return $this->entryRequest($request);
            }
            if (str_contains($request->path, '/projects')) {
                return $this->projectRequest($request);
            }
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
        } catch (CustomerNotFound|ProjectNotFound|EntryNotFound|InvoiceNotFound $error) {
            return new Response(404, ['errors' => [$error->getMessage()]]);
        } catch (JsonException) {
            return new Response(400, ['errors' => ['Malformed JSON body.']]);
        }
    }

    private function invoiceRequest(Request $request): Response
    {
        if (preg_match('#^/invoices/([1-9][0-9]*)/export$#D', $request->path, $m) === 1) {
            if ($request->method !== 'GET') { return new Response(405, ['errors' => ['Method not allowed.']]); }
            $id = filter_var($m[1], FILTER_VALIDATE_INT);
            if ($id === false) { throw new InvoiceNotFound(); }
            $format = $request->query['format'] ?? 'markdown';
            if (!is_string($format)) { throw new ValidationException(['Export format must be markdown or html.']); }
            $export = new InvoiceExport($this->customers, ($this->configuration ?? Configuration::fromEnvironment())->issuer);
            return new Response(200, $export->render($id, $format), InvoiceExport::CONTENT_TYPES[$format]);
        }
        $invoices = $this->customers->invoices();
        if (preg_match('#^/invoices/([1-9][0-9]*)$#D', $request->path, $m) === 1) {
            $id = filter_var($m[1], FILTER_VALIDATE_INT);
            if ($id === false) { throw new InvoiceNotFound(); }
            return $request->method === 'GET' ? new Response(200, $invoices->show($id)->toArray()) : new Response(405, ['errors' => ['Method not allowed.']]);
        }
        if (preg_match('#^/customers/([1-9][0-9]*)/invoices$#D', $request->path, $m) !== 1) { return new Response(404, ['errors' => ['Route not found.']]); }
        $id = filter_var($m[1], FILTER_VALIDATE_INT);
        if ($id === false) { return new Response(404, ['errors' => ['Customer not found.']]); }
        if ($request->method === 'GET') { return new Response(200, array_map(fn ($invoice) => $invoice->toArray(), $invoices->all($id))); }
        if ($request->method !== 'POST') { return new Response(405, ['errors' => ['Method not allowed.']]); }
        $this->customers->show($id);
        $input = $this->input($request);
        foreach (['issue_date', 'from', 'to'] as $key) {
            if (isset($input[$key]) && !is_string($input[$key])) { throw new ValidationException(['Invoice dates must be YYYY-MM-DD strings.']); }
        }
        return new Response(201, $invoices->create($id, $input['issue_date'] ?? null, $input['from'] ?? null, $input['to'] ?? null)->toArray());
    }

    private function entryRequest(Request $request): Response
    {
        if ($request->path === '/entries/import') {
            return $request->method === 'POST'
                ? new Response(201, $this->customers->entries()->importCsv($request->body))
                : new Response(405, ['errors' => ['Method not allowed.']]);
        }
        if (preg_match('#^/entries(?:/([1-9][0-9]*))?$#D', $request->path, $matches) !== 1) { return new Response(404, ['errors' => ['Route not found.']]); }
        $id = isset($matches[1]) ? filter_var($matches[1], FILTER_VALIDATE_INT) : null;
        if ($id === false) { throw new EntryNotFound(); }
        $entries = $this->customers->entries();
        if ($id === null && $request->method === 'GET') {
            $project = $request->query['project_id'] ?? null;
            if ($project !== null) { $project = $this->entryProjectId($project); }
            return new Response(200, array_map($this->entryRepresentation(...), $entries->all($project, $this->entryQueryTimestamp($request, 'from'), $this->entryQueryTimestamp($request, 'to'))));
        }
        if ($id !== null && $request->method === 'GET') { return new Response(200, $this->entryRepresentation($entries->show($id))); }
        if ($id !== null && $request->method === 'DELETE') { $entries->delete($id); return new Response(200, ['deleted' => $id]); }
        if (!(($id === null && $request->method === 'POST') || ($id !== null && $request->method === 'PUT'))) { return new Response(405, ['errors' => ['Method not allowed.']]); }
        $input = $this->input($request);
        $project = $input['project_id'] ?? null;
        if (!is_int($project) || $project < 1) { throw new ValidationException(['Project ID must be a positive integer.']); }
        if (!is_string($input['start'] ?? null) || !is_string($input['end'] ?? null)) { throw new ValidationException(['Start and end must be timestamps.']); }
        $start = $this->entryTimestamp($input['start']);
        $end = $this->entryTimestamp($input['end']);
        if ($end <= $start) { throw new ValidationException(['End must be after start.']); }
        $description = $input['description'] ?? null;
        if (!is_string($description) || trim($description) === '' || preg_match('//u', $description) !== 1) { throw new ValidationException(['Description must be a non-empty UTF-8 string.']); }
        return new Response($id === null ? 201 : 200, $this->entryRepresentation($entries->save($project, $start, $end, trim($description), $id)));
    }

    private function entryProjectId(mixed $value): int
    {
        if ((!is_string($value) && !is_int($value)) || preg_match('/^[1-9][0-9]*$/D', (string) $value) !== 1 || ($id = filter_var($value, FILTER_VALIDATE_INT)) === false) { throw new ValidationException(['Project ID must be a positive integer.']); }
        return $id;
    }

    private function entryQueryTimestamp(Request $request, string $key): ?int
    {
        if (!array_key_exists($key, $request->query)) { return null; }
        if (!is_string($request->query[$key])) { throw new ValidationException(['Date filters must be timestamps.']); }
        return $this->entryTimestamp($request->query[$key]);
    }

    private function entryTimestamp(string $value): int
    {
        if (preg_match('/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-](?:(?:0[0-9]|1[0-3]):[0-5][0-9]|14:00))$/D', $value) !== 1) {
            throw new ValidationException(['Timestamps must use YYYY-MM-DDTHH:MM:SS with Z or a timezone offset.']);
        }
        $date = \DateTimeImmutable::createFromFormat('!Y-m-d\\TH:i:sP', $value);
        $errors = \DateTimeImmutable::getLastErrors();
        if ($date === false || ($errors !== false && ($errors['warning_count'] > 0 || $errors['error_count'] > 0))) {
            throw new ValidationException(['Timestamps must be valid calendar dates and times.']);
        }
        return $date->getTimestamp();
    }

    /** @return array{id: int, project_id: int, start: string, end: string, description: string, raw_duration_seconds: int, billable_duration_seconds: int, billed: bool} */
    private function entryRepresentation(TimeEntry $entry): array
    {
        return ['id' => $entry->id, 'project_id' => $entry->projectId, 'start' => gmdate('Y-m-d\\TH:i:s\\Z', $entry->start), 'end' => gmdate('Y-m-d\\TH:i:s\\Z', $entry->end), 'description' => $entry->description, 'raw_duration_seconds' => $entry->rawDuration(), 'billable_duration_seconds' => $entry->billableDuration(), 'billed' => $entry->billed];
    }

    private function projectRequest(Request $request): Response
    {
        if (preg_match('#^/customers/([1-9][0-9]*)/projects(?:/([1-9][0-9]*)(/rates(?:/([1-9][0-9]*))?)?)?$#D', $request->path, $matches) !== 1) {
            return new Response(404, ['errors' => ['Route not found.']]);
        }
        $ids = [];
        foreach ([1, 2, 4] as $index) {
            if (($matches[$index] ?? '') !== '') {
                $id = filter_var($matches[$index], FILTER_VALIDATE_INT);
                if ($id === false) {
                    return new Response(404, ['errors' => ['Route not found.']]);
                }
                $ids[$index] = $id;
            }
        }
        $customerId = $ids[1];
        $projectId = $ids[2] ?? null;
        $projects = $this->customers->projects();
        if ($projectId !== null && ($matches[3] ?? '') !== '') {
            if (isset($ids[4])) {
                if ($request->method !== 'DELETE') {
                    return new Response(405, ['errors' => ['Method not allowed.']]);
                }
                $projects->removeRate($customerId, $projectId, $ids[4]);
                return new Response(200, ['deleted' => $ids[4]]);
            }
            return match ($request->method) {
                'GET' => new Response(200, array_map(fn ($rate) => $rate->toArray(), $projects->rates($customerId, $projectId))),
                'POST' => new Response(201, $projects->addRate($customerId, $projectId, $this->input($request))->toArray()),
                default => new Response(405, ['errors' => ['Method not allowed.']]),
            };
        }
        if ($projectId === null) {
            return match ($request->method) {
                'GET' => new Response(200, array_map(fn ($project) => $project->toArray(), $projects->all($customerId))),
                'POST' => new Response(201, $projects->create($customerId, $this->input($request))->toArray()),
                default => new Response(405, ['errors' => ['Method not allowed.']]),
            };
        }
        if ($request->method === 'DELETE') {
            $projects->delete($customerId, $projectId);
            return new Response(200, ['deleted' => $projectId]);
        }
        return match ($request->method) {
            'GET' => new Response(200, $projects->show($customerId, $projectId)->toArray()),
            'PUT' => new Response(200, $projects->update($customerId, $projectId, $this->input($request))->toArray()),
            default => new Response(405, ['errors' => ['Method not allowed.']]),
        };
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
