"use client";

import { useEffect, useRef, useState } from "react";
import { WS_URL } from "./api";
import { applyCommissionPct } from "./pnl";

export type LiveMessage<T = unknown> = { type: string; data: T };
export type LiveStatus = "connecting" | "open" | "closed";

/**
 * Frontend'te TÜKETİCİSİ OLMAYAN WS mesaj tipleri.
 *
 * Denetim #53: backend `ws_broadcast_loop` (`routers/runtime.py:138`) SANİYEDE
 * BİR `tickers` dizisi yayınlıyor (309 sembol × 6 alan ≈ 50 KB/sn). Hiçbir
 * frontend sayfası bu tipi dinlemiyor; yani saniyede bir 50 KB JSON parse
 * + `messageListeners` turu yapılıp sonuç çöpe atılıyordu. Bu liste, tüketicisi
 * yazılana kadar bu tipleri `onmessage` içinde ELER.
 */
export const UNCONSUMED_LIVE_TYPES: ReadonlySet<string> = new Set([
  "tickers",
  // `trade_repair_completed`: `/trade-repair` sayfası kaldırıldığı için
  // frontend'de tüketicisi yok.
  "trade_repair_completed",
  // NOT: `binance_account_update` bu listeye eklenmedi — tüketicisi var
  // (bkz. `binance-tr/page.tsx`).
]);

type MessageListener = (message: LiveMessage) => void;
type StatusListener = (status: LiveStatus) => void;

let socket: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectAttempt = 0;
let status: LiveStatus = "closed";
const messageListeners = new Set<MessageListener>();
const statusListeners = new Set<StatusListener>();

/** Yeniden bağlanma bildirimi: `since` = veri akışının kesildiği an (epoch ms; son mesaj ya da kapanış). */
export type LiveReconnectInfo = { since: number };
type ReconnectListener = (info: LiveReconnectInfo) => void;
const reconnectListeners = new Set<ReconnectListener>();

// Abonelik tipleri: her dinleyici ilgilendiği mesaj tiplerini bildirebilir.
// `null` = tüm tipler (geriye dönük uyumlu varsayılan). Hiçbir dinleyici
// bir tipi istemiyorsa o mesaj JSON.parse edilmeden, ham metin üzerinde ucuz
// bir alt-dize kontrolüyle elenir (`binance_price` saniyede bir tüm pazarı taşır).
const listenerTypes = new Map<MessageListener, ReadonlySet<string> | null>();
let wantsAllTypes = true;
let wantedTypes: ReadonlySet<string> = new Set();

function recomputeWanted() {
  let all = false;
  const union = new Set<string>();
  messageListeners.forEach((listener) => {
    const types = listenerTypes.get(listener) ?? null;
    if (types === null) { all = true; return; }
    types.forEach((t) => union.add(t));
  });
  wantsAllTypes = all;
  wantedTypes = union;
}

/** Ham JSON metninde `"type":"<t>"` geçiyor mu? (parse etmeden ön-eleme) */
function rawHasType(raw: string, type: string): boolean {
  return raw.includes(`"type":"${type}"`) || raw.includes(`"type": "${type}"`);
}

function rawWantsAnyType(raw: string): boolean {
  for (const t of wantedTypes) if (rawHasType(raw, t)) return true;
  return false;
}

// 2026-10-18 (denetim #7): `\s` kaçışı eksikti; backend `": "` ayracıyla yayınladığı için hiç eşleşmiyordu.
const COMMISSION_RE = /"commission_pct"\s*:\s*([0-9.eE+-]+)/;

