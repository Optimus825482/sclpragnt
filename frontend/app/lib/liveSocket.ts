"use client";

import { useEffect, useRef, useState } from "react";
import { WS_URL } from "./api";
import { applyCommissionPct } from "./pnl";

export type LiveMessage<T = unknown> = { type: string; data: T };
export type LiveStatus = "connecting" | "open" | "closed";

type MessageListener = (message: LiveMessage) => void;
type StatusListener = (status: LiveStatus) => void;

let socket: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectAttempt = 0;
let status: LiveStatus = "closed";
const messageListeners = new Set<MessageListener>();
const statusListeners = new Set<StatusListener>();

// H-09: yarım-açık (half-open) WS bağlantısı gözetimi.
//
// `onclose` yalnızca TCP kapanışında tetiklenir; kablo/NAT oturumu düştüğünde
// soket "open" kalır ve başlıklarda yeşil "● CANLI" yanmaya devam eder, veri
// donar. Bu yüzden son mesaj zamanı izlenir: 15 sn'de bir kontrol edilir,
// 45 sn boyunca hiç mesaj gelmezse bağlantı ölü sayılır ve kapatılır
// (onclose → status "closed" → backoff'lu yeniden bağlanma).
const HEARTBEAT_CHECK_MS = 15_000;
const STALE_AFTER_MS = 45_000;
let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
let lastMessageAt = 0;

function stopHeartbeat() {
  if (heartbeatTimer) clearInterval(heartbeatTimer);
  heartbeatTimer = null;
}

function startHeartbeat() {
  stopHeartbeat();
  lastMessageAt = Date.now();
  heartbeatTimer = setInterval(() => {
    const instance = socket;
    if (!instance) { stopHeartbeat(); return; }
    if (Date.now() - lastMessageAt <= STALE_AFTER_MS) return;
    // Ölü soket: kapat → onclose → "closed" + yeniden bağlanma.
    try { instance.close(); } catch { /* zaten kapalı */ }
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
    lastMessageAt = Date.now();
    try {
      const message = JSON.parse(event.data) as LiveMessage;
      // H-01: komisyon oranı backend'den tek noktadan senkronlanır → tüm
      // sayfalar açık pozisyon K/Z'sini aynı (net) esasla hesaplar.
      if (message?.type === "portfolio") {
        applyCommissionPct((message.data as { commission_pct?: unknown } | null)?.commission_pct);
      }
      if (message?.type) messageListeners.forEach((listener) => listener(message));
    } catch {
      // Ignore malformed messages without taking the shared live channel down.
    }
  };
  instance.onclose = (event) => {
    if (socket !== instance) return;
    socket = null;
    stopHeartbeat();
    setStatus("closed");
    if (event.code === 4401) {
      window.dispatchEvent(new CustomEvent("scalper:auth-expired"));
      return;
    }
    // Exponential backoff with jitter and a ceiling: a backend outage must
    // not turn every open tab into a fixed 2s retry storm.
    const delay = Math.min(30_000, 2_000 * 2 ** Math.min(reconnectAttempt, 4)) + Math.random() * 1_000;
    reconnectAttempt += 1;
    if (messageListeners.size > 0) reconnectTimer = setTimeout(connect, delay);
  };
  instance.onerror = () => instance.close();
}

export function subscribeLive(listener: MessageListener) {
  messageListeners.add(listener);
  connect();
  return () => {
    messageListeners.delete(listener);
    if (messageListeners.size === 0) {
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

export function useLiveMessages(listener: MessageListener) {
  // Listener bir ref'te tutulur: consumer'ın her render'da yeni bir inline
  // fonksiyon geçmesi (memoize edilmemiş olsa bile) aboneliği koparmaz.
  // Daha önce listener kimliği effect dependency'ydi ve chat sayfası gibi
  // sık render eden tüketiciler WebSocket'i saniyede onlarca kez
  // kapatıp yeniden açıyordu (streaming sırasında mesaj kaybı).
  const listenerRef = useRef(listener);
  useEffect(() => {
    listenerRef.current = listener;
  }, [listener]);
  useEffect(
    () => subscribeLive((message) => listenerRef.current(message)),
    [],
  );
}
