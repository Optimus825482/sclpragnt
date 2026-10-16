"use client";
import { useCallback, useEffect, useState } from "react";
import { API_BASE, apiRequest } from "../../lib/api";
import { MENU_ITEMS, SETTINGS_TABS, parseSettingsTab, type SettingsTabId } from "../../lib/userUi";
import { useUiPrefs } from "../../lib/useUiPrefs";
import { ensurePushSubscription, pushPermissionState } from "../../lib/push";
import { useAuth } from "../../lib/auth";
import AdminViewSwitch from "../AdminViewSwitch";
import ProfilePanel from "../ProfilePanel";

const TAB_KEY = "scalper:user-settings-tab";
const CARD = "rounded-xl border border-bunker-700 bg-bunker-900 p-4";

function MenuSection() {
  const { hidden, setHidden } = useUiPrefs();
  const [error, setError] = useState("");

  const toggle = async (id: string, visible: boolean) => {
    setError("");
    const set = new Set(hidden);
    if (visible) set.delete(id);
    else set.add(id);
    try {
      await setHidden(Array.from(set));
    } catch {
      setError("Kaydedilemedi, tekrar dene");
    }
  };

  return (
    <section className={CARD} aria-labelledby="menu-baslik">
      <h2 id="menu-baslik" className="text-base font-semibold text-white">Menü</h2>
      <p className="mt-1 text-sm text-bunker-muted">Görmek istemediğin sayfaları menüden gizleyebilirsin.</p>
      <ul className="mt-3 divide-y divide-bunker-800">
        {MENU_ITEMS.filter((item) => !item.legacy).map((item) => {
          const visible = item.locked ? true : !hidden.includes(item.id);
          return (
            <li key={item.id} className="flex min-h-[44px] items-center justify-between gap-3 py-2">
              <span className="text-sm text-white">
                <span aria-hidden="true" className="mr-2">{item.icon}</span>
                {item.label}
              </span>
              {item.locked ? (
                <span className="text-xs text-bunker-muted">Her zaman görünür</span>
              ) : (
                <button
                  type="button"
                  role="switch"
                  aria-checked={visible}
                  aria-label={`${item.label} menüde görünsün`}
                  onClick={() => toggle(item.id, !visible)}
                  className={`relative inline-flex h-11 w-14 shrink-0 items-center rounded-full border border-bunker-700 transition-colors ${visible ? "bg-neon-green" : "bg-bunker-700"}`}
                >
                  <span
                    className={`inline-block h-6 w-6 rounded-full bg-white shadow transition-transform ${visible ? "translate-x-7" : "translate-x-1"}`}
                  />
                </button>
              )}
            </li>
          );
        })}
      </ul>
      {error && <p role="alert" className="mt-2 text-sm text-neon-red">{error}</p>}
    </section>
  );
}

