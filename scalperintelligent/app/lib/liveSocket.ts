"use client";

import { useEffect, useRef, useState } from "react";
import { WS_URL } from "./api";

export type LiveMessage<T = unknown> = { type: string; data: T };
export type LiveStatus = "connecting" | "open" | "closed";

/** Tüketicisi olmayan yüksek hacimli tipleri eler (bkz. koyu tema liveSocket). */
const UNCONSUMED: ReadonlySet<string> = new Set(["tickers", "trade_repair_completed"]);

type MessageListener = (message: LiveMessage) => void;
type StatusListener = (status: LiveStatus) => void;
/** Dinleyicinin ilgilendiği mesaj tipleri; `null` = hepsi (filtre yok). */
type Subscription = { listener: MessageListener; types: ReadonlySet<string> | null };

let socket: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectAttempt = 0;
let status: LiveStatus = "closed";
const subscriptions = new Set<Subscription>();
const statusListeners = new Set<StatusListener>();

const HEARTBEAT_CHECK_MS = 15_000;
const STALE_AFTER_MS = 45_000;
let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
let lastMessageAt = 0;

/** Ham JSON metninden `"type":"..."` değerini parse etmeden çıkarır (ucuz ön filtre). */
const TYPE_PATTERN = /"type"\s*:\s*"([^"]*)"/;
function peekType(raw: string): string | null {
  const match = TYPE_PATTERN.exec(raw);
  return match ? match[1] : null;
}

/** Herhangi bir abonenin ilgilendiği tip mi? Filtresiz abone varsa her tip geçer. */
function wanted(type: string): boolean {
  for (const subscription of subscriptions) {
    if (subscription.types === null || subscription.types.has(type)) return true;
  }
  return false;
}

function stopHeartbeat() {
  if (heartbeatTimer) clearInterval(heartbeatTimer);
  heartbeatTimer = null;
}
function startHeartbeat() {
  stopHeartbeat();
  lastMessageAt = Date.now();
  heartbeatTimer = setInterval(() => {
    const instance = socket;
    if (!instance) return stopHeartbeat();
    if (Date.now() - lastMessageAt <= STALE_AFTER_MS) return;
    try { instance.close(); } catch { /* zaten kapalı */ }
  }, HEARTBEAT_CHECK_MS);
}
function setStatus(next: LiveStatus) {
  status = next;
  statusListeners.forEach((listener) => listener(next));
}
function connect() {
  if (typeof window === "undefined" || socket || subscriptions.size === 0) return;
  setStatus("connecting");
  const instance = new WebSocket(WS_URL);
  socket = instance;
  instance.onopen = () => {
    if (socket === instance) {
      reconnectAttempt = 0;
      setStatus("open");
      startHeartbeat();
    }
  };
  instance.onmessage = (event) => {
    if (socket !== instance) return;
    const raw = typeof event.data === "string" ? event.data : "";
    // Her mesaj canlılık kanıtıdır; elenen tipler de kalp atışını besler.
    lastMessageAt = Date.now();
    // JSON.parse ÖNCESİ ucuz eleme: `binance_price` gibi saniyelik, tüm
    // piyasayı taşıyan mesajlar yalnız bir abonesi varsa parse edilir.
    const type = peekType(raw);
    if (type !== null && (UNCONSUMED.has(type) || !wanted(type))) return;
    try {
      const message = JSON.parse(raw) as LiveMessage;
      if (!message?.type || UNCONSUMED.has(message.type)) return;
      subscriptions.forEach((subscription) => {
        if (subscription.types === null || subscription.types.has(message.type)) subscription.listener(message);
      });
    } catch {
      /* bozuk mesaj kanalı düşürmesin */
    }
  };
  instance.onclose = (event) => {
    if (socket !== instance) return;
    socket = null;
    stopHeartbeat();
    setStatus("closed");
    if (event.code === 4401) {
      window.dispatchEvent(new CustomEvent("odak:auth-expired"));
      return;
    }
    const delay = Math.min(30_000, 2_000 * 2 ** Math.min(reconnectAttempt, 4)) + Math.random() * 1_000;
    reconnectAttempt += 1;
    if (subscriptions.size > 0) reconnectTimer = setTimeout(connect, delay);
  };
  instance.onerror = () => instance.close();
}
function subscribeLive(listener: MessageListener, types?: readonly string[]) {
  const subscription: Subscription = { listener, types: types ? new Set(types) : null };
  subscriptions.add(subscription);
  connect();
  return () => {
    subscriptions.delete(subscription);
    if (subscriptions.size === 0) {
      if (reconnectTimer) clearTimeout(reconnectTimer);
      reconnectTimer = null;
      stopHeartbeat();
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

export function useLiveStatus() {
  const [current, setCurrent] = useState<LiveStatus>(status);
  useEffect(() => {
    statusListeners.add(setCurrent);
    return () => { statusListeners.delete(setCurrent); };
  }, []);
  return current;
}

/**
 * Canlı mesaj aboneliği. `types` verilirse yalnız o tipler iletilir ve diğer
 * tipler parse bile edilmez (bkz. onmessage). Tip listesi sabit olmalı; her
 * render'da yeni dizi üretilirse abonelik yeniden kurulur.
 */
export function useLiveMessages(listener: MessageListener, types?: readonly string[]) {
  const listenerRef = useRef(listener);
  useEffect(() => { listenerRef.current = listener; }, [listener]);
  const typesKey = types ? types.join("|") : "";
  useEffect(
    () => subscribeLive((message) => listenerRef.current(message), typesKey ? typesKey.split("|") : undefined),
    [typesKey],
  );
}

/**
 * Kabuk seviyesinde KALICI bağlantı (denetim P1-5): WS yalnız `subscribeLive`
 * çağıran sayfalarda açılıyordu; diğer sayfalarda rozet "KOPUK" kalıyordu.
 * AppShell bunu bir kez bağlar; boş tip kümesi hiçbir mesajı parse ettirmez.
 */
export function useLiveConnection() {
  useEffect(() => subscribeLive(() => undefined, []), []);
}
