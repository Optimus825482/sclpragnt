import MemoryTab from "./MemoryTab";

export default function MemoryPage() {
  return (
    <main className="page-shell space-y-5">
      <div className="page-heading">
        <p className="eyebrow text-neon-green">LLM HAFIZASI</p>
        <h1 className="font-mono text-2xl font-bold text-white">Embedding ve Retrieval</h1>
        <p className="mt-1 text-sm text-bunker-muted">Geçmiş işlem ve karar bağlamını yalnızca PostgreSQL memory backend aktifken arar.</p>
      </div>
      <MemoryTab />
    </main>
  );
}
