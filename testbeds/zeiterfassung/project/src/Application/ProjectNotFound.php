<?php
declare(strict_types=1);

namespace TimeTracker\Application;

final class ProjectNotFound extends \RuntimeException
{
    public function __construct() { parent::__construct('Project or rate not found.'); }
}
