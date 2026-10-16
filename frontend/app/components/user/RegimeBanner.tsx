"use client";
import { useCallback, useEffect, useState } from "react";
import { getJSON } from "../../lib/api";
import { useVisibleInterval } from "../../lib/useVisibleInterval";
import { regimeNotice, type MacroRegime } from "../../lib/userUi";

/** Rejim kalkanı aktifken "neden bildirim gelmiyor" sorusunu yanıtlar. Hata/veri yoksa görünmez. */
export default function RegimeBanner() {
  const [regime, setRegime] = useState<MacroRegime | null>(null);
  const load = useCallback(async () => {
    try {
      setRegime(await getJSON<MacroRegime>("/api/signals/macro-regime"));
    } catch {
      /* uyarı yalnız kesin veriyle gösterilir; hata olursa önceki durum kalır */
    }
  }, []);
  useVisibleInterval(load, 60_000);
  useEffect(() => { void load(); }, [load]);

  const n = regimeNotice(regime);
  if (!n.active) return null;
  return (
    <div role="status" className="card u-card-warn p-3 text-sm">
      <p className="font-bold u-num-warn">{n.title}</p>
      <p className="mt-1 text-white">{n.detail}</p>
    </div>
  );
}
