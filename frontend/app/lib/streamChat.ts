export type ChatMessage = { role: string; content: string; [key: string]: unknown };

export async function streamChat(
  url: string,
  messages: ChatMessage[],
  onDelta: (text: string) => void,
): Promise<{ model?: string }> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ messages, stream: true }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
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
        else if (eventName === "error") throw new Error(data.error || "LLM streaming hatası");
        else if (eventName === "done") result = data;
      }
      if (chunk.done) break;
    }
  } finally {
    reader.releaseLock();
  }
  return result;
}
