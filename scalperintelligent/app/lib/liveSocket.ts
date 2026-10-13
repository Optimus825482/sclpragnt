"use client";

import { useEffect, useRef, useState } from "react";
import { WS_URL } from "./api";

export type LiveMessage<T = unknown> = { type: string; data: T };
export type LiveStatus = "connecting" | "open" | "closed";

/** Tüketicisi olmayan yüksek hacimli tipleri eler (bkz. koyu tema liveSocket). */
const UNCONSUMED: ReadonlySet<string> = new Set(["tickers", "trade_repair_completed"]);

type MessageListener = (message: LiveMessage) => void;
type StatusListener = (status: LiveStatus) => void;

let socket: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectAttempt = 0;
let status: LiveStatus = "closed";
const messageListeners = new Set<MessageListener>();
const statusListeners = new Set<StatusListener>();

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
    const raw = typeof event.data === "string" ? event.data : "";
    if (raw.includes('"type":"tickers"') || raw.includes('"type": "tickers"')) return;
    lastMessageAt = Date.now();
    try {
      const message = JSON.parse(event.data) as LiveMessage;
      if (UNCONSUMED.has(message?.type)) return;
      if (message?.type) messageListeners.forEach((listener) => listener(message));
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
    if (messageListeners.size > 0) reconnectTimer = setTimeout(connect, delay);
  };
  instance.onerror = () => instance.close();
}
function subscribeLive(listener: MessageListener) {
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
  const listenerRef = useRef(listener);
  useEffect(() => { listenerRef.current = listener; }, [listener]);
  useEffect(() => subscribeLive((message) => listenerRef.current(message)), []);
}