function BinanceSection() {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [justSaved, setJustSaved] = useState(false);

  const check = useCallback(async () => {
    try {
      const r = await apiRequest(`${API_BASE}/api/binance/settings`, { cache: "no-store" });
      if (r.ok) {
        const d = await r.json();
        setConfigured(Boolean(d.configured));
      } else {
        setConfigured(false);
      }
    } catch {
      setConfigured(false);
    }
  }, []);

  useEffect(() => {
    check();
  }, [check]);

  const canSave = apiKey.trim() !== "" && apiSecret.trim() !== "" && !saving;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSave) return;
    setSaving(true);
    setError("");
    setJustSaved(false);
    try {
      const r = await apiRequest(`${API_BASE}/api/binance/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey.trim(), api_secret: apiSecret.trim() }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(typeof d?.detail === "string" ? d.detail : "Kaydedilemedi");
      }
      setConfigured(true);
      setJustSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Kaydedilemedi");
    } finally {
      // Gizli değer her durumda bellekten temizlenir.
      setApiKey("");
      setApiSecret("");
      setSaving(false);
    }
  };

  return (
    <section className={CARD} aria-labelledby="binance-baslik">
      <h2 id="binance-baslik" className="text-base font-semibold text-white">Binance TR bağlantısı</h2>
      <p className="mt-1 text-sm text-white" aria-live="polite">
        {configured === null ? "Durum kontrol ediliyor…" : configured || justSaved ? "Anahtar kayıtlı" : "Anahtar kayıtlı değil"}
      </p>
      <p className="mt-1 text-xs text-bunker-muted">Anahtara yalnız okuma ve spot işlem yetkisi ver; para çekme yetkisi verme.</p>
      <form className="mt-3 space-y-3" onSubmit={submit} autoComplete="off">
        <label className="block text-sm text-white">
          API anahtarı
          <input
            type="text"
            name="api_key"
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            className="mt-1 block min-h-[44px] w-full rounded-lg border border-bunker-700 bg-bunker-800 px-3 text-sm text-white"
          />
        </label>
        <label className="block text-sm text-white">
          API gizli anahtarı
          <input
            type="password"
            name="api_secret"
            autoComplete="new-password"
            value={apiSecret}
            onChange={(e) => setApiSecret(e.target.value)}
            className="mt-1 block min-h-[44px] w-full rounded-lg border border-bunker-700 bg-bunker-800 px-3 text-sm text-white"
          />
        </label>
        <button
          type="submit"
          disabled={!canSave}
          className="min-h-[44px] rounded-lg bg-neon-green px-4 text-sm font-medium text-white disabled:opacity-50"
        >
          {saving ? "Kaydediliyor…" : "Anahtarı kaydet"}
        </button>
      </form>
      {error && <p role="alert" className="mt-2 text-sm text-neon-red">{error}</p>}
    </section>
  );
}

function NotificationSection() {
  const [perm, setPerm] = useState<NotificationPermission | "unsupported">("default");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setPerm(pushPermissionState());
  }, []);

  const enable = async () => {
    setBusy(true);
    setError("");
    try {
      const res = await ensurePushSubscription();
      if (!res.ok) setError(res.reason === "izin_verilmedi" ? "İzin verilmedi" : "Bildirimler açılamadı");
    } catch {
      setError("Bildirimler açılamadı");
    } finally {
      setPerm(pushPermissionState());
      setBusy(false);
    }
  };

  const label =
    perm === "granted" ? "Bildirim izni: açık"
    : perm === "unsupported" ? "Bu tarayıcı bildirimleri desteklemiyor"
    : perm === "denied" ? "Bildirim izni: kapalı (tarayıcı ayarlarından açmalısın)"
    : "Bildirim izni: kapalı";

  return (
    <section className={CARD} aria-labelledby="bildirim-baslik">
      <h2 id="bildirim-baslik" className="text-base font-semibold text-white">Bildirimler</h2>
      <p className="mt-1 text-sm text-white">{label}</p>
      {perm !== "granted" && perm !== "unsupported" && perm !== "denied" && (
        <button
          type="button"
          onClick={enable}
          disabled={busy}
          className="mt-3 min-h-[44px] rounded-lg bg-neon-green px-4 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy ? "Açılıyor…" : "Bildirimleri aç"}
        </button>
      )}
      {error && <p role="alert" className="mt-2 text-sm text-neon-red">{error}</p>}
    </section>
  );
}

export default function UserSettings() {
  const { role } = useAuth();
  // 2026-10-17 (basit arayüz): Profil artık sekme; ?tab= (örn. /settings?tab=profile) > localStorage > "genel".
  const [tab, setTab] = useState<SettingsTabId>("genel");
  useEffect(() => {
    let next: SettingsTabId | null = null;
    try {
      next = parseSettingsTab(new URLSearchParams(window.location.search).get("tab"));
    } catch {
      /* yok say */
    }
    if (!next) {
      try {
        next = parseSettingsTab(window.localStorage.getItem(TAB_KEY));
      } catch {
        /* localStorage yok */
      }
    }
    if (next) setTab(next);
  }, []);
  const selectTab = (id: SettingsTabId) => {
    setTab(id);
    try {
      window.localStorage.setItem(TAB_KEY, id);
    } catch {
      /* yok sayılır */
    }
  };
  return (
    <div className="mx-auto max-w-2xl space-y-4 p-4">
      <h1 className="text-xl font-semibold text-white">Ayarlar</h1>
      <div role="tablist" aria-label="Ayar sekmeleri" className="flex flex-wrap gap-2">
        {SETTINGS_TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`ayar-sekme-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls={`ayar-panel-${t.id}`}
            onClick={() => selectTab(t.id)}
            className={`min-h-[44px] rounded-lg px-4 text-sm font-semibold ${tab === t.id ? "u-seg-on" : "u-seg-off"}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`ayar-panel-${tab}`} aria-labelledby={`ayar-sekme-${tab}`} className="space-y-4">
        {tab === "genel" && (
          <>
            <MenuSection />
            <BinanceSection />
          </>
        )}
        {tab === "bildirim" && <NotificationSection />}
        {tab === "profil" && <ProfilePanel embedded />}
      </div>
      {role === "admin" && (
        <section className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-4" aria-label="Yönetici arayüz seçimi">
          <h2 className="text-sm font-medium text-bunker-muted">Yönetici: gelişmiş arayüze geç</h2>
          <div className="mt-2">
            <AdminViewSwitch />
          </div>
          <p className="mt-2 text-xs text-bunker-muted">Basit: kullanıcıların gördüğü arayüz. Gelişmiş: mevcut yönetim arayüzü.</p>
        </section>
      )}
    </div>
  );
}
