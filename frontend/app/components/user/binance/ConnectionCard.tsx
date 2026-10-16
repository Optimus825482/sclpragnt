"use client";
import Link from "next/link";
import { useState } from "react";
import { call } from "../../../lib/tradeApi";
import { errorText } from "../../../lib/tradeUi";
import ConfirmDialog from "./ConfirmDialog";

type Props = {
  configured: boolean;
  sellEnabled: boolean;
  sellSource: string;
  onChanged: () => void;
};

export default function ConnectionCard({ configured, sellEnabled, sellSource, onChanged }: Props) {
  const [liveDialog, setLiveDialog] = useState(false);
  const [deleteDialog, setDeleteDialog] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const serverLocked = !sellEnabled && sellSource !== "panel";

  const setLive = async (value: boolean) => {
    setBusy(true);
    setError("");
    const r = await call("POST", "/api/binance/settings", { real_sell_enabled: value });
    setBusy(false);
    setLiveDialog(false);
    if (!r.ok) setError(errorText(r.error));
    onChanged();
  };

  const removeKeys = async () => {
    setBusy(true);
    setError("");
    const r = await call("DELETE", "/api/binance/keys");
    setBusy(false);
    setDeleteDialog(false);
    if (!r.ok) setError(errorText(r.error));
    onChanged();
  };

  return (
    <section className="card space-y-3 p-4" aria-labelledby="baglanti-baslik">
      <h2 id="baglanti-baslik" className="text-lg font-bold text-white">Bağlantı</h2>
      <p className="text-sm text-white" aria-live="polite">
        Binance TR anahtarı: <strong>{configured ? "kayıtlı" : "kayıtlı değil"}</strong>
        {" · "}Canlı işlem: <strong className={sellEnabled ? "text-neon-green" : "text-bunker-muted"}>{sellEnabled ? "açık" : "kapalı"}</strong>
      </p>
      {serverLocked && <p className="text-sm text-bunker-muted">Gerçek işlemler sunucu yöneticisi tarafından kapatılmış.</p>}
      {error && <p role="alert" className="text-sm text-neon-red">{error}</p>}

      <div className="flex flex-wrap gap-2">
        {!configured && (
          <Link href="/settings" className="ui-button-primary inline-flex min-h-[48px] items-center rounded-lg px-4 text-sm">
            Ayarlar’dan anahtar ekle
          </Link>
        )}
        {configured && !sellEnabled && !serverLocked && (
          <button type="button" onClick={() => setLiveDialog(true)} className="ui-button-primary min-h-[48px] rounded-lg px-4 text-sm">
            Canlı işlemi aç
          </button>
        )}
        {configured && sellEnabled && (
          <button type="button" onClick={() => setLive(false)} disabled={busy} className="ui-button-secondary min-h-[48px] rounded-lg border px-4 text-sm font-medium disabled:opacity-50">
            Canlı işlemi kapat
          </button>
        )}
        {configured && (
          <>
            <Link href="/settings" className="ui-button-secondary inline-flex min-h-[48px] items-center rounded-lg border px-4 text-sm font-medium">Anahtarı değiştir</Link>
            <button type="button" onClick={() => setDeleteDialog(true)} className="ui-button-secondary min-h-[48px] rounded-lg border px-4 text-sm font-medium text-neon-red">
              Anahtarı sil
            </button>
          </>
        )}
      </div>
      <p className="text-xs text-bunker-muted">Anahtara yalnız okuma ve spot işlem yetkisi ver; para çekme yetkisi verme.</p>

      <ConfirmDialog open={liveDialog} title="Canlı işlemi aç" confirmLabel="Canlı işlemi aç" busy={busy} onConfirm={() => setLive(true)} onClose={() => setLiveDialog(false)}>
        <p>Açtığında bu sayfadaki alım ve satım düğmeleri <strong>gerçek paranla</strong> emir gönderir.</p>
        <p className="text-bunker-muted">İstediğin zaman “Canlı işlemi kapat” ile kapatabilirsin.</p>
      </ConfirmDialog>
      <ConfirmDialog open={deleteDialog} title="Anahtarı sil" confirmLabel="Evet, sil" danger busy={busy} onConfirm={removeKeys} onClose={() => setDeleteDialog(false)}>
        <p>Kayıtlı Binance TR anahtarın silinir ve canlı işlem kapanır. Borsadaki emirlerin etkilenmez.</p>
      </ConfirmDialog>
    </section>
  );
}
