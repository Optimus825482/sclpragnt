"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_BASE, apiRequest, fetchAllPages } from "../lib/api";
import { useLiveMessages } from "../lib/liveSocket";
import SymbolLink from "../components/SymbolLink";
import MemoryTab from "../memory/MemoryTab";

const money=(v:number)=>`₺${v.toLocaleString("tr-TR",{minimumFractionDigits:2,maximumFractionDigits:2})}`;
const label=(s:string)=>({MOMENTUM:"MTF Momentum Ranking",EMA_VWAP_PULLBACK:"EMA + VWAP Pullback",VWAP_MEAN_REVERSION:"VWAP Mean Reversion",BB_MFI_MEAN_REVERSION:"BB + MFI Mean Reversion",CHOP_TREND_FILTER:"CHOP Trend Filter",KELTNER_BREAKOUT:"Keltner Breakout",DONCHIAN_BREAKOUT:"Donchian Breakout",GAINER_RADAR:"Gainer Radar"}[s]||s||"Bilinmiyor");
type Trade={id:number;trade_id?:string;symbol:string;strategy:string;pnl:number;pnl_pct:number;reason?:string;entry_time:number;exit_time?:number;commission?:number;hold_seconds?:number;entry_context?:any;strategy_revision?:string};
type Decision={id:number;timestamp:number;symbol:string;strategy?:string;decision:string;reason?:string;price?:number;metadata?:any};

