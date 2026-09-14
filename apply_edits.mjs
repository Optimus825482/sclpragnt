// GEÇİCİ audit-fix scripti. Uygulama:
//   node D:\scalperagent_v4\apply_edits.mjs
//   cd D:\scalperagent_v4\frontend && npx tsc --noEmit
// Edits are idempotent-safe guarded by exact old-string match; script deletes
// itself and all scratch files after success.
import { readFileSync, writeFileSync, unlinkSync } from "fs";

const edits = [
  {
    file: "frontend/app/lib/api.ts",
    old: `export function apiRequest(input: RequestInfo | URL, init?: RequestInit) {
  const method = String(init?.method || "GET").toUpperCase();
  const merged: RequestInit = { credentials: "include", ...init };
  if ((method === "GET" || method === "HEAD") && merged.cache === undefined) {
    merged.cache = "no-store";
  }
  return fetch(input, merged).then((response) => {
    if (response.status === 401 && typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("scalper:auth-expired"));
    }
    return response;
  });
}`,
    neu: `export function apiRequest(input: RequestInfo | URL, init?: RequestInit) {
  const method = String(init?.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
  // Audit: başarısız login POST'u auth-expired yayınlamamalı (login ekranında
  // yanlış "Oturum süresi doldu" flaşı), o yüzden URL de ayrıştırılır.
  const url = input instanceof Request ? input.url : String(input);
  const merged: RequestInit = { credentials: "include", ...init };
  if ((method === "GET" || method === "HEAD") && merged.cache === undefined) {
    merged.cache = "no-store";
  }
  return fetch(input, merged).then((response) => {
    const isLoginPost = method === "POST" && url.includes("/auth/login");
    if (response.status === 401 && typeof window !== "undefined" && !isLoginPost) {
      window.dispatchEvent(new CustomEvent("scalper:auth-expired"));
    }
    return response;
  });
}`,
  },
  {
    file: "frontend/app/settings/page.tsx",
    old: `    apiRequest(\`\${API_BASE}/api/config\`)
      .then((r) => r.json())
      .then((d) => { setCfg(d); setDraft(d); })
      .catch(() => setError(\`Backend'e bağlanılamadı (\${API_BASE})\`));
    apiRequest(\`\${API_BASE}/api/market-symbols\`)
      .then((r) => r.json())
      .then((d) => setMarketSymbols(d.symbols || []))
      .catch(() => setError("Binance TR sembolleri alınamadı"));
    apiRequest(\`\${API_BASE}/api/llm/config\`).then((r) => r.json()).then(setLlm).catch(() => undefined);`,
    neu: `    // Audit: unchecked r.json() zincirleri 500'de hata gövdesini state'e
    // yazıyordu (crash). Artık res.ok kontrolü + mevcut görünür hata şeridi.
    apiRequest(\`\${API_BASE}/api/config\`)
      .then(async (r) => {
        if (!r.ok) throw new Error(\`Ayar verisi alınamadı (HTTP \${r.status})\`);
        return r.json();
      })
      .then((d) => { setCfg(d); setDraft(d); })
      .catch((e) => setError(e instanceof Error ? e.message : \`Backend'e bağlanılamadı (\${API_BASE})\`));
    apiRequest(\`\${API_BASE}/api/market-symbols\`)
      .then(async (r) => {
        if (!r.ok) throw new Error(\`Sembol verisi alınamadı (HTTP \${r.status})\`);
        return r.json();
      })
      .then((d) => setMarketSymbols(d.symbols || []))
      .catch((e) => setError(e instanceof Error ? e.message : "Binance TR sembolleri alınamadı"));
    apiRequest(\`\${API_BASE}/api/llm/config\`)
      .then(async (r) => {
        if (!r.ok) throw new Error(\`LLM ayar verisi alınamadı (HTTP \${r.status})\`);
        return r.json();
      })
      .then(setLlm)
      .catch((e) => setError(e instanceof Error ? e.message : "LLM ayar verisi alınamadı"));`,
  },
  {
    file: "frontend/app/settings/page.tsx",
    old: `  const saveMonitoringMinScore = async () => {
    const val = Number(monitoringMinScoreInput);
    if (!Number.isFinite(val) || val < 0 || val > 100) { setError("Monitoring min skor 0-100 arası olmalı"); return; }`,
    neu: `  const saveMonitoringMinScore = async () => {
    // Audit: boş input Number("") === 0 → 0 kaydediliyordu; boşluk da reddedilir.
    const raw = monitoringMinScoreInput.trim();
    const val = Number(monitoringMinScoreInput);
    if (raw === "" || !Number.isFinite(val) || val < 0 || val > 100) { setError("Min skor 0-100 arasında olmalı."); return; }`,
  },
  {
    file: "frontend/app/settings/page.tsx",
    old: `  const loadMlStatus = () => apiRequest(\`\${API_BASE}/api/ml/status\`, { cache: "no-store" })
    .then((r) => r.json()).then(setMlStatus).catch(() => undefined);`,
    neu: `  const loadMlStatus = () => apiRequest(\`\${API_BASE}/api/ml/status\`, { cache: "no-store" })
    .then(async (r) => {
      if (!r.ok) throw new Error(\`ML durum verisi alınamadı (HTTP \${r.status})\`);
      return r.json();
    })
    .then(setMlStatus)
    .catch((e) => setMlError(e instanceof Error ? e.message : "ML durum verisi alınamadı"));`,
  },
  {
    file: "frontend/app/settings/page.tsx",
    old: `{llm.providers.map((p:any)=><option key={p.id} value={p.id}>{p.name}</option>)}`,
    neu: `{(llm.providers ?? []).map((p:any)=><option key={p.id} value={p.id}>{p.name}</option>)}`,
  },
  {
    file: "frontend/app/settings/page.tsx",
    old: `{llm.models.map((m:any)=><option key={m.id} value={m.id}>{m.name}</option>)}`,
    neu: `{(llm.models ?? []).map((m:any)=><option key={m.id} value={m.id}>{m.name}</option>)}`,
  },
  {
    file: "frontend/app/settings/page.tsx",
    old: `                    ? \`Son eğitim: \${new Date(toMs(mlStatus.artifact.created_at)).toLocaleString("tr-TR")} · \${mlStatus.artifact.sample_count.toLocaleString("tr-TR")} örnek · \${mlStatus.artifact.symbol_count} sembol · \${mlStatus.artifact.journal_sample_count} journal örneği\``,
    neu: `                    // Audit: eksik alan .toLocaleString'de crash ediyordu → "—" fallback.
                    ? \`Son eğitim: \${new Date(toMs(mlStatus.artifact.created_at)).toLocaleString("tr-TR")} · \${mlStatus.artifact.sample_count?.toLocaleString?.("tr-TR") ?? "—"} örnek · \${mlStatus.artifact.symbol_count ?? "—"} sembol · \${mlStatus.artifact.journal_sample_count ?? "—"} journal örneği\``,
  },
  {
    file: "frontend/app/reports/page.tsx",
    old: `      } else {
        setError(nt.detail || "Radar tespitleri alinamadi");
      }
    } catch {
      setError("Radar tespitleri alinamadi");
    } finally {
      setLoading(false);
    }
  }, [day]);`,
    neu: `      } else {
        // Audit: başarısız gün değişiminde önceki günün satırları "seçili gün"
        // gibi kalıyordu → hata gösterilirken liste temizlenir.
        setNotifications([]);
        setBreakdown(null);
        setOverall(null);
        setError(nt.detail || "Radar tespitleri alinamadi");
      }
    } catch {
      setNotifications([]);
      setBreakdown(null);
      setOverall(null);
      setError("Radar tespitleri alinamadi");
    } finally {
      setLoading(false);
    }
  }, [day]);`,
  },
  {
    file: "frontend/app/charts/page.tsx",
    old: `    const [forecast, setForecast] = useState<any>(null);
    const [forecastHistory, setForecastHistory] = useState<any>(null);
    const [forecastLoading, setForecastLoading] = useState(false);`,
    neu: `    const [forecast, setForecast] = useState<any>(null);
    const [forecastHistory, setForecastHistory] = useState<any>(null);
    const [forecastLoading, setForecastLoading] = useState(false);
    // Audit: "backend down" ile "veri yok" ayrımı için panel başına görünür
    // hata şeridi + yeniden dene; portföy şeridi için bayat göstergesi.
    const [forecastError, setForecastError] = useState<string | null>(null);
    const [monitorNotifError, setMonitorNotifError] = useState<string | null>(null);
    const [portfolioStale, setPortfolioStale] = useState(false);`,
  },
  {
    file: "frontend/app/charts/page.tsx",
    old: `    const loadForecast = useCallback(async (fresh: boolean) => {
        if (!symbol) { setForecast(null); return; }
        setForecastLoading(true);
        try {
            const res = await apiRequest(\`\${API}/\${encodeURIComponent(symbol)}/forecast\`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ timeframe: interval, fresh })
            });
            const data = await res.json();
            if (res.ok) setForecast(data);
        } catch {
            setForecast(null);
        } finally {
            setForecastLoading(false);
        }
    }, [symbol, interval]);

    const loadForecastHistory = useCallback(async () => {
        if (!symbol) { setForecastHistory(null); return; }
        try {
            const res = await apiRequest(\`\${API}/\${encodeURIComponent(symbol)}/forecast-history\`);
            const data = await res.json();
            if (res.ok) setForecastHistory(data);
        } catch {
            setForecastHistory(null);
        }
    }, [symbol]);`,
    neu: `    const loadForecast = useCallback(async (fresh: boolean) => {
        if (!symbol) { setForecast(null); return; }
        setForecastLoading(true);
        setForecastError(null);
        try {
            const res = await apiRequest(\`\${API}/\${encodeURIComponent(symbol)}/forecast\`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ timeframe: interval, fresh })
            });
            const data = await res.json();
            if (res.ok) setForecast(data);
            else setForecastError("Veri alınamadı (bağlantı hatası) — panel bayat olabilir");
        } catch {
            setForecast(null);
            setForecastError("Veri alınamadı (bağlantı hatası) — panel bayat olabilir");
        } finally {
            setForecastLoading(false);
        }
    }, [symbol, interval]);

    const loadForecastHistory = useCallback(async () => {
        if (!symbol) { setForecastHistory(null); return; }
        try {
            const res = await apiRequest(\`\${API}/\${encodeURIComponent(symbol)}/forecast-history\`);
            const data = await res.json();
            if (res.ok) setForecastHistory(data);
            else setForecastError("Veri alınamadı (bağlantı hatası) — panel bayat olabilir");
        } catch {
            setForecastHistory(null);
            setForecastError("Veri alınamadı (bağlantı hatası) — panel bayat olabilir");
        }
    }, [symbol]);`,
  },
  {
    file: "frontend/app/charts/page.tsx",
    old: `    const loadMonitorNotif = useCallback(async () => {
        if (!symbol) return;
        try {
            const res = await apiRequest(\`\${API_BASE}/api/monitoring/active-notification/\${encodeURIComponent(symbol)}\`, { cache: "no-store" });
            const data = await res.json();
            setMonitorNotif(res.ok && data?.active ? data : null);
        } catch {
            setMonitorNotif(null);
        }
    }, [symbol]);
    useEffect(() => {
        setMonitorNotif(null);
        setMonitorRemainingSec(null);
        loadMonitorNotif();
        const t = setInterval(loadMonitorNotif, 15_000);
        return () => clearInterval(t);
    }, [loadMonitorNotif]);`,
    neu: `    const loadMonitorNotif = useCallback(async () => {
        if (!symbol) return;
        try {
            const res = await apiRequest(\`\${API_BASE}/api/monitoring/active-notification/\${encodeURIComponent(symbol)}\`, { cache: "no-store" });
            const data = await res.json();
            if (!res.ok) setMonitorNotifError("Veri alınamadı (bağlantı hatası) — panel bayat olabilir");
            setMonitorNotif(res.ok && data?.active ? data : null);
        } catch {
            setMonitorNotif(null);
            setMonitorNotifError("Veri alınamadı (bağlantı hatası) — panel bayat olabilir");
        }
    }, [symbol]);
    useEffect(() => {
        setMonitorNotif(null);
        setMonitorRemainingSec(null);
        setMonitorNotifError(null);
        loadMonitorNotif();
        const t = setInterval(loadMonitorNotif, 15_000);
        return () => clearInterval(t);
    }, [loadMonitorNotif]);`,
  },
  {
    file: "frontend/app/charts/page.tsx",
    old: `    const loadPortfolioSummary = useCallback(async () => {
        try {
            const response = await apiRequest(\`\${API_BASE}/api/portfolio/summary\`);
            const result = await response.json();
            if (result.portfolio && Object.keys(result.portfolio).length) setLivePortfolio(result.portfolio as LivePortfolio);
            if (result.metrics) setPortfolioMetrics(result.metrics as PortfolioMetrics);
        } catch { /* özet için portföy metrikleri geçici olarak kullanılamıyor */ }
    }, []);`,
    neu: `    const loadPortfolioSummary = useCallback(async () => {
        try {
            const response = await apiRequest(\`\${API_BASE}/api/portfolio/summary\`);
            if (!response.ok) { setPortfolioStale(true); return; }
            const result = await response.json();
            if (result.portfolio && Object.keys(result.portfolio).length) setLivePortfolio(result.portfolio as LivePortfolio);
            if (result.metrics) setPortfolioMetrics(result.metrics as PortfolioMetrics);
            setPortfolioStale(false);
        } catch {
            // Audit: sessiz kalma — şerit yanında "bayat" göstergesi gösterilir.
            setPortfolioStale(true);
        }
    }, []);`,
  },
  {
    file: "frontend/app/charts/page.tsx",
    old: `            if (Array.isArray(message.data?.auto_paper_positions) && message.data.auto_paper_positions.length >= 0) {
                const ap = message.data.auto_paper_positions.map((t: any) => ({
                    id: Number(t.auto_paper_id || 0),
                    symbol: t.symbol,
                    entry_price: Number(t.entry || 0),
                    current_price: Number(t.current || 0),
                    quantity: Number(t.quantity || 0),
                    take_profit: t.take_profit,
                    stop_loss: t.stop,
                    entry_time: t.entry_time,
                }));
                if (ap.some((a: any) => a.id > 0)) setAutoPaperPositions(ap);
            }`,
    neu: `            // Audit: boş dizi geldiğinde state atlanıyordu → kapanan pozisyonlar
            // listede kalıyordu. Dizi taşındığı sürece AYNI şekilde uygulanır.
            if (Array.isArray(message.data?.auto_paper_positions)) {
                const ap = message.data.auto_paper_positions.map((t: any) => ({
                    id: Number(t.auto_paper_id || 0),
                    symbol: t.symbol,
                    entry_price: Number(t.entry || 0),
                    current_price: Number(t.current || 0),
                    quantity: Number(t.quantity || 0),
                    take_profit: t.take_profit,
                    stop_loss: t.stop,
                    entry_time: t.entry_time,
                }));
                setAutoPaperPositions(ap);
            }`,
  },
  {
    file: "frontend/app/charts/page.tsx",
    old: `            <section aria-label="Portföy özeti" className="grid grid-cols-2 gap-2 rounded-xl border border-bunker-800 bg-bunker-950/80 p-3 sm:grid-cols-6">`,
    neu: `            {portfolioStale && (
                <div className="flex items-center gap-2 rounded-lg border border-yellow-400/40 bg-yellow-400/5 px-3 py-1.5">
                    <span className="font-mono text-[11px] text-yellow-300">Portföy özeti güncellenemedi (bayat)</span>
                    <button type="button" onClick={() => { setPortfolioStale(false); loadPortfolioSummary(); }} className="rounded border border-bunker-700 px-2 py-0.5 font-mono text-[11px] text-bunker-muted hover:text-white">YENİDEN DENE</button>
                </div>
            )}
            <section aria-label="Portföy özeti" className="grid grid-cols-2 gap-2 rounded-xl border border-bunker-800 bg-bunker-950/80 p-3 sm:grid-cols-6">`,
  },
  {
    file: "frontend/app/charts/page.tsx",
    old: `                    {forecastLoading ? (
                        <p className="mt-2 font-mono text-xs text-neon-green animate-pulse">hedef hesaplanıyor...</p>
                    ) : forecast?.forecasts?.length ? (`,
    neu: `                    {forecastError && (
                        <div className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border border-yellow-400/40 bg-yellow-400/5 px-2 py-1.5">
                            <span className="font-mono text-[11px] text-yellow-300">{forecastError}</span>
                            <button type="button" onClick={() => { setForecastError(null); loadForecast(false); loadForecastHistory(); }} className="rounded border border-bunker-700 px-2 py-0.5 font-mono text-[11px] text-bunker-muted hover:text-white">YENİDEN DENE</button>
                        </div>
                    )}
                    {forecastLoading ? (
                        <p className="mt-2 font-mono text-xs text-neon-green animate-pulse">hedef hesaplanıyor...</p>
                    ) : forecast?.forecasts?.length ? (`,
  },
  {
    file: "frontend/app/charts/page.tsx",
    old: `            {/* Üst tahmin paneli: ML model çıktısı (LLM yok) + geçmiş başarı + yenile —
                aktif radar bildirimi yokken gösterilir */}
            {!monitorNotif?.active && (`,
    neu: `            {/* Audit: bildirim paneli yalnız aktifken gösterildiğinden, yükleme
                hatası şeridi ML tahmin panelinin üstünde durur */}
            {!monitorNotif?.active && monitorNotifError && (
                <div className="flex flex-wrap items-center gap-2 rounded-lg border border-yellow-400/40 bg-yellow-400/5 px-3 py-2">
                    <span className="font-mono text-[11px] text-yellow-300">RADAR BİLDİRİMİ: {monitorNotifError}</span>
                    <button type="button" onClick={() => { setMonitorNotifError(null); loadMonitorNotif(); }} className="rounded border border-bunker-700 px-2 py-0.5 font-mono text-[11px] text-bunker-muted hover:text-white">YENİDEN DENE</button>
                </div>
            )}

            {/* Üst tahmin paneli: ML model çıktısı (LLM yok) + geçmiş başarı + yenile —
                aktif radar bildirimi yokken gösterilir */}
            {!monitorNotif?.active && (`,
  },
  {
    file: "frontend/app/components/AuthGate.tsx",
    old: `  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const response = await apiRequest(\`\${API_BASE}/api/auth/status\`, { cache: "no-store" });
    if (!response.ok) throw new Error(\`Kimlik doğrulama durumu alınamadı (\${response.status})\`);
    const next = await response.json() as AuthStatus;
    setStatus(next);
    return next;
  }, []);

  useEffect(() => {
    const expired = () => { setStatus((current) => current ? { ...current, authenticated: false } : current); setError("Oturum süresi doldu. Yeniden giriş yapın."); };
    window.addEventListener("scalper:auth-expired", expired);
    refresh().catch((reason) => setError(reason instanceof Error ? reason.message : "Backend bağlantısı kurulamadı"));
    return () => window.removeEventListener("scalper:auth-expired", expired);
  }, [refresh]);`,
    neu: `  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Audit: /api/auth/status AĞ hatası (TypeError "Failed to fetch") ile
  // başarısız olursa sayfadan çıkış yolu yoktu → YENİDEN DENE butonu eklenir.
  const [statusNetworkError, setStatusNetworkError] = useState(false);

  const refresh = useCallback(async () => {
    const response = await apiRequest(\`\${API_BASE}/api/auth/status\`, { cache: "no-store" });
    if (!response.ok) throw new Error(\`Kimlik doğrulama durumu alınamadı (\${response.status})\`);
    const next = await response.json() as AuthStatus;
    setStatus(next);
    return next;
  }, []);

  useEffect(() => {
    const expired = () => { setStatus((current) => current ? { ...current, authenticated: false } : current); setError("Oturum süresi doldu. Yeniden giriş yapın."); };
    window.addEventListener("scalper:auth-expired", expired);
    refresh().catch((reason) => {
      setStatusNetworkError(reason instanceof TypeError);
      setError(reason instanceof Error ? reason.message : "Backend bağlantısı kurulamadı");
    });
    return () => window.removeEventListener("scalper:auth-expired", expired);
  }, [refresh]);

  const retryStatusCheck = () => {
    setError("");
    refresh().catch((reason) => {
      setStatusNetworkError(reason instanceof TypeError);
      setError(reason instanceof Error ? reason.message : "Backend bağlantısı kurulamadı");
    });
  };`,
  },
  {
    file: "frontend/app/components/AuthGate.tsx",
    old: `      {error && <p role="alert" className="mt-4 text-sm text-neon-red">{error}</p>}`,
    neu: `      {error && <p role="alert" className="mt-4 text-sm text-neon-red">{error}</p>}
      {statusNetworkError && <button type="button" onClick={retryStatusCheck} className="mt-2 ui-button ui-button-secondary">YENİDEN DENE</button>}`,
  },
  {
    file: "frontend/app/monitoring/page.tsx",
    old: `  const stateReqIdRef = useRef(0);
  const stateInFlightRef = useRef(false);
  const scanInFlightRef = useRef(false);`,
    neu: `  const stateReqIdRef = useRef(0);
  const stateInFlightRef = useRef(false);
  const scanInFlightRef = useRef(false);
  // Audit: loadHistory da loadState ile AYNI istek-nesli korumasını taşır.
  const historyReqIdRef = useRef(0);`,
  },
  {
    file: "frontend/app/monitoring/page.tsx",
    old: `  const loadHistory = useCallback(async (signal?: AbortSignal) => {
    try {
      const res = await apiRequest(\`\${API_BASE}/api/monitoring/notifications\`, { cache: "no-store", signal });
      if (!res.ok) throw new HttpStatusError(res.status);
      const data = await res.json();
      if (!mountedRef.current) return;
      const list: NotificationRow[] = Array.isArray(data?.history) ? data.history : [];
      setHistoryRows(list.slice(0, 10));
      setHistoryError(null);
    } catch (err) {
      if (isAbortError(err) || !mountedRef.current) return;
      setHistoryError(humanizeError(err));
    }
  }, []);`,
    neu: `  const loadHistory = useCallback(async (signal?: AbortSignal) => {
    const reqId = ++historyReqIdRef.current;
    try {
      const res = await apiRequest(\`\${API_BASE}/api/monitoring/notifications\`, { cache: "no-store", signal });
      if (reqId !== historyReqIdRef.current || !mountedRef.current) return;
      if (!res.ok) throw new HttpStatusError(res.status);
      const data = await res.json();
      if (reqId !== historyReqIdRef.current || !mountedRef.current) return;
      const list: NotificationRow[] = Array.isArray(data?.history) ? data.history : [];
      setHistoryRows(list.slice(0, 10));
      setHistoryError(null);
    } catch (err) {
      if (isAbortError(err) || !mountedRef.current || reqId !== historyReqIdRef.current) return;
      setHistoryError(humanizeError(err));
    }
  }, []);`,
  },
];

let failures = 0;
for (const edit of edits) {
  const path = `D:/scalperagent_v4/${edit.file}`;
  const src = readFileSync(path, "utf8");
  if (src.includes(edit.neu)) { console.log(`SKIP (already applied) ${edit.file}`); continue; }
  if (!src.includes(edit.old)) {
    console.error(`NOT FOUND in ${edit.file}: ${edit.old.slice(0, 80).replace(/\n/g, "\\n")}...`);
    failures += 1;
    continue;
  }
  writeFileSync(path, src.replace(edit.old, edit.neu));
  console.log(`OK ${edit.file}`);
}
if (failures > 0) process.exit(1);
// Scratch dosyalarını temizle (bu script dahil).
for (const scratch of [
  "apply_edits.mjs", "apply_edits.cmd", "apply_edits_package.json",
  "cleanup_list.txt", "run_steps.txt", "EXECUTE.txt", "RUNME.txt",
]) {
  try { unlinkSync(`D:/scalperagent_v4/${scratch}`); } catch { /* zaten yok */ }
}
console.log("ALL EDITS APPLIED — scratch files removed. Now run: cd frontend && npx tsc --noEmit");