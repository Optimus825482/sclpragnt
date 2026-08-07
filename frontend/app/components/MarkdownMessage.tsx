"use client";

import type { ReactNode } from "react";

function inline(text: string) {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={index} className="text-white">{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={index} className="rounded bg-black/30 px-1 text-yellow-200">{part.slice(1, -1)}</code>;
    return <span key={index}>{part}</span>;
  });
}

function repairSpacing(text: string) {
  return text
    // Keep provider output readable when it omits spaces around punctuation.
    .replace(/([!?;:])(?=[\p{L}])/gu, "$1 ")
    .replace(/\.(?=[\p{L}])/gu, ". ")
    .replace(/,(?=[\p{L}])/gu, ", ")
    // Also repair common token-boundary loss such as "MerhabaErkan".
    .replace(/([\p{Ll}\d])([\p{Lu}ÇĞİÖŞÜ])/gu, "$1 $2")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}

function isTableNoise(line: string) {
  return /^[|\s-]+$/.test(line.trim());
}

function isTableRow(line: string) {
  return line.includes("|") && tableCells(line).some(cell => /[\p{L}\p{N}%₺]/u.test(cell));
}

function isTableStart(lines: string[], index: number) {
  if (!isTableRow(lines[index]) || tableCells(lines[index]).length < 2) return false;
  for (let lookahead = index + 1; lookahead < Math.min(lines.length, index + 7); lookahead += 1) {
    if (isTableRow(lines[lookahead]) && !isTableNoise(lines[lookahead])) return true;
  }
  return false;
}

function tableCells(line: string) {
  return line.trim().replace(/^\||\|$/g, "").split("|").map(cell => cell.trim());
}

function MessageTable({ rows }: { rows: string[][] }) {
  const [head, ...body] = rows;
  return <div className="message-table-wrap" role="region" aria-label="LLM tablosu" tabIndex={0}>
    <table className="message-table">
      <thead><tr>{head.map((cell, index) => <th key={index}>{inline(cell)}</th>)}</tr></thead>
      <tbody>{body.map((row, rowIndex) => <tr key={rowIndex}>{head.map((_, cellIndex) => <td key={cellIndex}>{inline(row[cellIndex] || "—")}</td>)}</tr>)}</tbody>
    </table>
  </div>;
}

export default function MarkdownMessage({ content }: { content: string }) {
  const normalized = repairSpacing(String(content || ""))
    .replace(/\s*(#{2,4})\s*/g, "\n$1 ")
    .replace(/\s*---\s*/g, "\n---\n");
  const lines = normalized.split(/\r?\n/);
  const rendered: ReactNode[] = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (isTableStart(lines, index)) {
      const rows: string[][] = [tableCells(line)];
      index += 1;
      while (index < lines.length && lines[index].includes("|")) {
        if (isTableNoise(lines[index])) { index += 1; continue; }
        if (!isTableRow(lines[index])) break;
        rows.push(tableCells(lines[index]));
        index += 1;
      }
      rendered.push(<MessageTable key={`table-${index}`} rows={rows} />);
      index -= 1;
      continue;
    }
    const trimmed = line.trim();
    if (!trimmed) rendered.push(<div key={index} className="h-1" />);
    else if (trimmed === "---") rendered.push(<hr key={index} className="border-bunker-700" />);
    else if (trimmed.startsWith("### ")) rendered.push(<h3 key={index} className="pt-2 font-semibold text-neon-green">{inline(trimmed.slice(4))}</h3>);
    else if (trimmed.startsWith("## ")) rendered.push(<h2 key={index} className="pt-2 text-base font-bold text-white">{inline(trimmed.slice(3))}</h2>);
    else if (/^[-*] /.test(trimmed)) rendered.push(<div key={index} className="pl-4 before:mr-2 before:text-neon-green before:content-['•']">{inline(trimmed.slice(2))}</div>);
    else rendered.push(<p key={index}>{inline(line)}</p>);
  }
  return <div className="space-y-2 leading-6">{rendered}</div>;
}
