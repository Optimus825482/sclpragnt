"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import RequireAdmin from "../components/RequireAdmin";
import { useAuth } from "../lib/auth";

type ManagedUser = {
  id: number;
  username: string;
  role: string;
  is_active: boolean;
  created_at: number;
  updated_at: number;
};

type Notice = { kind: "ok" | "err"; text: string } | null;

const fmtDate = (value: number) =>
  value ? new Date(value < 10_000_000_000 ? value * 1000 : value).toLocaleString("tr-TR") : "—";

function UserModal({ mode, initial, onClose, onSaved }: {
  mode: "create" | "edit";
  initial?: ManagedUser | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [username, setUsername] = useState(initial?.username ?? "");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState(initial?.role ?? "user");
  const [isActive, setIsActive] = useState(initial?.is_active ?? true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    setBusy(true); setError("");
    try {
      const body: Record<string, unknown> = { username, role, is_active: isActive };
      if (mode === "create" || password) body.password = password;
      const url = mode === "create" ? "/api/admin/users" : `/api/admin/users/${initial?.id}`;
      const response = await apiRequest(`${API_BASE}${url}`, {
        method: mode === "create" ? "POST" : "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "İşlem başarısız");
      onSaved();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "İşlem başarısız");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[110] grid place-items-center bg-black/75 p-4" onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="user-modal-title">
      <section className="w-full max-w-md rounded-xl border border-bunker-700 bg-bunker-950 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-bunker-800 px-5 py-4">
          <h2 id="user-modal-title" className="font-mono text-lg font-bold text-white">{mode === "create" ? "Kullanıcı Ekle" : "Kullanıcı Düzenle"}</h2>
          <button type="button" onClick={onClose} className="text-bunker-muted hover:text-white" aria-label="Kapat">✕</button>
        </div>
        <div className="space-y-4 p-5">
          <label className="block"><span className="eyebrow">KULLANICI ADI</span>
            <input value={username} onChange={(e) => setUsername(e.target.value)} className="input mt-2 w-full" placeholder="kullanici_adi" autoFocus />
          </label>
          <label className="block"><span className="eyebrow">{mode === "create" ? "ŞİFRE" : "YENİ ŞİFRE (opsiyonel)"}</span>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="input mt-2 w-full" placeholder={mode === "create" ? "En az 6 karakter" : "Değiştirmek istemiyorsanız boş bırakın"} autoComplete="new-password" />
          </label>
          <div>
            <span className="eyebrow">ROL</span>
            <div className="mt-2 flex gap-2">
              <button type="button" onClick={() => setRole("user")} className={`flex-1 rounded-lg border px-3 py-2 font-mono text-xs ${role === "user" ? "border-neon-green/60 bg-neon-green/10 text-neon-green" : "border-bunker-700 text-bunker-muted hover:border-bunker-600"}`}>USER</button>
              <button type="button" onClick={() => setRole("admin")} className={`flex-1 rounded-lg border px-3 py-2 font-mono text-xs ${role === "admin" ? "border-amber-300/60 bg-amber-300/10 text-amber-300" : "border-bunker-700 text-bunker-muted hover:border-bunker-600"}`}>ADMIN</button>
            </div>
          </div>
          <label className="flex items-center justify-between rounded-lg border border-bunker-800 bg-bunker-900/50 px-3 py-2.5">
            <span className="font-mono text-xs text-white">Hesap aktif</span>
            <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} className="h-4 w-4 accent-neon-green" />
          </label>
          {error && <p role="alert" className="rounded-lg border border-neon-red/40 bg-neon-red/10 px-3 py-2 text-sm text-neon-red">{error}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose} className="ui-button ui-button-secondary">VAZGEÇ</button>
            <button type="button" onClick={submit} disabled={busy || !username.trim()} className="ui-button ui-button-primary">{busy ? "KAYDEDİLİYOR…" : "KAYDET"}</button>
          </div>
        </div>
      </section>
    </div>
  );
}

function ConfirmModal({ username, onClose, onConfirm }: { username: string; onClose: () => void; onConfirm: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const confirm = async () => {
    setBusy(true); setError("");
    try { await onConfirm(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Silme başarısız"); setBusy(false); }
  };
  return (
    <div className="fixed inset-0 z-[110] grid place-items-center bg-black/75 p-4" onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="confirm-title">
      <section className="w-full max-w-sm rounded-xl border border-bunker-700 bg-bunker-950 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="p-5">
          <h2 id="confirm-title" className="font-mono text-lg font-bold text-white">Kullanıcıyı sil</h2>
          <p className="mt-2 text-sm text-bunker-muted"><strong className="text-white">{username}</strong> kullanıcısını silmek istediğinize emin misiniz? Bu işlem geri alınamaz.</p>
          {error && <p role="alert" className="mt-3 rounded-lg border border-neon-red/40 bg-neon-red/10 px-3 py-2 text-sm text-neon-red">{error}</p>}
          <div className="mt-5 flex justify-end gap-2">
            <button type="button" onClick={onClose} className="ui-button ui-button-secondary">VAZGEÇ</button>
            <button type="button" onClick={confirm} disabled={busy} className="ui-button" style={{ borderColor: "rgb(255 49 49 / .5)", background: "rgb(255 49 49 / .12)", color: "#ff3131" }}>{busy ? "SİLİNİYOR…" : "EVET, SİL"}</button>
          </div>
        </div>
      </section>
    </div>
  );
}

export default function UsersPage() {
  const { username: currentUsername } = useAuth();
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<Notice>(null);
  const [modal, setModal] = useState<{ mode: "create" | "edit"; user?: ManagedUser | null } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<ManagedUser | null>(null);

  const load = useCallback(async () => {
    try {
      const response = await apiRequest(`${API_BASE}/api/admin/users`, { cache: "no-store" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Kullanıcı listesi alınamadı");
      setUsers(data.users || []);
    } catch (reason) {
      setNotice({ kind: "err", text: reason instanceof Error ? reason.message : "Kullanıcı listesi alınamadı" });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const notify = (kind: "ok" | "err", text: string) => {
    setNotice({ kind, text });
    window.setTimeout(() => setNotice(null), 4000);
  };

  const handleSaved = () => {
    setModal(null);
    load();
    notify("ok", modal?.mode === "create" ? "Kullanıcı oluşturuldu." : "Kullanıcı güncellendi.");
  };

  const handleDelete = async () => {
    if (!confirmDelete) return;
    const response = await apiRequest(`${API_BASE}/api/admin/users/${confirmDelete.id}`, { method: "DELETE" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "Silme başarısız");
    setConfirmDelete(null);
    await load();
    notify("ok", "Kullanıcı silindi.");
  };

  return (
    <RequireAdmin>
      <main className="page-shell">
        <div className="page-heading flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="eyebrow">SİSTEM YÖNETİMİ</p>
            <h1 className="font-mono text-2xl font-bold text-white">Kullanıcı Yönetimi</h1>
            <p className="mt-1 text-sm text-bunker-muted">Kullanıcı adı ve şifre ile giriş yapan hesapları yönetin.</p>
          </div>
          <button type="button" onClick={() => setModal({ mode: "create" })} className="ui-button ui-button-primary">+ KULLANICI EKLE</button>
        </div>

        {notice && (
          <div role="status" className={`mt-4 rounded-lg border px-4 py-3 text-sm ${notice.kind === "ok" ? "border-neon-green/40 bg-neon-green/10 text-neon-green" : "border-neon-red/40 bg-neon-red/10 text-neon-red"}`}>
            {notice.text}
          </div>
        )}

        <div className="card mt-5 overflow-x-auto">
          {loading ? (
            <p className="py-10 text-center font-mono text-sm text-bunker-muted">Yükleniyor…</p>
          ) : users.length === 0 ? (
            <p className="py-10 text-center font-mono text-sm text-bunker-muted">Henüz kullanıcı yok.</p>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Kullanıcı Adı</th><th>Rol</th><th>Durum</th><th>Oluşturulma</th><th>Güncellenme</th><th className="text-right">İşlemler</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td className="font-mono font-bold text-white">{u.username}{u.username === currentUsername && <span className="ml-2 text-[10px] text-neon-green">(SİZ)</span>}</td>
                    <td>{u.role === "admin" ? <span className="rounded border border-amber-300/50 bg-amber-300/10 px-1.5 py-0.5 font-mono text-[10px] text-amber-300">ADMIN</span> : <span className="rounded border border-bunker-600 px-1.5 py-0.5 font-mono text-[10px] text-bunker-muted">USER</span>}</td>
                    <td>{u.is_active ? <span className="font-mono text-xs text-neon-green">AKTİF</span> : <span className="font-mono text-xs text-neon-red">PASİF</span>}</td>
                    <td className="font-mono text-xs text-bunker-muted">{fmtDate(u.created_at)}</td>
                    <td className="font-mono text-xs text-bunker-muted">{fmtDate(u.updated_at)}</td>
                    <td className="text-right whitespace-nowrap">
                      <button type="button" onClick={() => setModal({ mode: "edit", user: u })} className="ui-button ui-button-secondary mr-2 !min-h-9 !px-3 !py-1.5 text-xs">DÜZENLE</button>
                      <button type="button" onClick={() => setConfirmDelete(u)} disabled={u.username === currentUsername} className="ui-button !min-h-9 !px-3 !py-1.5 text-xs disabled:opacity-40" style={{ borderColor: "rgb(255 49 49 / .5)", background: "rgb(255 49 49 / .1)", color: "#ff3131" }} title={u.username === currentUsername ? "Kendi hesabınızı silemezsiniz" : `${u.username} kullanıcısını sil`}>SİL</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <p className="mt-3 font-mono text-[11px] text-bunker-muted">Kullanıcı adı büyük/küçük harfe duyarsızdır · Şifreler PBKDF2 ile hash&apos;lenir · Son admin silinemez.</p>

        {modal && <UserModal mode={modal.mode} initial={modal.user} onClose={() => setModal(null)} onSaved={handleSaved} />}
        {confirmDelete && <ConfirmModal username={confirmDelete.username} onClose={() => setConfirmDelete(null)} onConfirm={handleDelete} />}
      </main>
    </RequireAdmin>
  );
}
