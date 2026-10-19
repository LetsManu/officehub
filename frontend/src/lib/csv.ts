/** Builds a CSV file in the browser (semicolon separated, UTF-8 with BOM for Excel). */

function cell(value: unknown): string {
  let text = value === null || value === undefined ? '' : String(value)
  // Neutralise spreadsheet formulas (CSV injection)
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`
  return /[";\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

export function toCsv(header: string[], rows: unknown[][]): string {
  return '﻿' + [header, ...rows].map((row) => row.map(cell).join(';')).join('\r\n')
}

export function downloadCsv(filename: string, header: string[], rows: unknown[][]): void {
  const blob = new Blob([toCsv(header, rows)], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