// H-09: yarım-açık (half-open) WS bağlantısı gözetimi.
//
// `onclose` yalnızca TCP kapanışında tetiklenir; kablo/NAT oturumu düştüğünde
// soket "open" kalır ve başlıklarda yeşil "● CANLI" yanmaya devam eder, veri
// donar. Bu yüzden son mesaj zamanı izlenir: 5 sn'de bir kontrol edilir,
// 20 sn boyunca hiç mesaj gelmezse bağlantı ölü sayılır, atılır ve hemen
// yeniden kurulur.
// 2026-10-18 (mobil denetimi #9): eşikler 15 sn/45 sn idi → ölü soket en kötü
// ~60 sn "CANLI" görünüyordu. Backend `portfolio` + `binance_price` çerçevelerini
// piyasa açıkken saniyede bir yayınlar; 20 sn sessizlik bağlantının ölü olduğuna
// dair güçlü işarettir, yanlış alarmın maliyeti yalnız ucuz bir yeniden bağlanmadır.
export const HEARTBEAT_CHECK_MS = 5_000;
export const STALE_AFTER_MS = 20_000;
/** Uygulama öne gelince/ağ dönünce: bu kadar sessizlik varsa soket beklemeden yenilenir. */
export const RESUME_STALE_MS = 5_000;
/** CONNECTING durumunda bu kadar takılan soket (iOS'ta arka plandan dönüşte görülür) yenilenir. */
export const CONNECT_STUCK_MS = 8_000;
let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
let lastMessageAt = 0;
let lastDownAt = 0;
let connectStartedAt = 0;
let hasOpenedBefore = false;

export function isSocketStale(lastAt: number, now: number, thresholdMs: number): boolean {
  return lastAt > 0 && now - lastAt > thresholdMs;
}

/** Üstel geri çekilme + jitter + tavan: sunucu kesintisinde sabit 2 sn'lik yeniden bağlanma fırtınası olmasın. */
export function reconnectDelayMs(attempt: number, random = Math.random()): number {
  return Math.min(30_000, 2_000 * 2 ** Math.min(attempt, 4)) + random * 1_000;
}

function stopHeartbeat() {
  if (heartbeatTimer) clearInterval(heartbeatTimer);
  heartbeatTimer = null;
}

function startHeartbeat() {
  stopHeartbeat();
  lastMessageAt = Date.now();
  heartbeatTimer = setInterval(() => {
    if (!socket) { stopHeartbeat(); return; }
    if (!isSocketStale(lastMessageAt, Date.now(), STALE_AFTER_MS)) return;
    // Ölü soket: `close()` yarım-açık bağlantıda onclose'u uzun süre getirmeyebilir →
    // soketi doğrudan at ve hemen yeniden kur.
    recycleSocket();
  }, HEARTBEAT_CHECK_MS);
}

/** Son WS mesajının üzerinden geçen süre (ms). Gözetim/etiket için. */
export function liveSilenceMs(): number {
  return lastMessageAt ? Date.now() - lastMessageAt : 0;
}

function setStatus(next: LiveStatus) {
  status = next;
  statusListeners.forEach((listener) => listener(next));
}

