<?php
declare(strict_types=1);

namespace TimeTracker\Tests\Integration;

use PDO;
use PHPUnit\Framework\TestCase;
use TimeTracker\Application\Customers;
use TimeTracker\Infrastructure\Bootstrap;
use TimeTracker\Infrastructure\Configuration;
use TimeTracker\Infrastructure\Migrations\Migrator;
use TimeTracker\Infrastructure\Storage\CustomerRepository;

final class InfrastructureTest extends TestCase
{
    public function testMigrationRunsTwiceWithoutLosingCustomers(): void
    {
        $pdo = new PDO('sqlite::memory:', null, null, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
        $migrator = new Migrator();
        $migrator->migrate($pdo);
        $pdo->exec("INSERT INTO customers (name, address, email) VALUES ('Ada', 'Street', 'ada@example.com')");
        $migrator->migrate($pdo);
        self::assertSame([1, 2], $pdo->query('SELECT version FROM schema_migrations')->fetchAll(PDO::FETCH_COLUMN));
        self::assertSame('Ada', $pdo->query('SELECT name FROM customers')->fetchColumn());
    }

    public function testProjectMigrationUpgradesExistingCustomerDatabase(): void
    {
        $pdo = new PDO('sqlite::memory:', null, null, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
        $pdo->exec('PRAGMA foreign_keys = ON');
        $pdo->exec('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY); INSERT INTO schema_migrations VALUES (1);
            CREATE TABLE customers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, address TEXT NOT NULL, email TEXT NOT NULL)');
        $pdo->exec("INSERT INTO customers VALUES (1, 'Ada', 'Street', 'ada@example.com')");
        (new Migrator())->migrate($pdo);
        $customers = new Customers(new CustomerRepository($pdo));
        $project = $customers->projects()->create(1, ['name' => 'Existing customer']);
        $customers->projects()->addRate(1, $project->id, ['amount' => '12.30', 'currency' => 'EUR', 'start' => '2026-01-01']);
        (new Migrator())->migrate($pdo);
        self::assertSame('Ada', $customers->show(1)->name);
        self::assertSame('12.30', $customers->projects()->rates(1, $project->id)[0]->toArray()['amount']);
    }

    public function testConfigurationLoadsDatabaseAndIssuerAndBootstrapPersists(): void
    {
        $directory = sys_get_temp_dir() . '/time-tracker-' . bin2hex(random_bytes(8));
        mkdir($directory);
        $configFile = $directory . '/project.php';
        $database = $directory . '/nested/storage.sqlite';
        file_put_contents($configFile, '<?php return ' . var_export(['database_path' => $database, 'issuer' => ['name' => 'Issuer', 'address' => 'Road', 'email' => 'issuer@example.com']], true) . ';');
        try {
            $config = Configuration::fromFile($configFile);
            self::assertSame($database, $config->databasePath);
            self::assertSame(['name' => 'Issuer', 'address' => 'Road', 'email' => 'issuer@example.com'], $config->issuer);
            $first = Bootstrap::customers($config);
            $first->create(['name' => 'Ada', 'address' => 'Street', 'email' => 'ada@example.com']);
            self::assertFileExists($database);
            self::assertSame('Ada', Bootstrap::customers($config)->show(1)->name);
        } finally {
            unlink($configFile);
            if (file_exists($database)) { unlink($database); }
            if (is_dir(dirname($database))) { rmdir(dirname($database)); }
            rmdir($directory);
        }
    }

    public function testDefaultConfigurationIsUsable(): void
    {
        $config = Configuration::fromFile(__DIR__ . '/../../config/project.php');
        self::assertStringEndsWith('/var/time-tracker.sqlite', $config->databasePath);
        self::assertSame('Solo Developer', $config->issuer['name']);
    }
}
