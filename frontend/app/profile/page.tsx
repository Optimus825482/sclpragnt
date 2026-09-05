"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import { useAuth } from "../lib/auth";
import { getUiMode, setUiMode } from "../lib/ui-mode";

type Notice = { kind: "ok" | "err"; text: string } | null;

export default function ProfilePage() {
  const { username, role } = useAuth();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const [memberSince, setMemberSince] = useState<number | null>(null);

  const loadProfile = useCallback(async () => {
    try {
      const res = await apiRequest(`${API_BASE}/api/profile`, { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        setMemberSince(data?.user?.created_at ?? null);
      }
    } catch {
      // Profil bilgisi alınamadı; yalnızca kullanıcı adı gösterilir
    }
  }, []);

  useEffect(() => {
    loadProfile();
  }, [loadProfile]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setNotice(null);
    if (newPassword !== confirmPassword) {
      setNotice({ kind: "err", text: "Yeni şifre ve onayı eşleşmiyor." });
      return;
    }
    if (newPassword.length < 6) {
      setNotice({ kind: "err", text: "Yeni şifre en az 6 karakter olmalı." });
      return;
    }
    setBusy(true);
    try {
      const res = await apiRequest(`${API_BASE}/api/profile/password`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setNotice({ kind: "err", text: data?.detail || "Şifre güncellenemedi." });
        return;
      }
      setNotice({ kind: "ok", text: data?.message || "Şifreniz güncellendi." });
      setCurrentPassword(""); setNewPassword(""); setConfirmPassword("");
    } catch {
      setNotice({ kind: "err", text: "Şifre güncellenemedi. Bağlantı hatası." });
    } finally {
      setBusy(false);
    }
  };

  const displayName = username ? String(username).charAt(0).toUpperCase() + String(username).slice(1) : "Kullanıcı";
  const fmtDate = (value: number | null) =>
    value ? new Date(value < 10_000_000_000 ? value * 1000 : value).toLocaleDateString("tr-TR") : "—";

  return (
    <main className="page-shell">
      <div className="page-heading">
        <p className="eyebrow text-neon-green">KULLANICI PROFİLİ</p>
        <h1>Profil</h1>
        <p className="text-bunker-muted">Hesap bilgileriniz ve şifre güncelleme.</p>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Kimlik kartı */}
        <section className="card lg:col-span-1">
          <div className="flex flex-col items-center text-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-full border border-neon-green/40 bg-neon-green/10 font-mono text-2xl font-bold text-neon-green">
              {displayName.charAt(0)}
            </div>
            <p className="mt-3 font-mono text-xl font-bold text-white">{displayName}</p>
            <p className="mt-1 font-mono text-xs text-bunker-muted">@{username}</p>
            <span className={`mt-2 px-2 py-0.5 rounded text-xs font-mono ${role === "admin" ? "bg-neon-green/15 text-neon-green" : "bg-bunker-800 text-bunker-muted"}`}>
              {role === "admin" ? "SİSTEM YÖNETİCİSİ" : "KULLANICI"}
            </span>
            <div className="mt-5 w-full border-t border-bunker-800 pt-3 text-left text-xs text-bunker-muted">
              <p>Üyelik: <span className="text-white">{fmtDate(memberSince)}</span></p>
              <p className="mt-1">Uygulama: <span className="text-white">Scalper Agent V4 · Paper Only</span></p>
            </div>
          </div>
        </section>

        {/* Şifre değiştirme */}
        <section className="card lg:col-span-2">
          <p className="eyebrow text-neon-green">ŞİFRE GÜNCELLE</p>
          <form onSubmit={submit} className="mt-4 space-y-4">
            <label className="block">
              <span className="eyebrow">MEVCUT ŞİFRE</span>
              <input
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                autoComplete="current-password"
                required
                className="input mt-2 w-full"
              />
            </label>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block">
                <span className="eyebrow">YENİ ŞİFRE</span>
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  autoComplete="new-password"
                  required
                  minLength={6}
                  className="input mt-2 w-full"
                />
              </label>
              <label className="block">
                <span className="eyebrow">YENİ ŞİFRE (ONAY)</span>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  autoComplete="new-password"
                  required
                  minLength={6}
                  className="input mt-2 w-full"
                />
              </label>
            </div>
            {notice && (
              <p role="alert" className={`rounded-lg border px-3 py-2 text-sm ${notice.kind === "ok" ? "border-neon-green/40 bg-neon-green/10 text-neon-green" : "border-neon-red/40 bg-neon-red/10 text-neon-red"}`}>
                {notice.text}
              </p>
            )}
            <button disabled={busy} className="ui-button ui-button-primary">
              {busy ? "GÜNCELLENİYOR…" : "ŞİFREYİ GÜNCELLE"}
            </button>
            <p className="text-xs text-bunker-muted">
              Şifrenizi güncelledikten sonra bir sonraki oturumda yeni şifrenizle giriş yaparsınız.
            </p>
          </form>
        </section>
      </div>

      {/* Hızlı erişim */}
      <section className="card mt-4">
        <p className="eyebrow text-neon-green">HIZLI ERİŞİM</p>
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          <a href="/" className="ui-button justify-center text-center">⚡ Scalping Ana Sayfa</a>
          <a href="/monitoring" className="ui-button justify-center text-center">📡 Monitoring Radar</a>
          <a href="/reports" className="ui-button justify-center text-center">📋 Performans</a>
        </div>
      </section>

      {/* Kullanıcı tercihleri */}
      <section className="card mt-4">
        <p className="eyebrow text-neon-green">KULLANICI TERCİHLERİ</p>
        <div className="mt-4 space-y-4">
          <label className="flex items-center justify-between rounded-lg border border-bunker-700 bg-bunker-900/50 p-3">
            <div>
              <p className="font-mono text-sm font-bold text-white">Arayüz Modu</p>
              <p className="font-mono text-[11px] text-bunker-muted">Basit modda temel metrikler gösterilir, gelişmiş modda tüm kontroller</p>
            </div>
            <select
              value={getUiMode()}
              onChange={(e) => { setUiMode(e.target.value as "simple" | "advanced"); window.location.reload(); }}
              className="rounded border border-bunker-700 bg-bunker-950 px-3 py-2 font-mono text-sm text-white"
            >
              <option value="simple">🔵 Basit</option>
              <option value="advanced">⚙ Gelişmiş</option>
            </select>
          </label>
        </div>
      </section>
    </main>
  );
}
