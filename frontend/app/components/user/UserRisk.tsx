"use client";
import { useCallback, useEffect, useState } from "react";
import { call, type RiskSettings } from "../../lib/tradeApi";
import { RR_PRESETS, capAmount, fmtTry, parseTrNumber, rrLabel } from "../../lib/tradeUi";

const CARD = "card p-4";

type Account = { balances?: { asset: string; free: string }[] };

export default function UserRisk() {
  const [saved, setSaved] = useState<RiskSettings | null>(null);
  const [pct, setPct] = useState(20);
  const [rr, setRr] = useState(2);
  const [rrText, setRrText] = useState("2");
  const [freeTry, setFreeTry] = useState<number | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "good" | "bad"; text: string } | null>(null);

  const load = useCallback(async () => {
    setStatus("loading");
    const r = await call<RiskSettings>("GET", "/api/binance/risk");
    if (!r.ok) {
      setMessage({ tone: "bad", text: r.error });
      setStatus("error");
      return;
    }
    setSaved({ max_position_pct: r.body.max_position_pct, default_rr: r.body.default_rr });
    setPct(r.body.max_position_pct);
    setRr(r.body.default_rr);
    setRrText(String(r.body.default_rr).replace(".", ","));
    setStatus("ready");
    const acct = await call<Account>("GET", "/api/binance/account");
    if (acct.ok) {
      const row = (acct.body.balances || []).find((b) => String(b.asset).toUpperCase() === "TRY");
      setFreeTry(row ? Number(row.free) : 0);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const dirty = !!saved && (saved.max_position_pct !== pct || saved.default_rr !== rr);
  const pctValid = Number.isFinite(pct) && pct >= 1 && pct <= 100;
  const rrValid = Number.isFinite(rr) && rr >= 1 && rr <= 5;

  const save = async () => {
    if (!pctValid || !rrValid || busy) return;
    setBusy(true);
    setMessage(null);
    const r = await call<RiskSettings>("PUT", "/api/binance/risk", { max_position_pct: pct, default_rr: rr });
    setBusy(false);
    if (!r.ok) {
      setMessage({ tone: "bad", text: r.error });
      return;
    }
    setSaved({ max_position_pct: r.body.max_position_pct, default_rr: r.body.default_rr });
    setMessage({ tone: "good", text: "Kaydedildi. Yeni alımlar bu ayarlara göre planlanır." });
  };

  const onRrText = (text: string) => {
    setRrText(text);
    const n = parseTrNumber(text);
    if (n != null) setRr(n);
  };

  return (
    <main className="space-y-4">
      <header>
        <h1 className="text-2xl font-bold text-white">Risk Merkezi</h1>
        <p className="mt-1 text-sm text-bunker-muted">Her alımda ne kadar risk alacağını burada sen belirlersin. Sistem bu sınırı aşan emri göndermez.</p>
      </header>

      {status === "loading" && <p className="text-sm text-bunker-muted" aria-live="polite">Yükleniyor…</p>}
      {status === "error" && (
        <div className={CARD}>
          <p role="alert" className="text-sm text-neon-red">{message?.text || "Ayarlar alınamadı"}</p>
          <button type="button" onClick={load} className="ui-button-secondary mt-3 min-h-[44px] rounded-lg border px-4 text-sm font-medium">Tekrar dene</button>
        </div>
      )}

      {status === "ready" && (
        <>
          <section className={CARD} aria-labelledby="limit-baslik">
            <h2 id="limit-baslik" className="text-base font-semibold text-white">Bir pozisyonda en fazla</h2>
            <p className="mt-1 text-sm text-bunker-muted">Serbest TL bakiyenin en çok yüzde kaçını tek bir alımda kullanabilirsin.</p>
            <div className="mt-3 flex items-center gap-3">
              <input
                type="range" min={1} max={100} step={1} value={Number.isFinite(pct) ? pct : 1}
                onChange={(e) => setPct(Number(e.target.value))}
                aria-label="Pozisyon başına en fazla yüzde"
                className="h-11 flex-1 accent-[color:var(--u-brand)]"
              />
              <label className="flex items-center gap-1 text-white">
                <span className="sr-only">Yüzde</span>
                <input
                  type="number" inputMode="decimal" min={1} max={100} value={Number.isFinite(pct) ? pct : ""}
                  onChange={(e) => setPct(e.target.value === "" ? Number.NaN : Number(e.target.value))}
                  className="input min-h-[44px] w-20 rounded-lg border px-2 text-right text-base"
                />
                <span aria-hidden>%</span>
              </label>
            </div>
            {!pctValid && <p role="alert" className="mt-2 text-sm text-neon-red">1 ile 100 arasında bir değer gir.</p>}
            {pctValid && (
              <p className="mt-2 text-sm text-white">
                {freeTry != null
                  ? <>Serbest bakiyen {fmtTry(freeTry)} ise bir alımda en fazla <strong>{fmtTry(capAmount(freeTry, pct))}</strong> kullanılır.</>
                  : <>Serbest bakiyenin %{pct}’i bir alımda kullanılabilir.</>}
              </p>
            )}
          </section>

          <section className={CARD} aria-labelledby="rr-baslik">
            <h2 id="rr-baslik" className="text-base font-semibold text-white">Standart kazanç / risk oranı</h2>
            <p className="mt-1 text-sm text-bunker-muted">
              1 : 2 demek, riske attığın her 1 TL için 2 TL kazanç hedeflenir. Alım ekranında sistem coine özel bir oran önerir; sen yine buradakini veya kendi değerini seçebilirsin.
            </p>
            <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Hazır oranlar">
              {RR_PRESETS.map((p) => (
                <button
                  key={p} type="button" aria-pressed={rr === p}
                  onClick={() => { setRr(p); setRrText(String(p).replace(".", ",")); }}
                  className={`min-h-[44px] rounded-lg border px-4 text-sm font-semibold ${rr === p ? "ui-button-primary" : "ui-button-secondary"}`}
                >
                  {rrLabel(p)}
                </button>
              ))}
            </div>
            <label className="mt-3 block text-sm text-white">
              Kendi oranım (1 ile 5 arası)
              <input
                type="text" inputMode="decimal" value={rrText} onChange={(e) => onRrText(e.target.value)}
                className="input mt-1 block min-h-[44px] w-32 rounded-lg border px-3 text-base"
              />
            </label>
            {!rrValid && <p role="alert" className="mt-2 text-sm text-neon-red">Oran 1 ile 5 arasında olmalı.</p>}
          </section>

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button" onClick={save} disabled={!dirty || !pctValid || !rrValid || busy}
              className="ui-button-primary min-h-[48px] rounded-lg px-6 text-sm disabled:opacity-50"
            >
              {busy ? "Kaydediliyor…" : "Kaydet"}
            </button>
            {message && (
              <p role={message.tone === "bad" ? "alert" : "status"} className={`text-sm ${message.tone === "bad" ? "text-neon-red" : "text-neon-green"}`}>
                {message.text}
              </p>
            )}
          </div>
          <p className="text-xs text-bunker-muted">Bu ayarlar öneridir ve kâr garantisi vermez. Kaybetme riski her zaman vardır.</p>
        </>
      )}
    </main>
  );
}
