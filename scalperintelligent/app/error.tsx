"use client";

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="odak-card mx-auto mt-10 max-w-lg p-6 text-center">
      <p className="odak-kicker">Hata</p>
      <h1 className="mt-2 text-lg font-semibold text-ink-900">Bir şeyler ters gitti</h1>
      <p className="mt-2 text-sm text-ink-500">{error.message || "Beklenmeyen bir hata oluştu."}</p>
      <button onClick={reset} className="mt-4 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover">
        Yeniden dene
      </button>
    </div>
  );
}