function connect() {
  if (typeof window === "undefined" || socket || messageListeners.size === 0) return;
  installLifecycleListeners();
  setStatus("connecting");
  connectStartedAt = Date.now();
  const instance = new WebSocket(WS_URL);
  socket = instance;
  instance.onopen = () => {
    if (socket === instance) {
      reconnectAttempt = 0;
      // Kesinti süresince kaçırılan olaylar için tüketicilere haber ver (REST ile telafi).
      // `startHeartbeat` lastMessageAt'i sıfırladığı için ÖNCE okunur.
      const since = lastMessageAt || lastDownAt;
      const wasReconnect = hasOpenedBefore;
      hasOpenedBefore = true;
      setStatus("open");
      startHeartbeat();
      if (wasReconnect && since > 0) reconnectListeners.forEach((listener) => listener({ since }));
    }
  };
  instance.onmessage = (event) => {
    if (socket !== instance) return;
    // `tickers` saniyede bir gelir ve hiçbir tüketiciyi yoktur; `lastMessageAt`
    // güncellenmesi de yapılmaz (aksi halde "ölü soket" gözlemi bu sahte
    // trafikle yanlışlıkla canlı görünürdü).
    const raw = typeof event.data === "string" ? event.data : "";
    if (raw) {
      // ucuz ön-eleme: tipi çıkarmadan ayrıştırmadan önce ham metinde ara
      if (raw.includes('"type":"tickers"') || raw.includes('"type": "tickers"')) return;
    }
    lastMessageAt = Date.now();
    // Hiçbir dinleyicinin istemediği tip: parse etmeden at. Tek yan etki olan
    // komisyon senkronu (H-01) `portfolio` mesajından regex ile alınır.
    if (raw && !wantsAllTypes && !rawWantsAnyType(raw)) {
      if (rawHasType(raw, "portfolio")) {
        const m = COMMISSION_RE.exec(raw);
        if (m) applyCommissionPct(m[1]);
      }
      return;
    }
    try {
      const message = JSON.parse(event.data) as LiveMessage;
      if (UNCONSUMED_LIVE_TYPES.has(message?.type)) return;
      // H-01: komisyon oranı backend'den tek noktadan senkronlanır → tüm
      // sayfalar açık pozisyon K/Z'sini aynı (net) esasla hesaplar.
      if (message?.type === "portfolio") {
        applyCommissionPct((message.data as { commission_pct?: unknown } | null)?.commission_pct);
      }
      if (message?.type) {
        messageListeners.forEach((listener) => {
          const types = listenerTypes.get(listener);
          if (types && !types.has(message.type)) return;
          listener(message);
        });
      }
    } catch {
      // Ignore malformed messages without taking the shared live channel down.
    }
  };
  instance.onclose = (event) => {
    if (socket !== instance) return;
    socket = null;
    stopHeartbeat();
    lastDownAt = Date.now();
    setStatus("closed");
    if (event.code === 4401) {
      window.dispatchEvent(new CustomEvent("scalper:auth-expired"));
      return;
    }
    // Exponential backoff with jitter and a ceiling: a backend outage must
    // not turn every open tab into a fixed 2s retry storm.
    const delay = reconnectDelayMs(reconnectAttempt);
    reconnectAttempt += 1;
    if (messageListeners.size > 0) reconnectTimer = setTimeout(connect, delay);
  };
  instance.onerror = () => instance.close();
}

/** Soketi sessizce bırakıp (onclose geri çağrısı tetiklemeden) bekleme olmadan yeniden kurar. */
function recycleSocket() {
  const instance = socket;
  socket = null;
  if (instance) {
    instance.onopen = null;
    instance.onmessage = null;
    instance.onerror = null;
    instance.onclose = null;
    try { instance.close(); } catch { /* zaten kapalı */ }
  }
  stopHeartbeat();
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = null;
  reconnectAttempt = 0;
  lastDownAt = Date.now();
  setStatus("closed");
  connect();
}

/**
 * Uygulama öne geldi / ağ döndü / bfcache'ten çıkıldı: yeniden bağlanma geri çekilmesini
 * beklemeden bağlan; açık görünen ama sessiz (ölü) soketi hemen yenile.
 * 2026-10-18 (mobil denetimi #9): mobil işletim sistemi arka plandaki soketi öldürür; eskiden
 * `visibilitychange`/`online`/`pageshow` dinlenmediği için dönüşte ~60 sn donuk veri görülürdü.
 */
export function wakeLive(forceRecycle = false) {
  if (typeof window === "undefined" || messageListeners.size === 0) return;
  const instance = socket;
  if (!instance) {
    // Geri çekilme zamanlayıcısı bekliyor (ya da hiç kurulmadı): hemen bağlan.
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = null;
    reconnectAttempt = 0;
    connect();
    return;
  }
  const now = Date.now();
  const closed = instance.readyState >= 2; // CLOSING | CLOSED
  const connectingStuck = instance.readyState === 0 && now - connectStartedAt > CONNECT_STUCK_MS;
  if (forceRecycle || closed || connectingStuck || isSocketStale(lastMessageAt, now, RESUME_STALE_MS)) {
    recycleSocket();
  }
}

