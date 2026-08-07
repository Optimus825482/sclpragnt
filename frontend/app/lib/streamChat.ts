import { API_BASE } from "./api";

export type ChatMessage = { role: string; content: string; [key: string]: unknown };

export async function streamChat(
  url: string,
  messages: ChatMessage[],
  onDelta: (text: string) => void,
  options: Record<string, unknown> = {},
): Promise<{ model?: string }> {
  const last = (messages[messages.length - 1]?.content || "").toLocaleLowerCase("tr-TR").replace(/[ıİ]/g, "i").replace(/[şŞ]/g, "s");
  if (/\b(islem|pozisyon)\s+a[çc]\b|\ba[çc]\s+islem\b/.test(last)) {
    const action = await fetch(`${API_BASE}/api/llm/paper-trade`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const body = await action.json().catch(() => ({}));
    if (!action.ok) {
      const detail = typeof body.detail === "string" ? body.detail : body.detail?.message
        ? `${body.detail.message}${(body.detail.blocked_candidates || body.detail.top_ranked || []).length ? "\n\nElenen adaylar:\n" + (body.detail.blocked_candidates || body.detail.top_ranked).slice(0, 8).map((x: any) => `- ${x.symbol || "—"}: ${x.reason || (x.risks || []).join(", ") || "bilinmiyor"}`).join("\n") : ""}`
        : body.error || "Paper işlem açılamadı";
      throw new Error(detail);
    }
    const signal = body.signal || {};
    onDelta(`### Paper işlem açıldı\n\n- **Sembol:** \`${signal.symbol || "—"}\`\n- **Yön:** ${signal.side || "LONG"}\n- **Giriş:** \`${signal.entry_price || "—"}\`\n- **Durum:** Mevcut risk ve paper-trading kuralları geçti.\n\nBu gerçek emir değildir; sanal portföye kaydedildi.`);
    return { model: "paper-risk-engine" };
  }
  const response = await fetch(url, {
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
        const data = JSON.parse(dataLine);
        if (eventName === "delta") onDelta(String(data.text || ""));
        else if (eventName === "error") {
          const detail = typeof data.error === "string" ? data.error : data.error?.message || "LLM streaming hatası";
          throw new Error(detail);
        }
        else if (eventName === "done") result = data;
      }
      if (chunk.done) break;
    }
  } finally {
    reader.releaseLock();
  }
  return result;
}
