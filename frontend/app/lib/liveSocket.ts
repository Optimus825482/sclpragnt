"use client";

import { useEffect, useState } from "react";
import { WS_URL } from "./api";

export type LiveMessage<T = unknown> = { type: string; data: T };
export type LiveStatus = "connecting" | "open" | "closed";

type MessageListener = (message: LiveMessage) => void;
type StatusListener = (status: LiveStatus) => void;

let socket: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let status: LiveStatus = "closed";
const messageListeners = new Set<MessageListener>();
const statusListeners = new Set<StatusListener>();

function setStatus(next: LiveStatus) {
  status = next;
  statusListeners.forEach((listener) => listener(next));
}

function connect() {
  if (typeof window === "undefined" || socket || messageListeners.size === 0) return;
  setStatus("connecting");
  const instance = new WebSocket(WS_URL);
  socket = instance;
  instance.onopen = () => { if (socket === instance) setStatus("open"); };
  instance.onmessage = (event) => {
    if (socket !== instance) return;
    try {
      const message = JSON.parse(event.data) as LiveMessage;
      if (message?.type) messageListeners.forEach((listener) => listener(message));
    } catch {
      // Ignore malformed messages without taking the shared live channel down.
    }
  };
  instance.onclose = (event) => {
    if (socket !== instance) return;
    socket = null;
    setStatus("closed");
    if (event.code === 4401) {
      window.dispatchEvent(new CustomEvent("scalper:auth-expired"));
      return;
    }
    if (messageListeners.size > 0) reconnectTimer = setTimeout(connect, 2_000);
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
  useEffect(() => subscribeLive(listener), [listener]);
}