function Stat({title,value,tone="text-white"}:{title:string;value:string;tone?:string}){return <div className="card report-stat"><p className="eyebrow">{title}</p><p className={`font-mono text-2xl mt-2 ${tone}`}>{value}</p></div>}
function ForecastTab({ report, loading, error }: { report: any; loading: boolean; error: string }) {
 if (loading) return <section className="card text-bunker-muted">LLM Chat tahmin raporu yükleniyor…</section>;
 if (error) return <section className="card border-neon-red/30 text-neon-red">LLM Chat tahmin raporu alınamadı: {error}</section>;
 if (!report) return <section className="card text-bunker-muted">Henüz Chat sayfasından kaydedilmiş tahmin yok.</section>;
 const pct=(value:any)=>value==null?"—":`%${(Number(value)*100).toFixed(1)}`;
 return <div className="space-y-4"><div className="grid grid-cols-2 gap-3 lg:grid-cols-4"><Stat title="Ölçülen tahmin" value={String(report.evaluated_count||0)}/><Stat title="Yön doğruluğu" value={pct(report.directional_accuracy)} tone={report.directional_accuracy!=null&&report.directional_accuracy>=.55?"text-neon-green":"text-yellow-300"}/><Stat title="Doğru tahmin" value={`${report.correct_count||0}/${report.evaluated_count||0}`}/><Stat title="Bekleyen" value={String(report.pending_count||0)} tone="text-sky-300"/></div><section className="card"><p className="eyebrow">UFUK BAZLI BAŞARI</p><div className="mt-3 table-scroll"><table className="data-table"><thead><tr><th>Ufuk</th><th>Ölçülen</th><th>Doğru</th><th>Başarı</th><th>Ort. hareket</th><th>Bekleyen</th></tr></thead><tbody>{(report.horizons||[]).map((row:any)=><tr key={row.horizon_minutes}><td>{row.horizon_minutes} dk</td><td>{row.evaluated_count||0}</td><td>{row.correct_count||0}</td><td className={row.directional_accuracy!=null&&row.directional_accuracy>=.55?"text-neon-green":"text-neon-red"}>{pct(row.directional_accuracy)}</td><td>{pct(row.average_return_pct)}</td><td>{row.pending_count||0}</td></tr>)}</tbody></table></div><p className="mt-3 text-xs text-bunker-muted">Sonuçlar yalnızca kapanmış M1 mumlarıyla ölçülür; az örneklem karar kanıtı değildir.</p></section><section className="card"><p className="eyebrow">SON TAHMİNLER</p><div className="mt-3 table-scroll"><table className="data-table"><thead><tr><th>Zaman</th><th>Sembol</th><th>Ufuk</th><th>Tahmin</th><th>Güven</th><th>Sonuç</th><th>Hareket</th></tr></thead><tbody>{(report.recent||[]).map((row:any)=><tr key={row.forecast_id}><td>{new Date(Number(row.created_at)*1000).toLocaleString("tr-TR")}</td><td><SymbolLink symbol={row.symbol} timeframe="1m" newTab className="text-white hover:text-neon-green"/></td><td>{row.horizon_minutes} dk</td><td>{row.direction==="up"?"YUKARI":row.direction==="down"?"AŞAĞI":"YATAY"}</td><td>%{Math.round(Number(row.confidence)||0)}</td><td className={row.status==="evaluated"?(row.direction_correct?"text-neon-green":"text-neon-red"):"text-yellow-300"}>{row.status==="evaluated"?(row.direction_correct?"DOĞRU":"YANLIŞ"):"BEKLİYOR"}</td><td>{row.status==="evaluated"?pct(row.outcome_return_pct):"—"}</td></tr>)}</tbody></table></div></section></div>;
}
type VelocityLiveRow = {
  candidate_id: string; symbol: string; entry_price: number; current_price: number | null;
  change_pct: number | null; target_pct: number; passes: boolean; velocity_score: number;
  status: string; touched: boolean; journal_touched: boolean | null; outcome: "success" | "ok" | "failed" | "pending";
  touch_sec: number | null; best_mfe_pct: number | null; elapsed_sec: number; remaining_sec: number;
  window_closed: boolean; window_time: string;
};
function VelocityTab({ report, loading, error }: { report: any; loading: boolean; error: string }) {
 const [deletingId,setDeletingId]=useState<string|null>(null);
 const [reloadKey,setReloadKey]=useState(0);
 const [data,setData]=useState<any>(null);
 const [live,setLive]=useState<VelocityLiveRow[]|null>(null);
 // Canlı izleme: 5 sn'de bir fiyat/süre tazeleme
 useEffect(()=>{
  let cancelled=false;
  const tick=()=>{apiRequest(`${API_BASE}/api/reports/velocity/live`,{cache:"no-store"}).then(r=>r.ok?r.json():Promise.reject(new Error(`HTTP ${r.status}`))).then(d=>{if(!cancelled)setLive(d.tracking||[]);}).catch(()=>undefined);};
  tick();
  const timer=window.setInterval(tick,5000);
  return ()=>{cancelled=true;window.clearInterval(timer);};
 },[reloadKey]);
 useEffect(()=>{
  if(!reloadKey) return; // ilk yükleme sayfa fetch'iyle gelir; reloadKey değişince tazele
  let cancelled=false;
  apiRequest(`${API_BASE}/api/reports/velocity?limit=60`,{cache:"no-store"}).then(r=>r.ok?r.json():Promise.reject(new Error(`HTTP ${r.status}`))).then(d=>{if(!cancelled){setData(d);}}).catch(()=>undefined);
  return ()=>{cancelled=true;};
 },[reloadKey]);
 const view = data || report;
 const deleteRow = (candidateId:string)=>{
  if(!window.confirm("Bu aday kaydı rapordan silinsin mi? (kalıcı)")) return;
  setDeletingId(candidateId);
  apiRequest(`${API_BASE}/api/reports/velocity/${encodeURIComponent(candidateId)}`,{method:"DELETE"})
   .then(r=>{if(!r.ok) throw new Error(`HTTP ${r.status}`); setDeletingId(null); setReloadKey(k=>k+1);})
   .catch(()=>setDeletingId(null));
 };
 if (loading) return <section className="card text-bunker-muted">Hız avcısı raporu yükleniyor…</section>;
 if (error) return <section className="card border-neon-red/30 text-neon-red">Hız avcısı raporu alınamadı: {error}</section>;
 if (!view) return <section className="card text-bunker-muted">Henüz hız avcısı taraması yok; Chat sayfasındaki "🚀 5 DK %2 HIZ AVCISI" butonuyla tarama başlatın.</section>;
 const pct=(value:any)=>value==null||Number.isNaN(Number(value))?"—":`%${(Number(value)*100).toFixed(1)}`;
 const stats=view.stats||{}; const learning=view.learning_state||{}; const filters=view.filters||{};
 const liveRows=live||[];
 const hitCount=liveRows.filter(r=>r.outcome==="success").length;
 const okCount=liveRows.filter(r=>r.outcome==="ok").length;
 const failCount=liveRows.filter(r=>r.outcome==="failed").length;
 const outcomeLabel=(row:VelocityLiveRow):{text:string;cls:string}=>{
  if(row.outcome==="success") return {text:"BAŞARILI · +%2 GEÇTİ",cls:"text-neon-green font-bold"};
  if(row.outcome==="ok") return {text:"OK · ÜZERİNE ÇIKTI",cls:"text-yellow-300"};
  if(row.outcome==="failed") return {text:"BAŞARISIZ · ÇIKAMADI",cls:"text-neon-red"};
  return {text:"İZLENİYOR",cls:"text-sky-300"};
 };
 return <div className="space-y-4">
  <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
   <Stat title="Canlı takip" value={String(liveRows.length)} tone="text-sky-300"/>
   <Stat title="Başarılı (+%2)" value={String(hitCount)} tone={hitCount>0?"text-neon-green":"text-white"}/>
   <Stat title="OK (üzerine çıktı)" value={String(okCount)} tone="text-yellow-300"/>
   <Stat title="Başarısız" value={String(failCount)} tone={failCount>0?"text-neon-red":"text-white"}/>
   <Stat title="Toplam aday" value={String(stats.total||0)}/>
   <Stat title="Ölçülen" value={String(stats.evaluated||0)} tone="text-sky-300"/>
  </div>
  <section className="card"><p className="eyebrow">CANLI İZLEME · ANALİZ ANI FİYAT → 5 DK PENCERE</p>
   <p className="mt-1 text-xs text-bunker-muted">BAŞARILI = 5 dk içinde +%2'yi geçti · OK = giriş fiyatının üzerine çıktı ama +%2 olmadı · BAŞARISIZ = üzerine hiç çıkamadı. Pencere kapanınca sonuç kilitlenir; 5 saniyede bir güncellenir.</p>
   <div className="mt-3 table-scroll"><table className="data-table"><thead><tr><th>Sembol</th><th>Giriş fiyatı</th><th>Canlı fiyat</th><th>Değişim</th><th>Sonuç</th><th>Süre</th><th>Max MFE</th><th>Pencere</th></tr></thead><tbody>{liveRows.map((row:VelocityLiveRow)=>{
    const lbl=outcomeLabel(row);
    return <tr key={row.candidate_id} className={row.outcome==="success"?"bg-neon-green/5":""}>
    <td><SymbolLink symbol={row.symbol} timeframe="1m" newTab className={row.outcome==="success"?"text-neon-green font-bold hover:text-white":"text-white hover:text-neon-green"}/></td>
    <td className="font-mono">{row.entry_price.toLocaleString("tr-TR",{maximumFractionDigits:8})}</td>
    <td className="font-mono">{row.current_price?.toLocaleString("tr-TR",{maximumFractionDigits:8})??"—"}</td>
    <td className={`font-mono ${(row.change_pct??0)>=2?"text-neon-green font-bold":(row.change_pct??0)>0?"text-neon-green":(row.change_pct??0)<0?"text-neon-red":""}`}>{row.change_pct!=null?`${row.change_pct>=0?"+":""}${row.change_pct.toFixed(2)}%`:"—"}</td>
    <td className={lbl.cls}>{lbl.text}</td>
    <td className="font-mono text-xs">{row.outcome==="success"&&row.touch_sec!=null?`${Math.floor(row.touch_sec/60)}dk ${row.touch_sec%60}sn'de geçti`:row.outcome==="pending"?`${Math.floor(row.elapsed_sec/60)}:${String(row.elapsed_sec%60).padStart(2,"0")} / 5:00`:"5:00 doldu"}</td>
    <td className={((row.best_mfe_pct??0)>=2)?"text-neon-green":"font-mono"}>{pct(row.best_mfe_pct)}</td>
    <td className="text-bunker-muted text-xs">{row.window_time}</td>
   </tr>;})}</tbody></table></div>
   {!liveRows.length&&<p className="mt-2 text-sm text-bunker-muted">Son 30 dakikada aday yok; Chat sayfasından "🚀 5 DK %2 HIZ AVCISI" taraması başlatın.</p>}
  </section>
  <section className="card"><p className="eyebrow">OTONOM HIZ AVCISI · 15 DK'DA BİR OTOMATİK POZİSYON</p>
   <div className="mt-2 flex flex-wrap items-center gap-2 text-xs font-mono">
    <span className={`rounded px-2 py-1 ${(view.auto_trade?.enabled)?"text-neon-green border border-neon-green/40":"text-yellow-300 border border-yellow-400/40"}`}>{view.auto_trade?.enabled?"OTONOM AKTİF":"KAPALI (env: VELOCITY_AUTO_ENABLED + LLM paper ayarı)"}</span>
    <span className="rounded border border-bunker-700 px-2 py-1">her {Math.round((view.auto_trade?.interval_sec||900)/60)} dk</span>
    <span className="rounded border border-bunker-700 px-2 py-1">bakiyenin %{view.auto_trade?.balance_pct||50}'i</span>
    <span className="rounded border border-neon-red/40 px-2 py-1">stop %{view.auto_trade?.sl_pct||1.5}</span>
    <span className="rounded border border-sky-400/40 px-2 py-1">+%{view.auto_trade?.trail_trigger_pct||1}'de ATR trailing</span>
    <span className="rounded border border-bunker-700 px-2 py-1">açılan: {view.auto_trade?.state?.total_opened||0}</span>
   </div>
   <p className="mt-2 text-xs text-bunker-muted">Çıkış merdiveni: fiyat girişin üstüne çıktığında stop break-even'e çekilir (kar kilitli), +%1'e ulaşınca ATR trailing devreye girer (maksimum kâr koşusu), sert stop her zaman %1.5.</p>
   {view.auto_trade?.state?.last_open&&<p className="mt-2 font-mono text-xs text-sky-300">Son deneme: {view.auto_trade.state.last_open.symbol} — {view.auto_trade.state.last_open.status}{view.auto_trade.state.last_open.reason?` (${view.auto_trade.state.last_open.reason})`:""}</p>}
   {(view.auto_trade?.recent_opens||[]).length>0&&<div className="mt-2 table-scroll"><table className="data-table"><thead><tr><th>Zaman</th><th>Sembol</th><th>Miktar</th><th>Giriş</th><th>Stop</th><th>Skor</th></tr></thead><tbody>{(view.auto_trade.recent_opens||[]).slice().reverse().map((o:any,i:number)=><tr key={i}><td>{o.at?new Date(o.at*1000).toLocaleTimeString("tr-TR"):"—"}</td><td>{o.symbol}</td><td>{o.order_value_try} TL</td><td>{o.entry}</td><td>%{o.stop_loss_pct}</td><td>{o.score}</td></tr>)}</tbody></table></div>}
  </section>
  <section className="card"><p className="eyebrow">FİLTRE PERFORMANSI · GEÇENLER</p>
   <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
    <Stat title="Geçen aday" value={String(stats.passing_count||0)}/>
    <Stat title="Geçenlerde dokunuş" value={`${stats.passing_touched||0}/${stats.passing_count||0}`}/>
    <Stat title="Koşullu isabet" value={pct(stats.passing_hit_rate)} tone={(stats.passing_hit_rate??0)>=0.19?"text-neon-green":"text-yellow-300"}/>
    <Stat title="Geçenlerde ort. MFE" value={pct(stats.passing_average_mfe_pct)}/>
   </div>
   <p className="mt-3 text-xs text-bunker-muted">v2 filtre: ATR% ≥ {filters.min_atr_pct} · Bollinger genişliği ≥ %{filters.min_bb_width_pct} · RSI ≥ {filters.trend_rsi_min} (trend) veya ≤ {filters.reversal_rsi_max} (V-dönüşü) · LinReg ≥ %{filters.struct_slope_pct} veya Aroon ≥ 50. Kalibrasyon hedefi %19 (replay); canlı değer saparsa öğrenme döngüsü ATR eşiğini ±0.05 kaydırır.</p>
  </section>
  <section className="card"><p className="eyebrow">ÖĞRENME DÖNGÜSÜ</p>
   <div className="mt-2 grid grid-cols-2 gap-2 font-mono text-xs lg:grid-cols-4">
    <span className="rounded border border-bunker-700 p-2">Son ölçüm: {learning.last_run_at?new Date(learning.last_run_at*1000).toLocaleTimeString("tr-TR"):"—"}</span>
    <span className="rounded border border-bunker-700 p-2">Ölçülen: {learning.measured||0}</span>
    <span className="rounded border border-bunker-700 p-2">Son kalibrasyon: {learning.last_calibrated_at?new Date(learning.last_calibrated_at*1000).toLocaleTimeString("tr-TR"):"—"}</span>
    <span className={`rounded border border-bunker-700 p-2 ${learning.last_error?"text-neon-red":"text-neon-green"}`}>{learning.last_error?"HATA":"Çalışıyor"}</span>
   </div>
   {learning.active_filters&&<p className="mt-2 font-mono text-xs text-sky-300">Kalibre edilmiş filtre: {JSON.stringify(learning.active_filters)}</p>}
  </section>
  <section className="card"><p className="eyebrow">SEMBOLE GÖRE DOKUNUŞ BAŞARISI</p>
   <div className="mt-3 table-scroll"><table className="data-table"><thead><tr><th>Sembol</th><th>Ölçülen</th><th>Dokunan</th><th>Oran</th><th>Ort. MFE</th></tr></thead><tbody>{(view.symbols||[]).map((row:any)=><tr key={row.symbol}><td><SymbolLink symbol={row.symbol} timeframe="1m" newTab className="text-white hover:text-neon-green"/></td><td>{row.evaluated}</td><td>{row.touched}</td><td className={(row.touch_rate??0)>=0.15?"text-neon-green":"text-neon-red"}>{pct(row.touch_rate)}</td><td>{pct(row.average_mfe_pct)}</td></tr>)}</tbody></table></div>
   {!(view.symbols||[]).length&&<p className="mt-2 text-sm text-bunker-muted">Henüz ölçülmüş sembol yok; sonuçlar 5 dakikalık pencere kapandıktan sonra birikir.</p>}
  </section>
  <section className="card"><p className="eyebrow">SON ADAYLAR VE SONUÇLARI</p>
   <div className="mt-3 table-scroll"><table className="data-table"><thead><tr><th>Zaman</th><th>Sembol</th><th>Koşul</th><th>ATR%</th><th>İvme</th><th>Skor</th><th>Sonuç</th><th>MFE</th><th>Sil</th></tr></thead><tbody>{(view.recent||[]).map((row:any)=><tr key={row.candidate_id}><td>{new Date(Number(row.created_at)*1000).toLocaleString("tr-TR")}</td><td><SymbolLink symbol={row.symbol} timeframe="1m" newTab className="text-white hover:text-neon-green"/></td><td className={row.passes?"text-neon-green":"text-bunker-muted"}>{row.passes?"GEÇTİ":"İZLEME"}</td><td>{row.atr_pct}</td><td>%{row.ret3_pct}</td><td>{row.velocity_score}</td><td className={row.status==="evaluated"?(row.touched_target?"text-neon-green":"text-neon-red"):"text-yellow-300"}>{row.status==="evaluated"?(row.touched_target?"+%2 DOKUNDU":"DOKUNMADI"):"BEKLİYOR"}</td><td>{row.status==="evaluated"?pct(row.mfe_pct):"—"}</td><td><button onClick={()=>deleteRow(row.candidate_id)} disabled={deletingId!==null} title="Bu kaydı rapordan sil (kalıcı)" className="rounded border border-red-400/50 bg-red-400/10 px-2 py-0.5 font-mono text-[10px] text-red-300 hover:bg-red-400/20 disabled:opacity-50">{deletingId===row.candidate_id?"…":"✕"}</button></td></tr>)}</tbody></table></div>
   {!(view.recent||[]).length&&<p className="mt-2 text-sm text-bunker-muted">Kayıt yok; Chat sayfasından hız taraması başlatın.</p>}
  </section>
 </div>;
}
function ChatPredictionsTab({ report, loading, error }: { report: any; loading: boolean; error: string }) {
 const [symbolFilter,setSymbolFilter]=useState("");
 const [replay,setReplay]=useState<any>(null);
 const [replayBusy,setReplayBusy]=useState(false);
 // Hook'lar koşulsuz ve early return'lerden ÖNCE çağrılmalı; aksi halde render
 // sırasında hook sayısı değişir ve React #310 ("Rendered fewer hooks")
 // oluşur. Filtreleme de bu yüzden hooksuz hesaplanıyor.
 const insights=useMemo(()=>((report||{}).insights||[]).filter((row:any)=>!symbolFilter||row.symbol===symbolFilter.toUpperCase()),[report,symbolFilter]);
 const recent=useMemo(()=>((report||{}).recent||[]).filter((row:any)=>!symbolFilter||row.symbol===symbolFilter.toUpperCase()),[report,symbolFilter]);
 const runReplay=async(lookbackHours:number)=>{
  if(replayBusy)return;
  setReplayBusy(true);
  try{
   // refresh=true her zaman yeni replay işi başlatır; iş arka planda koşar, state'i yoklayalım
   apiRequest(`${API_BASE}/api/reports/chat-predictions/replay?lookback_hours=${lookbackHours}&horizons=5,15&refresh=true`,{cache:"no-store"}).then(r=>r.json()).then(setReplay).catch(()=>undefined);
   const deadline=Date.now()+180_000;
   const poll=window.setInterval(async()=>{
    try{
     const res=await apiRequest(`${API_BASE}/api/reports/chat-predictions/replay?lookback_hours=${lookbackHours}&horizons=5,15`,{cache:"no-store"});
     const data=await res.json();
     setReplay(data);
     if(data.state?.status==="completed"||data.state?.status==="failed"||Date.now()>deadline){window.clearInterval(poll);setReplayBusy(false);}
    }catch{window.clearInterval(poll);setReplayBusy(false);}
   },4000);
  }catch{setReplayBusy(false);}
 };
 if (loading) return <section className="card text-bunker-muted">Chat M5/M15 tahmin raporu yükleniyor…</section>;
 if (error) return <section className="card border-neon-red/30 text-neon-red">Chat tahmin raporu alınamadı: {error}</section>;
 if (!report) return <section className="card text-bunker-muted">Henüz Chat sayfasından kaydedilmiş M5/M15 tahmini yok.</section>;
 const pct=(value:any)=>value==null||Number.isNaN(Number(value))?"—":`%${(Number(value)*100).toFixed(1)}`;
 const learning=report.learning_state||{};
 const replayResult=replay?.state?.result; const replayState=replay?.state||{};
 return <div className="space-y-4">
  <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
   <Stat title="Ölçülen tahmin" value={String(report.evaluated_count||0)}/>
   <Stat title="Yön doğruluğu" value={pct(report.directional_accuracy)} tone={report.directional_accuracy!=null&&report.directional_accuracy>=.55?"text-neon-green":"text-yellow-300"}/>
   <Stat title="Doğru tahmin" value={`${report.correct_count||0}/${report.evaluated_count||0}`}/>
   <Stat title="Bekleyen" value={String(report.pending_count||0)} tone="text-sky-300"/>
   <Stat title="LLM analizi" value={`${report.analyzed_count||0}`} tone="text-sky-300"/>
  </div>
  <section className="card">
   <div className="flex flex-wrap items-center justify-between gap-3">
    <div><p className="eyebrow">REPLAY TESTİ · GERİYE DÖNÜK SANAL TARAMA</p>
     <p className="mt-2 text-sm text-bunker-muted">Canlı pipeline'ı geçmiş kapanmış mumlarla yeniden koşar: her adımda o ana kadar kapanmış 1m→5m/15m mumlardan snapshot üretir, aynı skorla en iyi 3 adayı seçer ve sonucu sonraki kapanmış mumlarla ölçer.</p></div>
    <div className="flex gap-2">
     <button onClick={()=>runReplay(6)} disabled={replayBusy} className="min-h-10 rounded-lg border border-neon-green/40 bg-neon-green/10 px-4 font-mono text-sm text-neon-green disabled:opacity-50">{replayBusy?"REPLAY KOŞUYOR…":"SON 6 SAAT (M5+M15)"}</button>
     <button onClick={()=>runReplay(24)} disabled={replayBusy} className="min-h-10 rounded-lg border border-sky-400/40 bg-sky-400/10 px-4 font-mono text-sm text-sky-300 disabled:opacity-50">SON 24 SAAT</button>
    </div>
   </div>
   {replayState.status==="running"&&<p className="mt-3 font-mono text-xs text-yellow-300">Replay arka planda koşuyor · {replayState.message||"…"}</p>}
   {replayState.status==="failed"&&<p className="mt-3 font-mono text-xs text-neon-red">Replay başarısız: {replayState.message||"bilinmeyen hata"}</p>}
   {replayResult&&replayResult.status==="ok"&&<div className="mt-4 space-y-3">
    <div className="grid grid-cols-2 gap-2 font-mono text-xs lg:grid-cols-5">
     <span className="rounded border border-bunker-700 p-2">Pencere: {replayResult.lookback_hours} saat · {replayResult.steps} adım</span>
     <span className="rounded border border-bunker-700 p-2">Sembol: {replayResult.symbols_scanned}</span>
     <span className="rounded border border-bunker-700 p-2">Aralık: {new Date(replayResult.window_start_ms).toLocaleString("tr-TR",{dateStyle:"short",timeStyle:"short"})} → {new Date(replayResult.window_end_ms).toLocaleString("tr-TR",{dateStyle:"short",timeStyle:"short"})}</span>
     <span className="rounded border border-bunker-700 p-2">Etiket: canlı journal ile aynı eşik</span>
     <span className="rounded border border-bunker-700 p-2 text-yellow-300">Sınırlar: spread/derinlik geçmişi yok</span>
    </div>
    <div className="table-scroll"><table className="data-table"><thead><tr><th>Ufuk</th><th>Aday seçimi</th><th>Ölçülen</th><th>Doğru</th><th>Başarı</th><th>Eşik altı (range)</th><th>Ort. hareket</th><th>Ort. güven</th><th>Calibration</th></tr></thead><tbody>{(replayResult.horizons||[]).map((row:any)=><tr key={row.horizon_minutes}><td className="font-bold">{row.horizon_minutes} dk</td><td>{row.predictions||0}</td><td>{row.evaluated||0}</td><td>{row.correct||0}</td><td className={row.directional_accuracy!=null&&row.directional_accuracy>=.55?"text-neon-green":row.directional_accuracy!=null?"text-neon-red":"text-bunker-muted"}>{pct(row.directional_accuracy)}</td><td>{row.range_count||0}</td><td>{pct(row.average_return_pct)}</td><td>{row.average_confidence?`%${Math.round(row.average_confidence)}`:"—"}</td><td>{pct(row.calibration_error)}</td></tr>)}</tbody></table></div>
    <p className="eyebrow">SEMBOLE GÖRE REPLAY SONUCU</p>
    <div className="table-scroll"><table className="data-table"><thead><tr><th>Sembol</th><th>Ölçülen</th><th>Doğru</th><th>Başarı</th><th>Ort. hareket</th></tr></thead><tbody>{(replayResult.symbols||[]).map((row:any)=><tr key={row.symbol}><td><SymbolLink symbol={row.symbol} timeframe="1m" newTab className="text-white hover:text-neon-green"/></td><td>{row.evaluated}</td><td>{row.correct}</td><td className={row.directional_accuracy>=.55?"text-neon-green":"text-neon-red"}>{pct(row.directional_accuracy)}</td><td>{pct(row.average_return_pct)}</td></tr>)}</tbody></table></div>
   </div>}
  </section>
  <section className="card"><p className="eyebrow">OTOMATİK PAPER POZİSYON · YÜKSEK GÜVEN DESEN</p>
   <div className="mt-2 flex flex-wrap items-center gap-2 text-xs font-mono">
    <span className={`rounded px-2 py-1 ${(report.auto_trade?.enabled)?"text-neon-green border border-neon-green/40":"text-yellow-300 border border-yellow-400/40"}`}>{report.auto_trade?.enabled?"AKTİF":"KAPALI (env: CHAT_PREDICTION_AUTO_TRADE_ENABLED + LLM paper ayarı)"}</span>
    <span className="rounded border border-bunker-700 px-2 py-1">min {report.auto_trade?.config?.min_pattern_matches??2} eşleşme</span>
    <span className="rounded border border-neon-green/40 px-2 py-1">yüksek güven ≥{report.auto_trade?.config?.high_confidence_matches??3}</span>
    <span className="rounded border border-bunker-700 px-2 py-1">TP %{report.auto_trade?.config?.tp_pct??0.8}</span>
    <span className="rounded border border-bunker-700 px-2 py-1">SL %{report.auto_trade?.config?.sl_pct??0.5}</span>
    <span className="rounded border border-bunker-700 px-2 py-1">max {report.auto_trade?.config?.max_hold_seconds??900}s</span>
    <span className="rounded border border-bunker-700 px-2 py-1">limit {report.auto_trade?.config?.max_open_positions??2}</span>
    <span className="rounded border border-bunker-700 px-2 py-1">{report.auto_trade?.config?.order_value_try??300} TRY</span>
    <span className="rounded border border-bunker-700 px-2 py-1">toplam açılan: {report.auto_trade?.state?.total_opened??0}</span>
   </div>
   <p className="mt-2 text-xs text-bunker-muted">Desen: {(report.pattern_state?.tags||[]).join(", ")||"—"} · kaynak: {report.pattern_state?.source||"—"}</p>
   {(report.auto_trade?.state?.opened||[]).length>0&&<div className="mt-3 table-scroll"><table className="data-table"><thead><tr><th>Zaman</th><th>Sembol</th><th>Durum</th><th>Neden</th></tr></thead><tbody>{(report.auto_trade.state.opened||[]).slice(-8).reverse().map((row:any,i:number)=><tr key={i}><td>{row.queued_at?new Date(row.queued_at*1000).toLocaleTimeString("tr-TR"):"—"}</td><td>{row.symbol}</td><td className={row.status==="PAPER_OPENED"?"text-neon-green":row.status==="SKIPPED"?"text-yellow-300":"text-neon-red"}>{row.status}</td><td className="max-w-56 truncate" title={row.reason||""}>{row.reason||"—"}</td></tr>)}</tbody></table></div>}
  </section>
  <section className="card"><p className="eyebrow">M5 VE M15 UFUK BAZLI BAŞARI</p><div className="mt-3 table-scroll"><table className="data-table"><thead><tr><th>Ufuk</th><th>Kayıt</th><th>Ölçülen</th><th>Doğru</th><th>Başarı</th><th>Ort. hareket</th><th>Calibration</th><th>Analiz</th></tr></thead><tbody>{(report.horizons||[]).map((row:any)=><tr key={row.horizon_minutes}><td className="font-bold">{row.horizon_minutes} dk</td><td>{row.total_count||0}</td><td>{row.evaluated_count||0}</td><td>{row.correct_count||0}</td><td className={row.directional_accuracy!=null&&row.directional_accuracy>=.55?"text-neon-green":"text-neon-red"}>{pct(row.directional_accuracy)}</td><td>{pct(row.average_return_pct)}</td><td>{pct(row.calibration_error)}</td><td>{row.analyzed_count||0}</td></tr>)}</tbody></table></div><p className="mt-3 text-xs text-bunker-muted">Sonuç yalnızca kapanmış M1 mumlarıyla ölçülür; tahmin, giriş eşiği + tur maliyeti + ATR gürültü oranını geçmezse 'range' sayılır. LLM analizi arka planda çalışır; sonuç asla LLM tarafından üretilmez.</p></section>
  <section className="card"><p className="eyebrow">SEMBOLE GÖRE BAŞARI</p><div className="mt-3 table-scroll"><table className="data-table"><thead><tr><th>Sembol</th><th>Ölçülen</th><th>Doğru</th><th>Başarı</th><th>Ort. hareket</th></tr></thead><tbody>{(report.symbols||[]).map((row:any)=><tr key={row.symbol}><td><SymbolLink symbol={row.symbol} timeframe="1m" newTab className="text-white hover:text-neon-green"/></td><td>{row.evaluated_count||0}</td><td>{row.correct_count||0}</td><td className={row.directional_accuracy!=null&&row.directional_accuracy>=.55?"text-neon-green":"text-neon-red"}>{pct(row.directional_accuracy)}</td><td>{pct(row.average_return_pct)}</td></tr>)}</tbody></table></div>{!(report.symbols||[]).length&&<p className="mt-2 text-sm text-bunker-muted">Henüz ölçülmüş sembol yok.</p>}</section>
  <section className="card"><div className="flex flex-wrap items-center justify-between gap-3"><p className="eyebrow">ÖĞRENİLEN DERSLER · LLM POSTMORTEM</p><input value={symbolFilter} onChange={e=>setSymbolFilter(e.target.value)} placeholder="Sembol filtrele (örn. BTCTRY)" className="min-h-9 w-56 rounded-lg border border-bunker-700 bg-bunker-950 px-3 font-mono text-xs text-white"/></div>
   <div className="mt-3 space-y-2">{insights.length?insights.map((row:any)=><div key={row.insight_key} className="rounded-lg border border-bunker-700 bg-bunker-950/60 p-3"><div className="flex flex-wrap items-center gap-2 font-mono text-xs"><span className="text-neon-green">{row.symbol||"GENEL EVREN"}</span><span className="text-bunker-muted">{row.horizon_minutes} dk</span><span>n={row.sample_size}</span><span className="text-neon-green">{row.success_count}✓</span><span className="text-neon-red">{row.failure_count}✗</span></div><p className="mt-2 text-sm text-white">{row.insight}</p>{(row.factors?.misleading_factors||[]).length>0&&<p className="mt-2 text-xs text-neon-red">Yanıltan: {row.factors.misleading_factors.join(", ")}</p>}{(row.factors?.success_factors||[]).length>0&&<p className="mt-1 text-xs text-neon-green">Destekleyen: {row.factors.success_factors.join(", ")}</p>}</div>):<p className="text-sm text-bunker-muted">Henüz analiz edilmiş tahmin yok; yeterli örnek biriktikçe LLM postmortem dersleri burada listelenir.</p>}</div>
  </section>
  <section className="card"><p className="eyebrow">SON TAHMİNLER VE SONUÇLARI</p>
   <div className="mt-3 table-scroll"><table className="data-table"><thead><tr><th>Zaman</th><th>Sembol</th><th>Ufuk</th><th>Güven</th><th>Sonuç</th><th>Hareket</th><th>Skor</th><th>LLM Analizi</th></tr></thead><tbody>{recent.map((row:any)=><tr key={row.prediction_id}><td>{new Date(Number(row.created_at)*1000).toLocaleString("tr-TR")}</td><td><SymbolLink symbol={row.symbol} timeframe="1m" newTab className="text-white hover:text-neon-green"/></td><td>{row.horizon_minutes} dk</td><td>%{Math.round(Number(row.confidence)||0)}</td><td className={row.status==="evaluated"?(row.direction_correct?"text-neon-green":"text-neon-red"):"text-yellow-300"}>{row.status==="evaluated"?(row.direction_correct?"DOĞRU":"YANLIŞ"):"BEKLİYOR"}</td><td>{row.status==="evaluated"?<span title={row.outcome_direction==="range"?"Eşik aşılamadı; hareket yetersiz":undefined}>{pct(row.outcome_return_pct)}</span>:"—"}</td><td>{row.score??"—"}</td><td className="max-w-56 truncate" title={row.analysis||""}>{row.analysis?"✓ "+row.analysis:row.analysis_status==="pending"?"Kuyrukta":"—"}</td></tr>)}</tbody></table></div>
   {!(recent||[]).length&&<p className="mt-2 text-sm text-bunker-muted">Henüz kayıt yok; Chat sayfasındaki 5 DK / 15 DK yükseliş aday taramaları bu tabloya yazılır.</p>}
  </section>
  <section className="card"><p className="eyebrow">ÖĞRENME DÖNGÜSÜ DURUMU</p><div className="mt-2 grid grid-cols-2 gap-2 font-mono text-xs lg:grid-cols-4"><span className="rounded border border-bunker-700 p-2">Son tarama: {learning.last_run_at?new Date(learning.last_run_at*1000).toLocaleTimeString("tr-TR"):"—"}</span><span className="rounded border border-bunker-700 p-2">Değerlendirilen: {learning.evaluated||0}</span><span className="rounded border border-bunker-700 p-2">Analiz edilen: {learning.analyzed||0}</span><span className={`rounded border border-bunker-700 p-2 ${learning.last_error?"text-neon-red":"text-neon-green"}`}>{learning.last_error?"Hata: "+String(learning.last_error).slice(0,40):"Çalışıyor"}</span></div><p className="mt-2 text-xs text-bunker-muted">Aktif içgörüler sonraki taramalara ve chat bağlamına otomatik enjekte edilir; LLM kendi dersini doğrulayamaz, yalnızca ölçülmüş sonuç üzerinden türetilir.</p></section>
 </div>;
}
function DecisionTab({decisions:signals,trades}:{decisions:any[];trades:Trade[]}){
 const [query,setQuery]=useState(""); const [status,setStatus]=useState("all"); const [strategy,setStrategy]=useState("all");
 const [page,setPage]=useState(1); const pageSize=25;
 const source=signals;
 const knownStrategies=["MOMENTUM","ORDERFLOW","EMA_VWAP_PULLBACK","VWAP_MEAN_REVERSION","BB_MFI_MEAN_REVERSION","CHOP_TREND_FILTER","KELTNER_BREAKOUT","DONCHIAN_BREAKOUT","BB_SQUEEZE_ORDERFLOW","GAINER_RADAR"];
 const strategies=Array.from(new Set(source.map(d=>d.strategy||d.reason).filter(Boolean))) as string[];
 const rows=useMemo(()=>source.filter(d=>["BUY_SIGNAL","BUY_BLOCKED","LLM_REENTRY_BLOCKED","CLOSE_LONG"].includes(d.action)).map(d=>{
   const decision=d.action;
   const inferredStrategy=d.strategy||(knownStrategies.includes(String(d.reason||""))?d.reason:undefined);
   const eventTradeId=d.trade_id||d.metadata?.trade_id;
   const trade=decision==="BUY_BLOCKED"?undefined:trades.find(t=>eventTradeId
     ? t.trade_id===eventTradeId
     : t.symbol===d.symbol&&(!inferredStrategy||t.strategy===inferredStrategy)&&(
       decision==="CLOSE_LONG" ? Math.abs((t.exit_time||0)-d.timestamp)<180 : Math.abs((t.entry_time||0)-d.timestamp)<180
     ));
   const opened=decision==="BUY_SIGNAL";
   const resolvedStrategy=inferredStrategy||trade?.strategy;
   return {...d,decision,strategy:resolvedStrategy,reason:d.reason===(resolvedStrategy||"__none__")&&opened?"position_opened":d.reason,trade,opened,match_basis:trade?(eventTradeId?"trade_id":"legacy_timestamp"):undefined,status:["BUY_BLOCKED","LLM_REENTRY_BLOCKED"].includes(decision)?"blocked":decision==="CLOSE_LONG"?(trade?"closed":"unmatched"):(trade?"closed":"open")};
 }).filter(r=>(status==="all"||r.status===status)&&(strategy==="all"||r.strategy===strategy)&&(!query||`${r.symbol} ${r.strategy||""} ${r.reason||""}`.toLowerCase().includes(query.toLowerCase()))),[source,trades,status,strategy,query]);
 const pages=Math.max(1,Math.ceil(rows.length/pageSize)); const visible=rows.slice((page-1)*pageSize,page*pageSize);
 const exportCsv=()=>{const head=["Zaman","Sembol","Strateji","Sinyal","Durum","Eşleme","Fiyat","Neden","PnL","PnL %","Komisyon","Aktif Süre","Trade ID","Strateji Sürümü"];const esc=(v:any)=>`"${String(v??"").replaceAll('"','""')}"`;const body=rows.map(r=>[new Date(r.timestamp*1000).toLocaleString("tr-TR"),r.symbol,label(r.strategy||""),r.decision,r.status,r.match_basis,r.price,r.reason,r.trade?.pnl,r.trade?.pnl_pct,r.trade?.commission,r.trade?.hold_seconds,r.trade?.trade_id,r.trade?.strategy_revision||r.trade?.entry_context?.strategy_revision].map(esc).join(","));const blob=new Blob(["\ufeff"+[head.map(esc).join(","),...body].join("\n")],{type:"text/csv;charset=utf-8"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="sinyal-karar-analizi.csv";a.click();URL.revokeObjectURL(a.href)};
 const blocked=rows.filter(r=>r.status==="blocked").length, opened=rows.filter(r=>r.opened).length, closed=rows.filter(r=>r.opened&&r.trade).length;
 return <div className="space-y-4"><div className="grid grid-cols-2 lg:grid-cols-4 gap-3"><Stat title="Toplam sinyal" value={String(rows.length)}/><Stat title="İşleme dönüşen" value={String(opened)} tone="text-neon-green"/><Stat title="Engellenen" value={String(blocked)} tone="text-yellow-300"/><Stat title="Kapanan sonucu olan" value={String(closed)}/></div><div className="card space-y-3"><div className="flex flex-wrap gap-2"><input value={query} onChange={e=>{setQuery(e.target.value);setPage(1)}} placeholder="Sembol, strateji veya neden ara" className="min-h-10 flex-1 min-w-56 rounded-lg border border-bunker-700 bg-bunker-950 px-3 font-mono text-sm text-white"/><select value={strategy} onChange={e=>{setStrategy(e.target.value);setPage(1)}} className="min-h-10 rounded-lg border border-bunker-700 bg-bunker-950 px-3 font-mono text-sm text-white"><option value="all">Tüm stratejiler</option>{strategies.map(s=><option key={s} value={s}>{label(s)}</option>)}</select><select value={status} onChange={e=>{setStatus(e.target.value);setPage(1)}} className="min-h-10 rounded-lg border border-bunker-700 bg-bunker-950 px-3 font-mono text-sm text-white"><option value="all">Tüm durumlar</option><option value="closed">Kapanan işlem</option><option value="open">Açık işlem</option><option value="blocked">Açılmayan</option></select><button onClick={exportCsv} className="min-h-10 rounded-lg border border-neon-green/40 bg-neon-green/10 px-4 font-mono text-sm text-neon-green">CSV İNDİR</button></div><div className="table-scroll"><table className="data-table"><thead><tr>{["Zaman","Sembol","Strateji","Sinyal","Durum","Fiyat","Neden","PnL","Komisyon","Süre"].map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{visible.map((r:any)=><tr key={r.uiKey||`${r.decision}:${r.id}`}><td>{new Date(r.timestamp*1000).toLocaleString("tr-TR")}</td><td><SymbolLink symbol={r.symbol} className="text-white hover:text-neon-green" /></td><td>{label(r.strategy||"")}</td><td>{r.decision}</td><td title={r.match_basis==="legacy_timestamp"?"Eski kayıtta trade_id olmadığı için zaman penceresiyle eşlendi":undefined} className={r.status==="blocked"?"text-yellow-300":r.status==="closed"?"text-neon-green":"text-sky-300"}>{r.status==="blocked"?"AÇILMADI":r.status==="closed"?`KAPANDI${r.match_basis==="legacy_timestamp"?" · LEGACY":""}`:"AÇIK"}</td><td>{r.price??"—"}</td><td className="max-w-56 truncate" title={r.reason||""}>{r.reason||"—"}</td><td className={r.trade?.pnl<0?"text-neon-red":r.trade?.pnl>0?"text-neon-green":""}>{r.trade?money(r.trade.pnl):"—"}</td><td>{r.trade?money(r.trade.commission||0):"—"}</td><td>{r.trade?`${Math.round((r.trade.hold_seconds||0)/60)} dk`:"—"}</td></tr>)}</tbody></table></div><div className="flex items-center justify-between font-mono text-xs text-bunker-muted"><span>{rows.length} kayıt · sayfa {page}/{pages}</span><div className="flex gap-2"><button disabled={page<=1} onClick={()=>setPage(p=>p-1)} className="rounded border border-bunker-700 px-3 py-1 disabled:opacity-40">Önceki</button><button disabled={page>=pages} onClick={()=>setPage(p=>p+1)} className="rounded border border-bunker-700 px-3 py-1 disabled:opacity-40">Sonraki</button></div></div></div></div>
}
function CapitalLockTab({report,positions,onClose}:{report:any;positions:any[];onClose:(symbol:string)=>Promise<{ok:boolean;message:string}>}){
 const [closing,setClosing]=useState<string|null>(null); const [message,setMessage]=useState("");
 if(!report)return <section className="card text-bunker-muted">Sermaye-kilit raporu yükleniyor…</section>;
 const tone=Number(report.capital_lock_net_pnl_try||0)<0?"text-neon-red":"text-neon-green";
 const exportCsv=()=>{const head=["Sembol","Giriş","Çıkış","Süre (dk)","MFE (%)","MAE (%)","PnL (TRY)","Kapanış nedeni","M1 snapshot"];const esc=(v:any)=>`"${String(v??"").replaceAll('"','""')}"`;const body=(report.rows||report.recent||[]).map((row:any)=>[row.symbol,row.entry_time?new Date(row.entry_time*1000).toLocaleString("tr-TR"):"",row.exit_time?new Date(row.exit_time*1000).toLocaleString("tr-TR"):"",Math.round(Number(row.hold_seconds||0)/60),Number(row.max_favorable_pct||0).toFixed(2),Number(row.max_adverse_pct||0).toFixed(2),Number(row.pnl||0).toFixed(2),row.reason,row.activity_snapshot_present?"VAR":"ESKİ KAYIT"].map(esc).join(","));const blob=new Blob(["\ufeff"+[head.map(esc).join(","),...body].join("\n")],{type:"text/csv;charset=utf-8"});const link=document.createElement("a");link.href=URL.createObjectURL(blob);link.download="sermaye-kilit-raporu.csv";link.click();URL.revokeObjectURL(link.href)};
 const close=(symbol:string)=>async()=>{if(!window.confirm(`${symbol} açık paper pozisyonu güncel public fiyatla kapatılsın mı?`))return;setClosing(symbol);setMessage("");try{const result=await onClose(symbol);setMessage(result.message)}finally{setClosing(null)}};
 return <div className="space-y-4"><section className="grid grid-cols-2 gap-3 lg:grid-cols-4"><Stat title="BB-MFI kapanışı" value={String(report.trade_count||0)}/><Stat title="Sermaye kilit" value={String(report.capital_lock_count||0)} tone="text-yellow-300"/><Stat title="Kilit PnL" value={money(Number(report.capital_lock_net_pnl_try||0))} tone={tone}/><Stat title="Yeni M1 snapshot" value={String(report.activity_snapshot_count||0)} tone="text-sky-300"/></section><section className="card"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="eyebrow">ETİKET VE VERİ DURUMU</p><p className="mt-2 text-sm text-bunker-muted">Kilit: en az {report.label?.min_hold_hours ?? 4} saat açık ve en fazla %{report.label?.max_favorable_pct ?? .75} olumlu hareket. Bu ekran araştırma verisini değiştirmez.</p></div><button onClick={exportCsv} className="min-h-10 rounded-lg border border-neon-green/40 bg-neon-green/10 px-4 font-mono text-sm text-neon-green">CSV İNDİR</button></div><p className={`mt-2 font-mono text-xs ${report.status==="ready_for_research"?"text-neon-green":"text-yellow-300"}`}>{report.status==="ready_for_research"?"YETERLİ SNAPSHOT BİRİKİYOR":"VERİ TOPLANIYOR · Yeni açılan pozisyonlar M1 bağlamını otomatik kaydeder."}</p></section><section className="card"><p className="eyebrow">AÇIK PAPER POZİSYONLARI</p><p className="mt-2 text-xs text-bunker-muted">Kapatma, güncel public fiyatla işlem geçmişine yazılır; gerçek borsaya emir gönderilmez.</p>{message&&<p className="mt-2 font-mono text-xs text-yellow-300">{message}</p>}<div className="mt-3 table-scroll"><table className="data-table"><thead><tr><th>Sembol</th><th>Strateji</th><th>PnL</th><th>İşlem</th></tr></thead><tbody>{positions.map((position:any)=><tr key={position.symbol}><td><SymbolLink symbol={position.symbol} className="text-white hover:text-neon-green"/></td><td>{label(position.strategy||"")}</td><td className={Number(position.pnl_try||0)<0?"text-neon-red":"text-neon-green"}>{money(Number(position.pnl_try||0))}</td><td><button onClick={close(position.symbol)} disabled={closing!==null} className="rounded border border-red-400/50 bg-red-400/10 px-3 py-1 font-mono text-xs text-red-300 disabled:opacity-50">{closing===position.symbol?"KAPATILIYOR...":"MANUEL KAPAT"}</button></td></tr>)}</tbody></table></div>{!positions.length&&<p className="mt-3 text-sm text-bunker-muted">Açık paper pozisyonu yok.</p>}</section><section className="card"><p className="eyebrow">SON SERMAYE-KİLİT İŞLEMLERİ</p><div className="mt-3 table-scroll"><table className="data-table"><thead><tr><th>Sembol</th><th>Süre</th><th>MFE</th><th>MAE</th><th>PnL</th><th>Neden</th><th>Snapshot</th></tr></thead><tbody>{(report.recent||[]).map((row:any)=><tr key={row.trade_id||`${row.symbol}-${row.exit_time}`}><td><SymbolLink symbol={row.symbol} className="text-white hover:text-neon-green"/></td><td>{Math.round(Number(row.hold_seconds||0)/60)} dk</td><td>%{Number(row.max_favorable_pct||0).toFixed(2)}</td><td>%{Number(row.max_adverse_pct||0).toFixed(2)}</td><td className={Number(row.pnl)<0?"text-neon-red":"text-neon-green"}>{money(Number(row.pnl||0))}</td><td>{row.reason||"—"}</td><td className={row.activity_snapshot_present?"text-neon-green":"text-bunker-muted"}>{row.activity_snapshot_present?"VAR":"ESKİ KAYIT"}</td></tr>)}</tbody></table></div>{!(report.recent||[]).length&&<p className="mt-3 text-sm text-bunker-muted">Henüz bu etikette işlem yok.</p>}</section></div>
}
function TodayTab({trades}:{trades:Trade[]}){
 // gün sınırı: bileşen kurulduğunda yerel saat diliminde 00:00 (saniye)
 const [dayStart]=useState(()=>{const d=new Date();d.setHours(0,0,0,0);return Math.floor(d.getTime()/1000);});
 const todays=useMemo(()=>trades.filter(t=>(t.exit_time||t.entry_time)>=dayStart).sort((a,b)=>(b.exit_time||b.entry_time)-(a.exit_time||a.entry_time)),[trades,dayStart]);
 const wins=todays.filter(t=>t.pnl>0).length, losses=todays.filter(t=>t.pnl<0).length, flat=todays.length-wins-losses;
 const winRate=todays.length?(wins/todays.length)*100:0;
 const netPnl=todays.reduce((a,t)=>a+(t.pnl||0),0), commission=todays.reduce((a,t)=>a+(t.commission||0),0);
 const avgHold=todays.length?todays.reduce((a,t)=>a+(t.hold_seconds||0),0)/todays.length:0;
 const best=todays.reduce((a,t)=>!a||t.pnl>a.pnl?t:a,undefined as Trade|undefined);
 const worst=todays.reduce((a,t)=>!a||t.pnl<a.pnl?t:a,undefined as Trade|undefined);
 const byStrategy=useMemo(()=>{const m=new Map<string,{count:number;wins:number;pnl:number;pct:number}>();
   todays.forEach(t=>{const s=m.get(t.strategy)||{count:0,wins:0,pnl:0,pct:0};s.count++;if(t.pnl>0)s.wins++;s.pnl+=t.pnl||0;s.pct+=t.pnl_pct||0;m.set(t.strategy,s)});
   return[...m.entries()].sort((a,b)=>b[1].pnl-a[1].pnl)},[todays]);
 const exportCsv=()=>{const head=["Zaman","Sembol","Strateji","PnL","PnL %","Komisyon","Süre (dk)","Neden"];const esc=(v:any)=>`"${String(v??"").replaceAll('"','""')}"`;const body=todays.map(t=>[t.exit_time?new Date(t.exit_time*1000).toLocaleString("tr-TR"):"",t.symbol,label(t.strategy),t.pnl.toFixed(2),t.pnl_pct?.toFixed?.(2)??"", (t.commission||0).toFixed(2),Math.round((t.hold_seconds||0)/60),t.reason].map(esc).join(","));const blob=new Blob(["﻿"+[head.map(esc).join(","),...body].join("\n")],{type:"text/csv;charset=utf-8"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="bugun-islemler.csv";a.click();URL.revokeObjectURL(a.href)};
 return <div className="space-y-5">
  <div className="grid grid-cols-2 lg:grid-cols-6 gap-3">
   <Stat title="Bugünkü İşlem" value={String(todays.length)}/>
   <Stat title="Başarı" value={`%${winRate.toFixed(1)}`} tone={winRate>=50?"text-neon-green":todays.length?"text-neon-red":"text-white"}/>
   <Stat title="Kazanan / Kaybeden" value={`${wins}/${losses}`}/>
   <Stat title="Net PnL" value={money(netPnl)} tone={netPnl>=0?"text-neon-green":"text-neon-red"}/>
   <Stat title="Komisyon" value={money(commission)}/>
   <Stat title="Ort. Süre" value={`${Math.round(avgHold/60)} dk`}/>
  </div>
  {todays.length>0&&<div className="grid grid-cols-2 gap-3">
   <div className="card"><p className="eyebrow">EN İYİ İŞLEM</p><p className="mt-2 font-mono text-sm font-bold text-white"><SymbolLink symbol={best!.symbol} className="text-neon-green hover:text-white"/> · {money(best!.pnl)}</p></div>
   <div className="card"><p className="eyebrow">EN KÖTÜ İŞLEM</p><p className="mt-2 font-mono text-sm font-bold text-white"><SymbolLink symbol={worst!.symbol} className="hover:text-neon-green"/> · {money(worst!.pnl)}</p></div>
  </div>}
  <section className="card">
   <div className="flex flex-wrap items-center justify-between gap-3"><p className="eyebrow">STRATEJİ BAZLI BAŞARI</p><button onClick={exportCsv} className="min-h-9 rounded-lg border border-neon-green/40 bg-neon-green/10 px-4 font-mono text-xs text-neon-green">CSV İNDİR</button></div>
   <div className="table-scroll mt-3">
    <table className="data-table"><thead><tr>{["Strateji","İşlem","Kazanan","Başarı %","Net PnL","Ort. PnL %"].map(h=><th key={h}>{h}</th>)}</tr></thead>
    <tbody>{byStrategy.length?byStrategy.map(([strategy,s])=>{const wr=(s.wins/s.count)*100;const tone=s.pnl>=0?"text-neon-green":"text-neon-red";return<tr key={strategy}><td>{label(strategy)}</td><td>{s.count}</td><td className="text-neon-green">{s.wins}</td><td className={wr>=50?"text-neon-green":"text-neon-red"}>%{wr.toFixed(0)}</td><td className={tone}>{money(s.pnl)}</td><td className={tone}>{s.pct>=0?"+":""}{(s.pct/s.count).toFixed(2)}%</td></tr>}):<tr><td colSpan={6} className="text-center text-bunker-muted">Bugün kapanan işlem yok.</td></tr>}</tbody>
    </table>
   </div>
  </section>
  <section className="card">
   <p className="eyebrow">BUGÜN KAPANAN İŞLEMLER ({flat===0?"":`${flat} başabaş · `}{todays.length})</p>
   <div className="table-scroll mt-3">
    <table className="data-table"><thead><tr>{["Zaman","Sembol","Strateji","PnL","PnL %","Komisyon","Süre","Neden"].map(h=><th key={h}>{h}</th>)}</tr></thead>
    <tbody>{todays.map(t=><tr key={t.id}>
     <td>{new Date((t.exit_time||t.entry_time)*1000).toLocaleTimeString("tr-TR")}</td>
     <td><SymbolLink symbol={t.symbol} className="text-white hover:text-neon-green"/></td>
     <td>{label(t.strategy)}</td>
     <td className={t.pnl>=0?"text-neon-green":"text-neon-red"}>{money(t.pnl)}</td>
     <td className={t.pnl>=0?"text-neon-green":"text-neon-red"}>{t.pnl_pct>=0?"+":""}{(t.pnl_pct??0).toFixed(2)}%</td>
     <td>{money(t.commission||0)}</td>
     <td>{Math.round((t.hold_seconds||0)/60)} dk</td>
     <td className="max-w-56 truncate" title={t.reason||""}>{t.reason||"—"}</td>
    </tr>)}</tbody>
    </table>
   </div>
   {!todays.length&&<p className="mt-3 text-sm text-bunker-muted">Bugün henüz kapanan işlem yok.</p>}
  </section>
 </div>;
}
const MODULES = [
  ["/reports/forecasts", "LLM Tahmin Raporu", "Yorumların 5dk-4saat yön doğruluğu ve son sonuçları"],
  ["/system-health", "Sistem Sağlığı", "Market, WebSocket, DB ve LLM servis durumu"],
  ["/risk", "Risk Merkezi", "Pozisyon limiti, PnL ve risk bayrakları"],
  ["/strategy-comparison", "Strateji Karşılaştırma", "Komisyon sonrası strateji sonuçları"],
] as const;

export default function ReportsPage(){
 const[tab,setTab]=useState<"overview"|"today"|"signals"|"capital_lock"|"memory"|"forecasts"|"chat_predictions"|"velocity">("overview"); const[trades,setTrades]=useState<Trade[]>([]); const[signals,setSignals]=useState<any[]>([]); const[decisions,setDecisions]=useState<Decision[]>([]); const[complete,setComplete]=useState(true); const[risk,setRisk]=useState<any>(null); const[capitalLock,setCapitalLock]=useState<any>(null); const[positions,setPositions]=useState<any[]>([]); const[forecastReport,setForecastReport]=useState<any>(null); const[forecastLoading,setForecastLoading]=useState(true); const[forecastError,setForecastError]=useState(""); const[chatPredictions,setChatPredictions]=useState<any>(null); const[chatPredictionsLoading,setChatPredictionsLoading]=useState(true); const[chatPredictionsError,setChatPredictionsError]=useState(""); const[velocityReport,setVelocityReport]=useState<any>(null); const[velocityLoading,setVelocityLoading]=useState(true); const[velocityError,setVelocityError]=useState("");
 const loadVersion=useRef(0);
 const load=useCallback(()=>{const version=++loadVersion.current;return Promise.all([fetchAllPages<Trade>("/api/trades","trades"),fetchAllPages<any>("/api/signals","signals"),fetchAllPages<Decision>("/api/decisions","decisions"),apiRequest(`${API_BASE}/api/risk/summary`,{cache:"no-store"}).then(r=>r.ok?r.json():null),apiRequest(`${API_BASE}/api/reports/capital-lock`,{cache:"no-store"}).then(r=>r.ok?r.json():null),apiRequest(`${API_BASE}/api/positions`,{cache:"no-store"}).then(r=>r.ok?r.json():{positions:[]})]).then(([a,b,c,d,e,f])=>{if(version!==loadVersion.current)return;setTrades(a.rows);setSignals(b.rows);setDecisions(c.rows);setComplete(a.complete&&b.complete&&c.complete);setRisk(d);setCapitalLock(e);setPositions(f.positions||[])}).catch(()=>{if(version===loadVersion.current)setComplete(false)})},[]);
 const onLiveMessage=useCallback((message:any)=>{if(["signal","trade_updated","reset"].includes(message.type))load()},[load]); useLiveMessages(onLiveMessage); useEffect(()=>{load()},[load]);
 useEffect(()=>{setForecastLoading(true);setForecastError("");apiRequest(`${API_BASE}/api/reports/llm-chat-forecasts`,{cache:"no-store"}).then(async r=>{if(!r.ok){const body=await r.text();throw new Error(`HTTP ${r.status}${body?` · ${body.slice(0,120)}`:""}`)}return r.json()}).then(setForecastReport).catch(e=>{setForecastReport(null);setForecastError(e instanceof Error?e.message:"Bilinmeyen API hatası")}).finally(()=>setForecastLoading(false))},[]);
 useEffect(()=>{setChatPredictionsLoading(true);setChatPredictionsError("");apiRequest(`${API_BASE}/api/reports/chat-predictions?limit=60`,{cache:"no-store"}).then(async r=>{if(!r.ok){const body=await r.text();throw new Error(`HTTP ${r.status}${body?` · ${body.slice(0,120)}`:""}`)}return r.json()}).then(setChatPredictions).catch(e=>{setChatPredictions(null);setChatPredictionsError(e instanceof Error?e.message:"Bilinmeyen API hatası")}).finally(()=>setChatPredictionsLoading(false))},[]);
 useEffect(()=>{setVelocityLoading(true);setVelocityError("");apiRequest(`${API_BASE}/api/reports/velocity?limit=60`,{cache:"no-store"}).then(async r=>{if(!r.ok){const body=await r.text();throw new Error(`HTTP ${r.status}${body?` · ${body.slice(0,120)}`:""}`)}return r.json()}).then(setVelocityReport).catch(e=>{setVelocityReport(null);setVelocityError(e instanceof Error?e.message:"Bilinmeyen API hatası")}).finally(()=>setVelocityLoading(false))},[]);
 const analysisRows=useMemo(()=>{const rows=[...signals.map(item=>({...item,uiKey:`signal:${item.id}`})),...decisions.map(item=>({...item,action:item.decision,uiKey:`decision:${item.id}`}))];const seen=new Set<string>();return rows.filter(item=>{const tradeId=item.trade_id||item.metadata?.trade_id;const key=tradeId?`${item.action}|${tradeId}`:item.uiKey;if(seen.has(key))return false;seen.add(key);return true})},[signals,decisions]);
 const pnl=risk?.realized_pnl??trades.reduce((a,t)=>a+(t.pnl||0),0); const timeout=trades.filter(t=>{const reason=String(t.reason||"").toLowerCase();return ["time","timeout","max_hold","early_failure","stale_position"].some(token=>reason.includes(token))}).length;
 const closePosition=useCallback(async(symbol:string)=>{try{const response=await apiRequest(`${API_BASE}/api/positions/${encodeURIComponent(symbol)}/close`,{method:"POST"});const data=await response.json();if(data.ok)await load();return {ok:Boolean(data.ok),message:data.message||(data.ok?"Pozisyon kapatıldı.":"Pozisyon kapatılamadı.")}}catch{return {ok:false,message:"Pozisyon kapatılamadı."}}},[load]);
 return <main className="page-shell"><div className="page-heading"><p className="eyebrow">PERFORMANS MERKEZİ</p><h1>Raporlar</h1><p className="text-bunker-muted">İşlem kalitesi ve kayıt kapsamı. Uzman modüll tek kaynak sayfalarına taşındı.</p></div><nav className="section-tabs" aria-label="Rapor sekmeleri">{[["today","Bugün"],["overview","Genel Rapor"],["signals","Sinyal ve Karar Analizi"],["capital_lock","Sermaye Kilit"],["chat_predictions","M5/M15 Tahmin Başarı"],["velocity","Hız Avcısı (%2/5dk)"],["forecasts","LLM Chat Tahminleri"],["memory","LLM Hafızası"]].map(([k,l])=><button key={k} onClick={()=>setTab(k as any)} className={tab===k?"active":""}>{l}</button>)}</nav>{tab==="today"?<TodayTab trades={trades}/>:tab==="signals"?<DecisionTab decisions={analysisRows} trades={trades}/>:tab==="capital_lock"?<CapitalLockTab report={capitalLock} positions={positions} onClose={closePosition}/>:tab==="chat_predictions"?<ChatPredictionsTab report={chatPredictions} loading={chatPredictionsLoading} error={chatPredictionsError}/>:tab==="velocity"?<VelocityTab report={velocityReport} loading={velocityLoading} error={velocityError}/>:tab==="forecasts"?<ForecastTab report={forecastReport} loading={forecastLoading} error={forecastError}/>:tab==="memory"?<MemoryTab/>:<div className="space-y-5"><div className="grid grid-cols-2 lg:grid-cols-4 gap-3"><Stat title="İşlem" value={String(trades.length)}/><Stat title="Net PnL" value={money(pnl)} tone={pnl>=0?"text-neon-green":"text-neon-red"}/><Stat title="Timeout" value={String(timeout)} tone="text-neon-red"/><Stat title="Sinyal" value={String(signals.length)}/></div><div className={`card ${complete?"border-neon-green/20 bg-neon-green/5":"border-yellow-400/20 bg-yellow-400/5"}`}><p className={`eyebrow ${complete?"text-neon-green":"text-yellow-300"}`}>VERİ KAPSAMI</p><p className="text-sm mt-2">{complete?"Mevcut offset sayfaları yüklendi; canlı insert sırasında snapshot garantisi için backend keyset cursor gerekir.":"Kayıt sınırına ulaşıldı veya bir sayfa alınamadı; metrikler eksik olabilir."}</p></div><div className="grid md:grid-cols-3 gap-3">{MODULES.map(([href,title,description])=><Link key={href} href={href} className="card transition-colors hover:border-neon-green/40"><p className="font-mono font-bold text-white">{title}</p><p className="mt-2 text-sm text-bunker-muted">{description}</p><span className="mt-3 inline-block font-mono text-xs text-neon-green">MODÜLÜ AÇ →</span></Link>)}</div><div className="card"><p className="eyebrow">SON KAPANAN İŞLEMLER</p><div className="table-scroll mt-3"><table className="data-table"><thead><tr><th>Sembol</th><th>Strateji</th><th>PnL</th><th>Komisyon</th><th>Süre</th><th>Neden</th></tr></thead><tbody>{trades.slice(0,12).map(t=><tr key={t.id}><td><SymbolLink symbol={t.symbol} className="text-white hover:text-neon-green" /></td><td>{label(t.strategy)}</td><td className={t.pnl>=0?"text-neon-green":"text-neon-red"}>{money(t.pnl)}</td><td>{money(t.commission||0)}</td><td>{Math.round((t.hold_seconds||0)/60)} dk</td><td>{t.reason||"—"}</td></tr>)}</tbody></table></div></div></div>}</main>
}
