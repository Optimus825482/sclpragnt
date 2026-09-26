import { apiRequest } from "./api";

export type ChatMessage = { role: string; content: string; [key: string]: unknown };

/**
 * SSE olay gövdeleri — `any` yerine kapatılmış (union) tipler.
 *
 * NEDEN (denetim #49): `data: any` olduğunda backend alan adını değiştirirse
 * (ör. `watch_completed` → `watch_done`) derleme hatası VERMEZ, `Number(undefined)`
 * → `NaN` olur ve `NaN` doğrudan UI'a basılır. Kapatma sayesinde backend sözleşme
 * değişikliği tüketiciyi derleme zamanında kırar.
 *
 * Bilinmeyen olaylar `StreamEventUnknown` ile karşılanır: tüketici bunu
 * yutabilir ama alan okumadan önce `as` ile daraltmak zorundadır.
 */
export type StreamDataMap = {
  /** Asistan çıktısının parçası (token). */
  delta: { text?: string };
  /** Akış sonu: model, durum, iz/istatistik. */
  done: {
    model?: string;
    status?: string;
    /** Gözlem tamamlandı mı (fiyat izleme paneli). */
    watch_completed?: boolean;
  };
  /** Gözlem (fiyat takibi) başladı. */
  watch_started: { symbol?: string };
  /** Gözlem sırasında canlı fiyat örneği. */
  price: {
    symbol?: string;
    price?: number | string;
    start_price?: number | string;
    change_pct?: number | string;
    high?: number | string;
    low?: number | string;
    samples?: number | string;
  };
  /** Hata gövdesi: ya düz metin ya LLM hata nesnesi. */
  error: { error?: string | { message?: string } };
  /** Sunucu tarafı araç çağrısı bildirimi (şema taşınmadıkça opak). */
  tool: Record<string, unknown>;
};

export type StreamEventName = keyof StreamDataMap;

/** Bilinen olay: `event` alanı daraltılmış, `data` eşleşen tipte. */
export type StreamEvent<K extends StreamEventName = StreamEventName> = {
  event: K;
  data: StreamDataMap[K];
};

/** Şeması bilinmeyen olay: tüketici `data` alanlarını `as` ile daraltmalı. */
export type StreamEventUnknown = { event: string; data: Record<string, unknown> };

/** Herhangi bir SSE olayı (bilinen veya bilinmeyen). */
export type AnyStreamEvent = StreamEvent | StreamEventUnknown;

/** Serbest ad ile daraltma tablosu — tüketici `as StreamEvent<"price">` yazabilir. */
export type StreamEventFor<K extends StreamEventName> = StreamEvent<K>;

/**
 * Serbest sayı alanı: `NaN`/`Infinity`/`null` → `null`.
 *
 * `Number(x) || 0` deseni "0" ile "veri yok"u birbirine katıyordu ve `NaN`
 * UI'a sızabiliyordu. Burada geçersiz her şey `null` olur; tüketici `—` basar.
 */
export function numOrNull(value: unknown): number | null {
  if (value == null || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** Serbest metin alanı: eksik/`[object Object]` olmayan durumda boş string. */
export function strOrEmpty(value: unknown): string {
  if (value == null) return "";
  return typeof value === "string" ? value : String(value);
}

/** Serbest boolean alanı. */
export function boolOrFalse(value: unknown): boolean {
  return value === true;
}

export async function streamChat(
  url: string,
  messages: ChatMessage[],
  onDelta: (text: string) => void,
  options: Record<string, unknown> = {},
  controls: { signal?: AbortSignal; onEvent?: (event: AnyStreamEvent) => void } = {},
): Promise<{ model?: string; status?: string }> {
  const response = await apiRequest(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ messages, stream: true, ...options }),
    signal: controls.signal,
  });
  if (!response.ok) {
    const raw = await response.text();
    let body: { detail?: string; error?: string } = {};
    try {
      const parsed: unknown = JSON.parse(raw);
      if (parsed && typeof parsed === "object") body = parsed as { detail?: string; error?: string };
    } catch {
      body = { error: raw.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 240) };
    }
    throw new Error(body.detail || body.error || `Sunucu hatası (${response.status})`);
  }
  if (!response.body) throw new Error("Streaming bağlantısı başlatılamadı");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: { model?: string; status?: string } = {};
  let terminalEvent = false;
  try {
    while (true) {
      const chunk = await reader.read();
      buffer += decoder.decode(chunk.value || new Uint8Array(), { stream: !chunk.done });
      const events = buffer.split(/\r?\n\r?\n/);
      buffer = events.pop() || "";
      for (const event of events) {
        const eventName = event.match(/^event:\s*(.+)$/m)?.[1];
        const dataLine = event.match(/^data:\s*(.+)$/m)?.[1];
        if (!dataLine) continue;
        let parsed: unknown;
        try { parsed = JSON.parse(dataLine); } catch { continue; }
        const payload = (parsed && typeof parsed === "object" ? parsed : {}) as Record<string, unknown>;
        const name = (eventName || "message") as StreamEventName | "message";
        // Tüketiciye geçmeden önce olayı şemaya göre daralt: bilinmeyen
        // olaylar opak geçer, `data` alanları `any` DEĞİLDİR.
        const safePayload = sanitizeStreamData(payload);
        if (name === "message") {
          controls.onEvent?.({ event: name, data: safePayload });
        } else {
          controls.onEvent?.({ event: name, data: safePayload as StreamDataMap[StreamEventName] } as StreamEvent);
        }
        if (name === "delta") onDelta(strOrEmpty(safePayload.text));
        else if (name === "error") {
          terminalEvent = true;
          const raw2 = safePayload.error;
          const detail = typeof raw2 === "string"
            ? raw2
            : (raw2 && typeof raw2 === "object" && typeof (raw2 as { message?: unknown }).message === "string"
              ? (raw2 as { message: string }).message
              : "LLM streaming hatası");
          throw new Error(detail);
        } else if (name === "done") {
          terminalEvent = true;
          result = safePayload as { model?: string; status?: string };
        }
      }
      if (chunk.done) break;
    }
  } finally {
    reader.releaseLock();
  }
  if (controls.signal?.aborted) return { status: "cancelled" };
  if (!terminalEvent) throw new Error("LLM bağlantısı beklenmedik şekilde kapandı; backend/SSE proxy loglarını kontrol edin.");
  return result;
}

/**
 * Gövde içindeki sayı-benzeri string/NaN değerlerini güvenli hale getirir.
 * `NaN` JSON'da geçmez ama `Number("abc")` deseni üretmiş JSON'lar olabilir
 * (`{ "price": NaN }` → parse edilemez) — asıl koruma tüketici tarafındaki
 * `numOrNull`. Burada yalnızca derin kopya + tip güvenliği sağlanıyor.
 */
function sanitizeStreamData(data: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(data)) {
    if (typeof v === "number" && !Number.isFinite(v)) {
      out[k] = null; // NaN / ±Infinity → null ("veri yok")
    } else if (v && typeof v === "object" && !Array.isArray(v)) {
      out[k] = sanitizeStreamData(v as Record<string, unknown>);
    } else {
      out[k] = v;
    }
  }
  return out;
}
