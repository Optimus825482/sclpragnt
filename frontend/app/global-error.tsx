"use client";

import { useEffect } from "react";
import { isChunkLoadError, reloadForChunkError } from "./lib/chunkError";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const chunkError = isChunkLoadError(error);
  useEffect(() => { reloadForChunkError(error); }, [error]);
  return (
    <html lang="tr">
      <body style={{ background: "#0b0d10", color: "#e5e7eb", fontFamily: "monospace", display: "flex", minHeight: "100vh", alignItems: "center", justifyContent: "center" }}>
        <div style={{ textAlign: "center", display: "flex", flexDirection: "column", gap: "1rem" }}>
          <p style={{ letterSpacing: "0.2em", fontSize: "12px" }}>{chunkError ? "YENİ SÜRÜM" : "KRİTİK HATA"}</p>
          <h1 style={{ fontSize: "20px" }}>{chunkError ? "Uygulama güncellendi, yeni sürüm yükleniyor" : "Uygulama beklenmeyen bir hatayla karşılaştı"}</h1>
          {!chunkError && <p style={{ color: "#9ca3af", fontSize: "13px" }}>{error.message || "Bilinmeyen hata"}</p>}
          <div style={{ display: "flex", gap: "0.75rem", justifyContent: "center" }}>
            <button type="button" onClick={chunkError ? () => window.location.reload() : reset} style={{ padding: "0.5rem 1rem", cursor: "pointer" }}>
              {chunkError ? "SAYFAYI YENİLE" : "TEKRAR DENE"}
            </button>
            <a href="/" style={{ padding: "0.5rem 1rem" }}>
              ANA SAYFAYA DÖN
            </a>
          </div>
        </div>
      </body>
    </html>
  );
}
