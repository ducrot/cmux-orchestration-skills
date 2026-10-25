# Time Tracker

A PHP 8.3 application for a solo developer, with a console interface and a JSON API. Customer records contain a name, address and email. All three fields are required; email must be valid. Leading and trailing whitespace is removed.

## Installation

Install PHP 8.3 or newer with PDO and SQLite extensions, and Composer, then run:

```sh
composer install --no-interaction --no-scripts --no-plugins
php bin/console
```

The console lists commands. On first use the application creates its SQLite database and applies numbered migrations automatically. Applied versions are stored in `schema_migrations`; subsequent starts only apply missing versions.

## Configuration

Edit `config/project.php`: `database_path` selects the SQLite file, and `issuer` contains `name`, `address` and `email` for invoice issuer details. The default database is `var/time-tracker.sqlite`. Set `TIME_TRACKER_CONFIG` to the path of another PHP configuration file to select it for both entry points. Use an absolute database path (or one based on the configuration file's `__DIR__`) to keep it independent of the working directory. `:memory:` is available for in-process use.

## Console

```sh
php bin/console help
php bin/console customer:create "Ada Example" "1 Main Street" "ada@example.com"
php bin/console customer:list
php bin/console customer:show 1
php bin/console customer:update 1 "Ada Updated" "2 Main Street" "ada@example.com"
php bin/console customer:delete 1
```

`help`, `--help`, `list`, or no arguments list the available commands. Create and update take all three fields in the order name, address, email; update replaces the full record. Successful customer commands emit JSON to standard output, including an object for create/show/update, an array for list and `{"deleted":1}` for delete. IDs are positive integers. Invalid arguments, validation failures and unknown customers produce a message on standard error and exit code 1; success exits 0.

## Projects and hourly rates

Projects belong to an existing customer and have a required name. Names are trimmed; update replaces the name. A customer with projects cannot be deleted. Deleting a project removes its rates.

```sh
php bin/console project:create 1 "Website"
php bin/console project:list 1
php bin/console project:show 1 1
php bin/console project:update 1 1 "Website maintenance"
php bin/console rate:add 1 1 "95.50" EUR 2026-01-01 2026-06-30
php bin/console rate:add 1 1 "100.00" EUR 2026-07-01
php bin/console rate:list 1 1
php bin/console rate:remove 1 1 1
php bin/console project:delete 1 1
```

Project commands take the customer ID first, then the project ID where needed. Rate commands take customer and project IDs; removal also takes the rate ID. `rate:add` takes amount, currency, start, and an optional end. Dates use valid `YYYY-MM-DD` calendar dates. Both period boundaries are inclusive; an omitted end is open. Periods of the same project cannot overlap, even when their currencies differ. Gaps are allowed, and no rate applies in a gap. An application lookup is available as `Projects::applicableRate(customerId, projectId, date)`, returning a `Rate` or `null`.

Amounts are non-negative decimal strings with up to two fractional digits and nine integer digits; currency is a three-letter uppercase code (for example `EUR`). Amounts are stored as integer cents and returned as decimal strings with two fractional digits. These commands use the same JSON output, exit codes and error conventions as customer commands. Project objects contain `id`, `customer_id`, `name`, `rounding_minutes`; rate objects contain `id`, `project_id`, `amount`, `currency`, `start`, `end` (`null` for an open end).

## JSON API

Run from the project root:

```sh
php -S 127.0.0.1:8080 -t public public/index.php
```

The router argument sends all routes to the JSON entry point. For example:

```sh
curl -i -X POST http://127.0.0.1:8080/customers \
  -H 'Content-Type: application/json' \
  -d '{"name":"Ada Example","address":"1 Main Street","email":"ada@example.com"}'
```

| Method | Route | Response |
| --- | --- | --- |
| GET | `/customers` | 200, array of customers ordered by ID |
| POST | `/customers` | 201, created customer |
| GET | `/customers/{id}` | 200, customer |
| PUT | `/customers/{id}` | 200, updated customer (full replacement) |
| DELETE | `/customers/{id}` | 200, `{"deleted":1}` |

POST and PUT accept a JSON object with `name`, `address` and `email` strings. Customer objects contain `id`, `name`, `address` and `email`. Validation failures return 422 and `{"errors":["..."]}`. Unknown customers and routes return 404, unsupported methods return 405, and malformed JSON returns 400, all with an `errors` array. Unexpected server errors return a generic JSON 500 response.

Project and rate routes:

| Method | Route | Response |
| --- | --- | --- |
| GET | `/customers/{customerId}/projects` | 200, projects ordered by ID |
| POST | `/customers/{customerId}/projects` | 201, project; body `{"name":"Website"}` |
| GET | `/customers/{customerId}/projects/{projectId}` | 200, project |
| PUT | `/customers/{customerId}/projects/{projectId}` | 200, project; body `{"name":"New name"}` |
| DELETE | `/customers/{customerId}/projects/{projectId}` | 200, `{"deleted":1}` |
| GET | `/customers/{customerId}/projects/{projectId}/rates` | 200, rates ordered by start date then ID |
| POST | `/customers/{customerId}/projects/{projectId}/rates` | 201, rate |
| DELETE | `/customers/{customerId}/projects/{projectId}/rates/{rateId}` | 200, `{"deleted":1}` |

Rate POST bodies use strings for `amount`, `currency` and `start`, for example `{"amount":"95.50","currency":"EUR","start":"2026-01-01","end":"2026-06-30"}`. Omit `end` or use `null` for an open period. All rules described above apply to API writes. Overlap and blocked customer deletion return 422. Unknown customers, projects, rates and mismatched parent IDs return 404. Malformed JSON returns 400 and unsupported methods return 405.

## Development

The `TimeTracker\` PSR-4 root maps to `src/`: `Domain` holds models and validation rules, `Application` coordinates customer operations, `Infrastructure` holds configuration, PDO storage and migrations, and `Console` and `Api` adapt the service for each interface.

`Console\Application::run()` accepts argument values and output callbacks and returns an exit code. `Api\Handler::handle()` accepts a `Request` value and returns a `Response` with status, body and JSON serialization. Both can share an application service without starting processes.

Run the unit and integration suites and PHPStan level 6:

```sh
vendor/bin/phpunit
vendor/bin/phpstan analyse --no-progress
```

Integration tests use in-memory SQLite for customer operations and migrations; a temporary file database additionally verifies configuration and persistence across connections. Commit `composer.lock` when updating dependencies to pin installations.

## Time entries and rounding

A project's `rounding_minutes` is `null` (no rounding, the default) or a positive integer step in minutes. Set it on project creation or update. API project bodies accept `rounding_minutes`, for example `{"name":"Website","rounding_minutes":15}`; `null` or `"none"` disables rounding. Omitting it on update preserves the existing setting. Project responses include this field.

```sh
php bin/console project:create 1 "Website" 15
php bin/console project:update 1 1 "Website" 10
php bin/console project:update 1 1 "Website" none
php bin/console entry:create 1 2026-10-25T09:00:00Z 2026-10-25T09:16:00Z "Development"
php bin/console entry:list
php bin/console entry:list 1
php bin/console entry:list all 2026-10-25T00:00:00Z 2026-10-26T00:00:00Z
php bin/console entry:show 1
php bin/console entry:update 1 1 2026-10-25T09:00:00Z 2026-10-25T09:30:00Z "Development and tests"
php bin/console entry:delete 1
```

Create takes project ID, start, end and description. Update takes entry ID followed by those same four values, replacing the entry. Description must be a non-empty UTF-8 string and is trimmed. Timestamps use `YYYY-MM-DDTHH:MM:SSZ` or an explicit offset such as `2026-10-25T10:00:00+01:00`; output is normalized to UTC. End must be strictly after start. Overlaps are checked globally across all projects on creation and update; the error identifies the conflicting entry ID. Touching intervals are allowed. A project with entries cannot be deleted.

Each entry returns `id`, `project_id`, `start`, `end`, `description`, `raw_duration_seconds`, `billable_duration_seconds` and `billed` (currently always `false`). Raw duration is elapsed seconds. Billable duration rounds each entry up independently to a multiple of the project's current step: with 15-minute rounding, 15 minutes stays 15 and 16 becomes 30. With no rounding it equals raw duration. Changing the project step recalculates the billable duration of existing entries when read; raw duration stays unchanged.

| Method | Route | Response |
| --- | --- | --- |
| POST | `/entries` | 201, created entry |
| GET | `/entries` | 200, entries ordered by start instant then ID |
| GET | `/entries/{id}` | 200, entry |
| PUT | `/entries/{id}` | 200, replaced entry |
| DELETE | `/entries/{id}` | 200, `{"deleted":1}` |

POST and PUT require a JSON object such as `{"project_id":1,"start":"2026-10-25T09:00:00Z","end":"2026-10-25T09:16:00Z","description":"Development"}`. Project ID is a positive JSON integer. Validation and overlap failures return 422; unknown entries or projects return 404; malformed JSON returns 400; unsupported methods return 405.

`GET /entries` accepts optional query parameters `project_id`, `from` and `to`, for example `/entries?project_id=1&from=2026-10-25T00:00:00Z&to=2026-10-26T00:00:00Z`. The CLI equivalent is `entry:list [PROJECT_ID|all [FROM [TO]]]`. Both filter on the entry's start instant: `from` is inclusive, `to` exclusive. Either API boundary may be omitted; when both are supplied, `to` must be after `from`. URL-encode a literal `+` in timezone offsets as `%2B`.

## CSV time-entry import

Import a UTF-8, semicolon-separated CSV file with the exact header `project_id;start;end;description`:

```csv
project_id;start;end;description
1;2026-10-25T09:00:00Z;2026-10-25T09:16:00Z;Development
1;2026-10-25T09:16:00Z;2026-10-25T10:00:00Z;"Review; tests"
```

```sh
php bin/console entry:import entries.csv
curl -i -X POST http://127.0.0.1:8080/entries/import \
  -H 'Content-Type: text/csv' --data-binary @entries.csv
```

The API takes raw CSV as its request body. Both interfaces return JSON such as `{"count":2,"ids":[1,2]}`; CLI success exits 0 and API success returns 201. A header-only file succeeds with count 0. CSV quoting allows semicolons and line breaks inside double-quoted fields; double a quote inside a quoted field (`""`). Both LF and CRLF line endings work.

All rows are validated before any insert, and all inserts share one transaction. The existing manual-entry rules apply: a project must exist, timestamps require a valid calendar date/time and explicit timezone, end must follow start, descriptions must be non-empty UTF-8, and intervals cannot overlap existing entries or each other, even across projects. Touching intervals are allowed. Imported entries use the project's current rounding rule just like manual entries.

An invalid file imports nothing. CLI exits 1 and lists each error on its own standard-error line; API returns 422 with the same messages in `{"errors":["Row 2: ..."]}`. Row numbers identify physical starting lines (header is line 1), including after quoted multiline descriptions. Wrong headers and comma-separated files are rejected with the expected format before validating data rows. Unknown projects inside imports are validation errors (422). An unreadable CLI file exits 1. `POST` is the only supported method for `/entries/import` (other methods return 405).
