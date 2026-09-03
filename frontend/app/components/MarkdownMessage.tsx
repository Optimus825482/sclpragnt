"use client";

import React, { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

function cleanProviderMarkdown(value: string) {
  const lines = String(value || "").replace(/\r\n?/g, "\n").split("\n");
  return lines
    .filter((line, index) => {
      const trimmed = line.trim();
      // Some providers emit decorative table separators as separate lines.
      // They are not valid GFM rows and prevent the parser from recognizing the table.
      if (!/^[|\s-]+$/.test(trimmed) || !trimmed.includes("|")) return true;
      const cells = trimmed.replace(/^\||\|$/g, "").split("|").map(cell => cell.trim());
      // Keep valid GFM separators such as | --- | --- |.
      if (cells.some(cell => /^:?-{3,}:?$/.test(cell))) return true;
      const previous = lines[index - 1]?.includes("|");
      const next = lines[index + 1]?.includes("|");
      return !(previous && next);
    })
    .join("\n")
    // ReDoS önlemi: Unicode property escape (\p{L}) yerine basit [a-zA-Z] kullan
    // (Türkçe karakterler için karakter sınıfı genişletildi)
    .replace(/([!?;:])(?=[a-zA-ZçğıöüşÇĞİÖÜŞ])/g, "$1 ")
    .replace(/\. (?=[a-zA-ZçğıöüşÇĞİÖÜŞ])/g, ". ");
}

function MarkdownMessage({ content }: { content: string }) {
  return <div className="message-markdown">
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        h2: ({ children }) => <h2 className="pt-2 text-base font-bold text-white">{children}</h2>,
        h3: ({ children }) => <h3 className="pt-2 font-semibold text-neon-green">{children}</h3>,
        table: ({ children }) => <div className="message-table-wrap" role="region" aria-label="LLM tablosu" tabIndex={0}><table className="message-table">{children}</table></div>,
        th: ({ children }) => <th>{children}</th>,
        td: ({ children }) => <td>{children}</td>,
        code: ({ children }) => <code className="rounded bg-black/30 px-1 text-yellow-200">{children}</code>,
      }}
    >{cleanProviderMarkdown(content)}</ReactMarkdown>
  </div>;
}

// Chat input changes re-render the parent; avoid reparsing every previous
// assistant message on each keystroke.
export default memo(MarkdownMessage);
