import Link from "next/link";

export default function NotFound() {
  return (
    <main className="page-shell">
      <div className="card mt-10 flex flex-col items-center gap-4 px-6 py-12 text-center">
        <p className="eyebrow">404</p>
        <h1 className="font-mono text-xl font-bold text-white">Sayfa bulunamadı</h1>
        <Link href="/" className="ui-button ui-button-primary">
          ANA SAYFAYA DÖN
        </Link>
      </div>
    </main>
  );
}
