"use client";

/**
 * Üst menünün hemen altındaki ince portföy bandı (YALNIZ masaüstü).
 *
 * Binance TR key+secret kayıtlıysa GERÇEK Binance değerleri ("Binance TR"),
 * değilse PAPER değerleri ("Paper") gösterir; kaynak sol etiketten okunur.
 * Veri/yenileme mantığı `lib/usePortfolioSummary.ts`'dedir. Mobilde hiç
 * render edilmez (ve veri çekilmez): `matchMedia` + CSS çift güvence.
 */
import { useEffect, useState } from "react";
import { formatFixed, formatSignedTL, formatTL } from "../lib/format";
import { usePortfolioSummary, type PortfolioBandData } from "../lib/usePortfolioSummary";

// globals.css'teki mobil kırılımı (max-width: 768px) ile aynı eşik.
const DESKTOP_QUERY = "(min-width: 769px)";

const toneClass = (v: number | null | undefined) =>
  v == null || !Number.isFinite(v) ? "ui-tone-muted" : v > 0 ? "ui-tone-positive" : v < 0 ? "ui-tone-negative" : "";

/** İşaretli yüzde: `+1,25%`, `-0,40%`, veri yok "—". */
export function formatSignedPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const text = `${formatFixed(Math.abs(v), 2)}%`;
  return v > 0 ? `+${text}` : v < 0 ? `-${text}` : text;
}

function Tile({ label, children, title }: { label: string; children: React.ReactNode; title?: string }) {
  return (
    <div className="pband-tile" title={title}>
      <span className="pband-label">{label}</span>
      <span className="pband-value">{children}</span>
    </div>
  );
}

function SkeletonTiles() {
  return (
    <>
      {["TOPLAM DEĞER", "SERBEST TL", "AÇIK İŞLEM", "ANLIK K/Z", "GÜNLÜK K/Z"].map((l) => (
        <div className="pband-tile" key={l} aria-hidden="true">
          <span className="pband-label">{l}</span>
          <span className="pband-skeleton" />
        </div>
      ))}
    </>
  );
}

function Tiles({ d }: { d: PortfolioBandData }) {
  return (
    <>
      <Tile label="TOPLAM DEĞER">{formatTL(d.totalTry)}</Tile>
      <Tile label="SERBEST TL">{formatTL(d.freeTry)}</Tile>
      <Tile label="AÇIK İŞLEM">{d.openCount == null ? "—" : String(d.openCount)}</Tile>
      <Tile label="ANLIK K/Z" title="Açık pozisyonların anlık kâr/zararı (komisyon dahil)">
        <span className={toneClass(d.unrealizedTry)}>{formatSignedTL(d.unrealizedTry)}</span>
        <span className={`pband-sub ${toneClass(d.unrealizedPct)}`}>{formatSignedPct(d.unrealizedPct)}</span>
      </Tile>
      <Tile label="GÜNLÜK K/Z" title="Bugün gerçekleşen (kapanan) işlemlerin toplam kâr/zararı">
        <span className={toneClass(d.dailyPnlTry)}>{formatSignedTL(d.dailyPnlTry)}</span>
      </Tile>
    </>
  );
}

function BandInner() {
  const { data, status, stale } = usePortfolioSummary();
  const sourceLabel = data ? (data.source === "binance" ? "Binance TR" : "Paper") : null;
  return (
    <div
      className={`portfolio-band${stale ? " is-stale" : ""}`}
      role="status"
      aria-live="polite"
      aria-label="Portföy durumu"
      data-source={data?.source ?? "loading"}
      title={stale ? "Son yenileme başarısız oldu; değerler bayat olabilir" : undefined}
    >
      {sourceLabel ? (
        <span className="pband-source" data-source={data!.source}>
          {sourceLabel}
          {/* 2026-10-17: Binance'te canlı fiyat tiki son 10 sn içinde uygulandıysa yeşil nokta. */}
          {data!.liveAt && Date.now() - data!.liveAt < 10_000 ? (
            <span className="pband-live" title="Canlı fiyatla güncelleniyor (2 sn)" aria-label="canlı" />
          ) : null}
        </span>
      ) : (
        <span className="pband-source" aria-hidden="true">…</span>
      )}
      {status === "error" ? (
        <span className="pband-error">Portföy verisi alınamadı</span>
      ) : data ? (
        <Tiles d={data} />
      ) : (
        <SkeletonTiles />
      )}
    </div>
  );
}

export default function PortfolioBand() {
  const [desktop, setDesktop] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia(DESKTOP_QUERY);
    const sync = () => setDesktop(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);
  // İç bileşen yalnız masaüstünde bağlanır: mobilde REST/WS aboneliği de yok.
  return desktop ? <BandInner /> : null;
}
