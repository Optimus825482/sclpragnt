import Link from "next/link";

export default function NotFound() {
  return (
    <div className="odak-card mx-auto mt-10 max-w-lg p-6 text-center">
      <p className="odak-kicker">404</p>
      <h1 className="mt-2 text-lg font-semibold text-ink-900">Sayfa bulunamadı</h1>
      <Link href="/" className="mt-4 inline-block rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover">
        Pano'ya dön
      </Link>
    </div>
  );
}
