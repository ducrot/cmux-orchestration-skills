<?php
declare(strict_types=1);
namespace TimeTracker\Application;
final class EntryNotFound extends \RuntimeException
{
    public function __construct() { parent::__construct('Time entry not found.'); }
}
