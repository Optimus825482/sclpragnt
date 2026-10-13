"use client";

import { usePoll } from "../lib/hooks";
import { useLiveStatus } from "../lib/liveSocket";
import type { MonitoringState } from "../lib/types";
import { fmtClockTime } from "../lib/format";

/**
 * Kompakt sistem durumu şeridi. Tasarımda yer alan "Sistem Aktif / Binance Bağlı
 * / AI Modeli Aktif…" listesi beş ayrı satır kaplayıp bilgi yoğunluğunu
 * artırıyordu; burada TEK satıra sıkıştırılmış (sadeleştirme kararı).
 */
function Item({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-gain" : "bg-warn"}`} />
      <span className={ok ? "text-ink-700" : "text-warn"}>{label}</span>
    </span>
  );
}

export default function StatusStrip() {
  const liveStatus = useLiveStatus();
  const { data } = usePoll<MonitoringState>("/api/monitoring/state", 20_000);

  const ready = Boolean(data?.data_ready);
  const loop = Boolean(data?.loop_active);

  return (
    <div className="odak-card flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2.5 text-xs">
      <Item ok={liveStatus === "open"} label={liveStatus === "open" ? "Canlı akış bağlı" : "Akış bekleniyor"} />
      <Item ok={ready} label={ready ? "Tarama hazır" : "Tarama başlıyor"} />
      <Item ok={loop} label={loop ? "Motor aktif" : "Motor beklemede"} />
      <span className="ml-auto inline-flex items-center gap-1.5 text-ink-400">
        <span>Son güncelleme</span>
        <span className="font-mono text-ink-700">{fmtClockTime(data?.last_scan_at)}</span>
      </span>
    </div>
  );
}
