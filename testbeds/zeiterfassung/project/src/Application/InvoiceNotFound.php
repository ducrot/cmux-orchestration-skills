<?php
declare(strict_types=1);
namespace TimeTracker\Application;
final class InvoiceNotFound extends \RuntimeException
{
    public function __construct() { parent::__construct('Invoice not found.'); }
}
