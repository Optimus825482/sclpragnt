"use client";

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="page-shell">
      <div className="card mt-10 flex flex-col items-center gap-4 border-neon-red/30 bg-neon-red/5 px-6 py-12 text-center">
        <p className="eyebrow">BEKLENMEYEN HATA</p>
        <h1 className="font-mono text-xl font-bold text-white">Bu bölüm yüklenirken bir hata oluştu</h1>
        <p className="max-w-md text-sm text-bunker-muted">
          {error.message || "Bilinmeyen hata"}
        </p>
        <div className="flex gap-3">
          <button type="button" className="ui-button ui-button-primary" onClick={reset}>
            TEKRAR DENE
          </button>
          <a href="/" className="ui-button">ANA SAYFAYA DÖN</a>
        </div>
      </div>
    </main>
  );
}
