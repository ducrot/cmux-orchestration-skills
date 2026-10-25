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

## Development

The `TimeTracker\` PSR-4 root maps to `src/`: `Domain` holds models and validation rules, `Application` coordinates customer operations, `Infrastructure` holds configuration, PDO storage and migrations, and `Console` and `Api` adapt the service for each interface.

`Console\Application::run()` accepts argument values and output callbacks and returns an exit code. `Api\Handler::handle()` accepts a `Request` value and returns a `Response` with status, body and JSON serialization. Both can share an application service without starting processes.

Run the unit and integration suites and PHPStan level 6:

```sh
vendor/bin/phpunit
vendor/bin/phpstan analyse --no-progress
```

Integration tests use in-memory SQLite for customer operations and migrations; a temporary file database additionally verifies configuration and persistence across connections. Commit `composer.lock` when updating dependencies to pin installations.
