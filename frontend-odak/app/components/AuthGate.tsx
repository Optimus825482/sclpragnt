"use client";

import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import { AuthContext } from "../lib/auth";
import type { AuthStatus } from "../lib/types";
import { Button } from "./ui";

/** Oturum kapısı — koyu tema AuthGate ile aynı akış, açık tema görünümü.
 *  Push/izni/uyarı modalları bu sade arayüze DAHİL EDİLMEDİ (kapsam dışı). */
export default function AuthGate({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [networkError, setNetworkError] = useState(false);

  const refresh = useCallback(async () => {
    const response = await apiRequest(`${API_BASE}/api/auth/status`, { cache: "no-store" });
    // 5xx neredeyse her zaman "proxy hedefi (backend) erişilemez" demektir —
    // Next rewrite, backend kapalıyken 502/500 döndürür. Bunu ağ hatası sayıp
    // YENİDEN DENE akışına alıyoruz (yalnız TypeError değil).
    if (response.status >= 500) {
      throw new Error(
        "Backend'e ulaşılamadı (proxy " + response.status + "). Backend çalışıyor mu? (port 8004)",
      );
    }
    if (!response.ok) throw new Error(`Kimlik durumu alınamadı (${response.status})`);
    const next = (await response.json()) as AuthStatus;
    setStatus(next);
    return next;
  }, []);

  // Ağ hatası (TypeError) VEYA proxy 5xx → yeniden denenebilir durum.
  const markRetryable = (reason: unknown) => {
    const message = reason instanceof Error ? reason.message : "Backend bağlantısı kurulamadı";
    setNetworkError(reason instanceof TypeError || /ulaşılamadı|proxy \d{3}/.test(message));
    setError(message);
  };

  useEffect(() => {
    const expired = () => {
      setStatus((cur) => (cur ? { ...cur, authenticated: false } : cur));
      setError("Oturum süresi doldu. Yeniden giriş yapın.");
    };
    window.addEventListener("odak:auth-expired", expired);
    refresh().catch(markRetryable);
    return () => window.removeEventListener("odak:auth-expired", expired);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh]);

  const login = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await apiRequest(`${API_BASE}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "Oturum açılamadı");
      const next = await refresh();
      if (!next.authenticated) throw new Error("Oturum cookie'si doğrulanamadı.");
      setUsername("");
      setPassword("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Oturum açılamadı");
    } finally {
      setBusy(false);
    }
  };

  const logout = async () => {
    setBusy(true);
    try {
      await apiRequest(`${API_BASE}/api/auth/logout`, { method: "POST" });
    } finally {
      try {
        setStatus(await refresh());
      } catch {
        setStatus((cur) => (cur ? { ...cur, authenticated: false } : cur));
      }
      setBusy(false);
    }
  };

  const value = useMemo(
    () => ({ username: status?.username ?? null, role: status?.role ?? null, logout }),
    [status?.username, status?.role, logout],
  );

  if (!status?.authenticated) {
    return (
      <main className="grid min-h-screen place-items-center bg-canvas p-5">
        <section className="odak-card w-full max-w-md p-7">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-accent text-base font-bold text-white">S</span>
          <h1 className="mt-4 text-xl font-semibold text-ink-900">Scalper Intelligent Trade Systems</h1>
          <p className="mt-1 text-sm text-ink-500">PANEL</p>

          {!status && !error && <p className="mt-5 text-sm text-ink-400">Oturum doğrulanıyor…</p>}

          {status && !status.configured && (
            <div className="mt-5 rounded-lg border border-warn/30 bg-warn-soft p-3 text-sm text-warn">
              Kimlik doğrulama yapılandırılmamış. Backend'de <code>SCALPER_ADMIN_PASSWORD</code> tanımlayın.
            </div>
          )}

          {status?.configured && (
            <form onSubmit={login} className="mt-5 space-y-3">
              <label className="block">
                <span className="odak-kicker">Kullanıcı adı</span>
                <input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                  required
                  autoFocus
                  placeholder="admin"
                  className="mt-1.5 w-full rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink-900 outline-none focus:border-accent"
                />
              </label>
              <label className="block">
                <span className="odak-kicker">Parola</span>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  required
                  className="mt-1.5 w-full rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink-900 outline-none focus:border-accent"
                />
              </label>
              <Button type="submit" variant="primary" className="w-full" disabled={busy}>
                {busy ? "Doğrulanıyor…" : "Oturum aç"}
              </Button>
            </form>
          )}

          {error && (
            <p role="alert" className="mt-4 text-sm text-loss">
              {error}
            </p>
          )}
          {networkError && (
            <div className="mt-3 rounded-lg border border-warn/30 bg-warn-soft p-3 text-xs text-warn">
              Panel açık ama arka uç servisine ulaşılamıyor. Backend'i başlatın (port 8004) ve
              yeniden deneyin.
              <Button
                className="mt-2 w-full"
                onClick={() => {
                  setError("");
                  setNetworkError(false);
                  refresh().catch(markRetryable);
                }}
              >
                Yeniden dene
              </Button>
            </div>
          )}
        </section>
      </main>
    );
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
