<?php
declare(strict_types=1);

namespace TimeTracker\Export;

use TimeTracker\Application\Customers;
use TimeTracker\Domain\Invoice;
use TimeTracker\Domain\ValidationException;

final readonly class InvoiceExport
{
    public const CONTENT_TYPES = ['markdown' => 'text/markdown', 'html' => 'text/html'];

    /** @param array{name: string, address: string, email: string} $issuer */
    public function __construct(private Customers $customers, private array $issuer) {}

    public function render(int $id, string $format): string
    {
        if (!isset(self::CONTENT_TYPES[$format])) {
            throw new ValidationException(['Unknown export format. Use markdown or html.']);
        }
        $invoice = $this->customers->invoices()->show($id);
        $customer = $this->customers->show($invoice->customerId);
        $escape = $format === 'html' ? $this->html(...) : $this->markdown(...);
        $issuer = implode('<br>', array_map($escape, $this->issuer));
        $recipient = implode('<br>', array_map($escape, [$customer->name, $customer->address, $customer->email]));
        $rows = [];
        foreach ($invoice->positions as $position) {
            $rows[] = array_map($escape, [$position->date, $position->description, number_format($position->hours, 2, '.', ''), $this->money($position->rateCents / 100, $position->currency), $this->money($position->amount, $position->currency)]);
        }
        $currency = $invoice->positions[0]->currency;
        $totals = [];
        foreach (['Net' => $invoice->net, 'VAT (' . number_format(Invoice::VAT_RATE * 100, 0) . '%)' => $invoice->vat, 'Gross' => $invoice->gross] as $label => $amount) {
            $totals[$escape($label)] = $escape($this->money($amount, $currency));
        }
        $title = 'Invoice ' . $escape($invoice->number);
        $date = $escape($invoice->issueDate);
        $headers = ['Date', 'Description', 'Hours', 'Rate', 'Amount'];
        if ($format === 'markdown') {
            $document = "# $title\n\nDate: $date\n\n## Issuer\n\n$issuer\n\n## Customer\n\n$recipient\n\n| " . implode(' | ', $headers) . " |\n| --- | --- | --- | --- | --- |\n";
            foreach ($rows as $row) { $document .= '| ' . implode(' | ', $row) . " |\n"; }
            foreach ($totals as $label => $amount) { $document .= "\n$label: $amount\n"; }
            return $document;
        }
        $document = "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><title>$title</title></head><body>\n<h1>$title</h1>\n<p>Date: $date</p>\n<h2>Issuer</h2><p>$issuer</p>\n<h2>Customer</h2><p>$recipient</p>\n<table><thead><tr><th>" . implode('</th><th>', $headers) . "</th></tr></thead><tbody>\n";
        foreach ($rows as $row) { $document .= '<tr><td>' . implode('</td><td>', $row) . "</td></tr>\n"; }
        $document .= "</tbody></table>\n<dl>";
        foreach ($totals as $label => $amount) { $document .= "<dt>$label</dt><dd>$amount</dd>"; }
        return $document . "</dl>\n</body></html>\n";
    }

    private function money(float $amount, string $currency): string
    {
        return number_format($amount, 2, '.', '') . ' ' . $currency;
    }

    private function html(string $value): string
    {
        return str_replace(["\r\n", "\r", "\n"], '<br>', htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8'));
    }

    private function markdown(string $value): string
    {
        $value = str_replace(['\\', '*', '_', '[', ']', '`', '#', '~'], ['\\\\', '\\*', '\\_', '\\[', '\\]', '\\`', '\\#', '\\~'], $value);
        $value = str_replace('|', '&#124;', htmlspecialchars($value, ENT_NOQUOTES | ENT_SUBSTITUTE, 'UTF-8'));
        $value = (string) preg_replace(['/^([0-9]+)([.)])(?=\s|$)/', '/^([+-])(?=\s|$)/'], ['$1\\\\$2', '\\\\$1'], $value);
        return str_replace(["\r\n", "\r", "\n"], '<br>', $value);
    }
}
