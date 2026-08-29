"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

/** /portfolio tek sayfada ana sayfaya birleşti; eski bağlantılar buradan yönlendirilir. */
export default function PortfolioRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/");
  }, [router]);
  return (
    <main className="mx-auto max-w-7xl p-6">
      <div className="card text-bunker-muted">Portföy sayfası ana sayfayla birleştirildi; yönlendiriliyorsunuz…</div>
    </main>
  );
}
