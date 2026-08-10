import { apiRequest } from "./api";

export type ChatMessage = { role: string; content: string; [key: string]: unknown };

export async function streamChat(
  url: string,
  messages: ChatMessage[],
  onDelta: (text: string) => void,
  options: Record<string, unknown> = {},
): Promise<{ model?: string }> {
  const response = await apiRequest(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ messages, stream: true, ...options }),
  });
  if (!response.ok) {
    const raw = await response.text();
    let body: any = {};
    try { body = JSON.parse(raw); } catch { body = { error: raw.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 240) }; }
    throw new Error(body.detail || body.error || `Sunucu hatası (${response.status})`);
  }
  if (!response.body) throw new Error("Streaming bağlantısı başlatılamadı");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: { model?: string } = {};
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
        let data: any;
        try { data = JSON.parse(dataLine); } catch { continue; }
        if (eventName === "delta") onDelta(String(data.text || ""));
        else if (eventName === "error") {
          terminalEvent = true;
          const detail = typeof data.error === "string" ? data.error : data.error?.message || "LLM streaming hatası";
          throw new Error(detail);
        }
        else if (eventName === "done") { terminalEvent = true; result = data; }
      }
      if (chunk.done) break;
    }
  } finally {
    reader.releaseLock();
  }
  if (!terminalEvent) throw new Error("LLM bağlantısı beklenmedik şekilde kapandı; backend/SSE proxy loglarını kontrol edin.");
  return result;
}
