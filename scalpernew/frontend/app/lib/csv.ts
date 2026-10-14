/** CSV üretimi + indirme (istemci tarafı; dışa aktarma salt-okunur veriden yapılır). */

export type CsvCell = string | number | null | undefined;

function csvEscape(value: CsvCell): string {
  if (value == null) return "";
  const text = String(value);
  if (/[",;\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

export function toCsv(headers: string[], rows: Array<Array<CsvCell>>): string {
  const lines = [headers.map(csvEscape).join(";")];
  for (const row of rows) lines.push(row.map(csvEscape).join(";"));
  return lines.join("\n");
}

export function downloadCsv(filename: string, content: string): void {
  // UTF-8 BOM: Excel'de Türkçe karakter bozulmasın.
  const blob = new Blob(["\uFEFF" + content], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}
