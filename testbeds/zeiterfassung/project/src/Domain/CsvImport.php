<?php
declare(strict_types=1);
namespace TimeTracker\Domain;

final class CsvImport
{
    /**
     * @param list<int> $projectIds
     * @param list<TimeEntry> $existing
     * @return list<array{project_id: int, start: int, end: int, description: string}>
     */
    public static function validate(string $csv, array $projectIds, array $existing): array
    {
        if (str_starts_with($csv, "\xEF\xBB\xBF")) { $csv = substr($csv, 3); }
        $stream = fopen('php://temp', 'w+');
        if ($stream === false) { throw new \RuntimeException('Cannot open CSV buffer.'); }
        try {
            fwrite($stream, $csv);
            rewind($stream);
            if (fgetcsv($stream, null, ';', '"', '') !== ['project_id', 'start', 'end', 'description']) {
                throw new ValidationException(['Expected semicolon-separated CSV with header project_id;start;end;description.']);
            }
            $errors = $rows = $intervals = [];
            $line = 1;
            $previous = 0;
            while (($position = ftell($stream)) !== false && ($fields = fgetcsv($stream, null, ';', '"', '')) !== false) {
                $line += substr_count($csv, "\n", $previous, $position - $previous);
                $previous = $position;
                if (count($fields) !== 4 || in_array(null, $fields, true)) {
                    $errors[] = "Row $line: Expected four semicolon-separated fields.";
                    continue;
                }
                [$project, $startValue, $endValue, $description] = $fields;
                $id = preg_match('/^[1-9][0-9]*$/D', $project) === 1 ? filter_var($project, FILTER_VALIDATE_INT) : false;
                if ($id === false || !in_array($id, $projectIds, true)) { $errors[] = "Row $line: Unknown project (project_id must identify an existing project)."; }
                $start = self::timestamp($startValue);
                $end = self::timestamp($endValue);
                if ($start === null) { $errors[] = "Row $line: Start must be a valid YYYY-MM-DDTHH:MM:SS timestamp with Z or timezone offset."; }
                if ($end === null) { $errors[] = "Row $line: End must be a valid YYYY-MM-DDTHH:MM:SS timestamp with Z or timezone offset."; }
                if (trim($description) === '' || preg_match('//u', $description) !== 1) { $errors[] = "Row $line: Description must be a non-empty UTF-8 string."; }
                if ($start === null || $end === null) { continue; }
                if ($end <= $start) { $errors[] = "Row $line: End must be after start."; continue; }
                foreach ($existing as $entry) {
                    if ($start < $entry->end && $end > $entry->start) { $errors[] = "Row $line: Overlaps time entry {$entry->id}." . ($entry->billed ? " Locked by invoice {$entry->invoiceNumber}." : ""); }
                }
                foreach ($intervals as $other) {
                    if ($start < $other['end'] && $end > $other['start']) {
                        $errors[] = "Row {$other['line']}: Overlaps CSV row $line.";
                        $errors[] = "Row $line: Overlaps CSV row {$other['line']}.";
                    }
                }
                $intervals[] = ['line' => $line, 'start' => $start, 'end' => $end];
                if ($id !== false) { $rows[] = ['project_id' => $id, 'start' => $start, 'end' => $end, 'description' => trim($description)]; }
            }
            if ($errors !== []) { throw new ValidationException($errors); }
            return $rows;
        } finally { fclose($stream); }
    }

    private static function timestamp(string $value): ?int
    {
        if (preg_match('/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-](?:(?:0[0-9]|1[0-3]):[0-5][0-9]|14:00))$/D', $value) !== 1) { return null; }
        $date = \DateTimeImmutable::createFromFormat('!Y-m-d\\TH:i:sP', $value);
        $errors = \DateTimeImmutable::getLastErrors();
        return $date === false || ($errors !== false && ($errors['warning_count'] > 0 || $errors['error_count'] > 0)) ? null : $date->getTimestamp();
    }
}
