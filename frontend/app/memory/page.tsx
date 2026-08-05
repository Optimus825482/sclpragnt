import MemoryTab from "./MemoryTab";

export default function MemoryPage() {
  return <main className="page-shell"><div className="page-heading"><p className="eyebrow">LLM HAFIZASI</p><h1>Embedding ve Retrieval</h1><p className="text-bunker-muted">Geçmiş işlem ve karar bağlamını yalnızca PostgreSQL memory backend aktifken arar.</p></div><MemoryTab /></main>;
}
