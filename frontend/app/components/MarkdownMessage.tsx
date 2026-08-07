"use client";

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
    .replace(/([.!?;:])(?=[\p{L}\d])/gu, "$1 ")
    .replace(/([,])(?=[\p{L}\d])/gu, "$1 ")
    // Also repair common token-boundary loss such as "MerhabaErkan".
    .replace(/([\p{Ll}\d])([\p{Lu}ÇĞİÖŞÜ])/gu, "$1 $2")
    .replace(/\s{2,}/g, " ")
    .trim();
}

export default function MarkdownMessage({ content }: { content: string }) {
  const normalized = repairSpacing(String(content || ""))
    .replace(/\s*(#{2,4})\s*/g, "\n$1 ")
    .replace(/\s*---\s*/g, "\n---\n")
    .replace(/\|/g, " | ");
  return <div className="space-y-2 leading-6">{normalized.split(/\r?\n/).map((line, index) => {
    const trimmed = line.trim();
    if (!trimmed) return <div key={index} className="h-1" />;
    if (trimmed === "---") return <hr key={index} className="border-bunker-700" />;
    if (trimmed.startsWith("### ")) return <h3 key={index} className="pt-2 font-semibold text-neon-green">{inline(trimmed.slice(4))}</h3>;
    if (trimmed.startsWith("## ")) return <h2 key={index} className="pt-2 text-base font-bold text-white">{inline(trimmed.slice(3))}</h2>;
    if (/^[-*] /.test(trimmed)) return <div key={index} className="pl-4 before:mr-2 before:text-neon-green before:content-['•']">{inline(trimmed.slice(2))}</div>;
    return <p key={index}>{inline(line)}</p>;
  })}</div>;
}
