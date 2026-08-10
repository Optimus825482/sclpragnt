"use client";
import { useEffect, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import SymbolLink from "../components/SymbolLink";

export default function TradeRepairPage() {
  const [data, setData] = useState<any>(null); const [legacy, setLegacy] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const load = () => apiRequest(`${API_BASE}/api/trade-repair/status`, { cache: "no-store" }).then(r => r.json()).then(setData).catch(() => undefined);
  useEffect(() => { load(); apiRequest(`${API_BASE}/api/trade-repair/legacy-cleanup`, { cache: "no-store" }).then(r => r.json()).then(x => setLegacy(x.records || [])).catch(() => undefined); const id = setInterval(load, 1500); return () => clearInterval(id); }, []);
  const preview = async () => { setBusy(true); try { await apiRequest(`${API_BASE}/api/trade-repair/preview`, { method: "POST" }); await load(); } finally { setBusy(false); } };
  const apply = async () => {
    const count = data?.preview?.actions?.assign_trade_ids ?? 0;
    if (!window.confirm(`Onaylı geçmiş veri onarımı başlatılacak. ${count} bağlantı kimliği düzeltilecek. Hiçbir kayıt silinmeyecek. Devam edilsin mi?`)) return;
    setBusy(true); try { await apiRequest(`${API_BASE}/api/trade-repair/apply`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm: true }) }); await load(); } finally { setBusy(false); }
  };
  const purgeLegacy = async () => {
    if (!legacy.length || !window.confirm(`Şu kayıtlar kalıcı olarak silinecek: ${legacy.map(x => `${x.trade_id} (${x.symbol})`).join(", ")}. İlgili kapanış sinyal/karar ve embedding kayıtları da temizlenecek. Devam edilsin mi?`)) return;
    setBusy(true); try { await apiRequest(`${API_BASE}/api/trade-repair/legacy-cleanup`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm: true, trade_ids: legacy.map(x => x.trade_id) }) }); setLegacy([]); await load(); } finally { setBusy(false); }
  };
  const p = data?.preview;
  return <main className="page-shell space-y-5">
    <header><p className="eyebrow">GEÇMİŞ VERİ ONARIMI</p><h1>Trade Repair Monitor</h1><p className="text-bunker-muted">Açılış, kapanış ve karar kayıtlarını silmeden denetleyin ve onayla düzeltin.</p></header>
    <div className="card border-yellow-400/20 bg-yellow-400/5 text-sm"><p className="text-yellow-300 font-mono">GÜVENLİK SINIRI</p><p className="mt-2">Önizleme salt-okunurdur. Uygulama yalnızca eksik trade_id alanlarını doldurur ve kesin eşleşen kapanış kararlarına strateji ekler. Kayıt silmez, PnL veya cüzdan değerini değiştirmez.</p></div>
    <div className="flex flex-wrap gap-3"><button onClick={preview} disabled={busy} className="ui-button ui-button-secondary">ÖNİZLEMEYİ ÇALIŞTIR</button><button onClick={apply} disabled={busy || !p?.requires_confirmation} className="ui-button ui-button-primary">ONAYLA VE ONAR</button></div>
    {legacy.length > 0 && <div className="card border-neon-red/30 bg-neon-red/5"><p className="eyebrow text-neon-red">MİGRASYON KAYNAKLI LEGACY KAYITLAR</p><div className="mt-3 space-y-1 font-mono text-sm">{legacy.map(x => <div key={x.trade_id}>{x.trade_id} · <SymbolLink symbol={x.symbol} className="text-white hover:text-neon-green" /> · PnL ₺{Number(x.pnl || 0).toFixed(2)}</div>)}</div><button onClick={purgeLegacy} disabled={busy} className="ui-button mt-4 border-neon-red/50 text-neon-red">ONAYLA VE LEGACY KAYITLARINI SİL</button></div>}
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">{[["Durum",data?.status||"idle"],["Aşama",data?.phase||"—"],["İlerleme",`${data?.progress??0}%`],["Kimlik adayı",String(p?.actions?.assign_trade_ids??0)]].map(([k,v])=><div className="card" key={k}><p className="eyebrow">{k}</p><p className="font-mono text-xl mt-2 text-white">{v}</p></div>)}</div>
    {p && <div className="card space-y-3"><p className="eyebrow">ÖNİZLEME SONUCU</p><div className="grid sm:grid-cols-3 gap-3 font-mono text-sm"><span>Eksik trade_id: {p.missing_trade_ids?.length ?? 0}</span><span>Eksik pozisyon id: {p.missing_position_ids?.length ?? 0}</span><span>Eşleşmeyen kapanış: {p.unmatched_close_logs?.length ?? 0}</span></div>{p.unmatched_close_logs?.length > 0 && <p className="text-yellow-300 text-sm">Eşleşmeyen kapanışlar yalnızca raporlandı; otomatik silinmeyecek.</p>}</div>}
    <div className="card"><p className="eyebrow mb-3">CANLI ONARIM LOGU</p><div className="max-h-80 overflow-auto space-y-2 font-mono text-xs">{(data?.logs||[]).map((l:any,i:number)=><div key={i} className="border-b border-bunker-800 pb-2"><span className="text-bunker-muted">{new Date(l.time*1000).toLocaleTimeString("tr-TR")}</span> <span className={l.level==="error"?"text-neon-red":l.level==="warning"?"text-yellow-300":"text-neon-green"}>[{l.level}]</span> {l.message}</div>)}{!data?.logs?.length&&<span className="text-bunker-muted">Henüz log yok. Önizleme ile başlayın.</span>}</div></div>
  </main>;
}
