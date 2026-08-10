"use client";

import { FormEvent, ReactNode, useCallback, useEffect, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";

type AuthStatus = { configured: boolean; authenticated: boolean };

export default function AuthGate({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const response = await apiRequest(`${API_BASE}/api/auth/status`, { cache: "no-store" });
    if (!response.ok) throw new Error(`Kimlik doğrulama durumu alınamadı (${response.status})`);
    const next = await response.json() as AuthStatus;
    setStatus(next);
    return next;
  }, []);

  useEffect(() => {
    const expired = () => { setStatus((current) => current ? { ...current, authenticated: false } : current); setError("Oturum süresi doldu. Yeniden giriş yapın."); };
    window.addEventListener("scalper:auth-expired", expired);
    refresh().catch((reason) => setError(reason instanceof Error ? reason.message : "Backend bağlantısı kurulamadı"));
    return () => window.removeEventListener("scalper:auth-expired", expired);
  }, [refresh]);

  const login = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const response = await apiRequest(`${API_BASE}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password }) });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "Oturum açılamadı");
      const next = await refresh();
      if (!next.authenticated) throw new Error("Oturum cookie'si doğrulanamadı. HTTP geliştirmede SCALPER_COOKIE_SECURE=0 kullanın.");
      setPassword("");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Oturum açılamadı"); }
    finally { setBusy(false); }
  };

  const logout = async () => {
    setBusy(true);
    try { await apiRequest(`${API_BASE}/api/auth/logout`, { method: "POST" }); }
    finally { setStatus((current) => current ? { ...current, authenticated: false } : current); setBusy(false); }
  };

  if (!status?.authenticated) return <main className="grid min-h-screen place-items-center bg-bunker-950 p-5">
    <section className="w-full max-w-md rounded-xl border border-bunker-700 bg-bunker-900 p-6 shadow-2xl">
      <p className="eyebrow">SCALPERAGENT · PAPER ONLY</p>
      <h1 className="mt-2 font-mono text-2xl font-bold text-white">Yönetici oturumu</h1>
      {!status && !error && <p className="mt-4 font-mono text-sm text-bunker-muted">Backend doğrulanıyor…</p>}
      {status && !status.configured && <div className="mt-5 rounded-lg border border-neon-red/40 bg-neon-red/10 p-4 text-sm text-neon-red"><strong>Kimlik doğrulama yapılandırılmamış.</strong><p className="mt-2 text-bunker-muted">Backend için SCALPER_ADMIN_PASSWORD ve SCALPER_SESSION_SECRET değerlerini tanımlayın.</p></div>}
      {status?.configured && <form onSubmit={login} className="mt-5 space-y-3"><label className="block"><span className="eyebrow">YÖNETİCİ PAROLASI</span><input type="password" autoComplete="current-password" required autoFocus value={password} onChange={(event) => setPassword(event.target.value)} className="input mt-2 w-full" /></label><button disabled={busy} className="ui-button ui-button-primary w-full">{busy ? "DOĞRULANIYOR…" : "OTURUM AÇ"}</button></form>}
      {error && <p role="alert" className="mt-4 text-sm text-neon-red">{error}</p>}
    </section>
  </main>;

  return <><button type="button" onClick={logout} disabled={busy} className="fixed bottom-4 right-4 z-[90] rounded-lg border border-bunker-700 bg-bunker-950/90 px-3 py-2 font-mono text-[11px] text-bunker-muted shadow-lg hover:border-neon-red/50 hover:text-neon-red">OTURUMU KAPAT</button>{children}</>;
}
