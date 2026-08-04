const browserOrigin = typeof window !== "undefined" ? window.location.origin : "http://localhost:8004";
export const API_BASE = process.env.NEXT_PUBLIC_API_URL || browserOrigin;
export const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || API_BASE.replace(/^http/, "ws");