let lifecycleInstalled = false;
const onVisibilityChange = () => { if (document.visibilityState === "visible") wakeLive(); };
const onPageShow = (event: Event) => { wakeLive((event as PageTransitionEvent).persisted === true); };
const onOnline = () => wakeLive(true);

function installLifecycleListeners() {
  if (lifecycleInstalled || typeof window === "undefined") return;
  lifecycleInstalled = true;
  document.addEventListener("visibilitychange", onVisibilityChange);
  document.addEventListener("resume", onVisibilityChange); // Chrome Page Lifecycle: dondurulmuş sekme canlandı
  window.addEventListener("pageshow", onPageShow);
  window.addEventListener("online", onOnline);
}

function removeLifecycleListeners() {
  if (!lifecycleInstalled || typeof window === "undefined") return;
  lifecycleInstalled = false;
  document.removeEventListener("visibilitychange", onVisibilityChange);
  document.removeEventListener("resume", onVisibilityChange);
  window.removeEventListener("pageshow", onPageShow);
  window.removeEventListener("online", onOnline);
}

/**
 * @param types dinlenecek mesaj tipleri; verilmezse (veya boşsa) tüm tipler.
 */
export function subscribeLive(listener: MessageListener, types?: readonly string[]) {
  messageListeners.add(listener);
  listenerTypes.set(listener, types && types.length > 0 ? new Set(types) : null);
  recomputeWanted();
  connect();
  return () => {
    messageListeners.delete(listener);
    listenerTypes.delete(listener);
    recomputeWanted();
    if (messageListeners.size === 0) {
      if (reconnectTimer) clearTimeout(reconnectTimer);
      reconnectTimer = null;
      stopHeartbeat();
      removeLifecycleListeners();
      hasOpenedBefore = false;
      lastMessageAt = 0;
      lastDownAt = 0;
      const instance = socket;
      socket = null;
      if (instance) {
        instance.onopen = null;
        instance.onmessage = null;
        instance.onerror = null;
        instance.onclose = null;
        instance.close();
      }
      setStatus("closed");
    }
  };
}

/** Soket kesintiden sonra yeniden bağlandığında çağrılır (ilk bağlanışta DEĞİL). */
export function subscribeLiveReconnect(listener: ReconnectListener) {
  reconnectListeners.add(listener);
  return () => { reconnectListeners.delete(listener); };
}

/** `subscribeLiveReconnect` için hook: dinleyici ref'te tutulur, abonelik kopmaz. */
export function useLiveReconnect(listener: ReconnectListener) {
  const listenerRef = useRef(listener);
  useEffect(() => {
    listenerRef.current = listener;
  }, [listener]);
  useEffect(() => subscribeLiveReconnect((info) => listenerRef.current(info)), []);
}

export function useLiveStatus() {
  const [current, setCurrent] = useState<LiveStatus>(status);
  useEffect(() => {
    statusListeners.add(setCurrent);
    return () => { statusListeners.delete(setCurrent); };
  }, []);
  return current;
}

export function useLiveMessages(listener: MessageListener, types?: readonly string[]) {
  // Listener bir ref'te tutulur: consumer'ın her render'da yeni bir inline
  // fonksiyon geçmesi (memoize edilmemiş olsa bile) aboneliği koparmaz.
  // Daha önce listener kimliği effect dependency'ydi ve chat sayfası gibi
  // sık render eden tüketiciler WebSocket'i saniyede onlarca kez
  // kapatıp yeniden açıyordu (streaming sırasında mesaj kaybı).
  const listenerRef = useRef(listener);
  useEffect(() => {
    listenerRef.current = listener;
  }, [listener]);
  const typesKey = types && types.length > 0 ? types.join("|") : "";
  useEffect(
    () => subscribeLive((message) => listenerRef.current(message), typesKey ? typesKey.split("|") : undefined),
    [typesKey],
  );
}
