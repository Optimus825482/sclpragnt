"use client";
import React, { useState, useRef, useEffect } from "react";
import { streamChat } from "../lib/streamChat";
import { API_BASE } from "../lib/api";

interface Message {
  role: "user" | "assistant";
  content: string;
  time: string;
}

interface ChartAssistantDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  /** Verilmezse genel asistan modu (grafik dışı sayfalar). */
  symbol?: string;
  currentPrice?: number | null;
}

const SYMBOL_PROMPTS = [
  { label: "📊 Genel Durum", query: "Bu coinde şu an genel durum nedir? Yükselme isteği var mı?" },
  { label: "🎯 Tahmin Motoru", query: "Sistemin Master Surge ve ML tahmin motorları bu coin için ne öngörüyor?" },
  { label: "🐋 Büyük Alıcılar", query: "Büyük cüzdanlar veya balinalar tahtada aktif mi, alım mı satım mı yapıyorlar?" },
  { label: "⚡ Vadeli Pozisyonlar", query: "Vadeli piyasada durum ne, yatırımcılar aşırı long mu açmış, fonlama ve açık pozisyon ne söylüyor?" },
  { label: "🌐 Piyasa & Bitcoin", query: "Kripto piyasasında genel hava, korku endeksi ve Bitcoin'in yönü bu coini nasıl etkiliyor?" },
  { label: "⚠️ Alım Riski", query: "Şu an bu seviyeden pozisyon almak güvenli mi yoksa riskli mi, neyi beklemeliyim?" },
];

// Sembolsüz (genel) mod: grafik dışı sayfalarda gösterilen hızlı sorular.
const GENERAL_PROMPTS = [
  { label: "📡 Şu an öne çıkan coinler", query: "Şu an radarda öne çıkan coinler hangileri, neden öne çıkıyorlar?" },
  { label: "🌐 Piyasa & Bitcoin", query: "Kripto piyasasında genel hava, korku endeksi ve Bitcoin'in yönü nasıl?" },
  { label: "📊 Bugünkü bildirimler nasıl gitti?", query: "Bugün gelen radar bildirimleri nasıl sonuçlandı, hedefe ulaşanlar ve ulaşamayanlar neler?" },
  { label: "⚠️ Şu an alım yapmak riskli mi?", query: "Şu an genel olarak alım yapmak güvenli mi yoksa riskli mi, neye dikkat etmeliyim?" },
];

const nowHHMM = () => new Date().toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });

const GENERAL_WELCOME =
  "Merhaba! Piyasa, radar bildirimleri, portföyün ve coinler hakkında sade bir dille soru sorabilirsin. Teknik terimlerle kafanı karıştırmadan anlık durumu özetleyebilirim. Aşağıdaki hızlı sorulardan birini seçebilir veya aklındakini yazabilirsin.";

export default function ChartAssistantDrawer({
  isOpen,
  onClose,
  symbol,
  currentPrice,
}: ChartAssistantDrawerProps) {
  const quickPrompts = symbol ? SYMBOL_PROMPTS : GENERAL_PROMPTS;
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content: !symbol
        ? GENERAL_WELCOME
        : `Merhaba! Şu an **${symbol}** grafiğini inceliyorsun. Sistemin tüm tahmin motorları (Master Surge, ML hedef, balina akışı) bağlı. Tamamen sade bir dille, teknik terimlerle kafanı karıştırmadan anlık durumu özetleyebilirim. Aşağıdaki hızlı sorulardan birini seçebilir veya aklındakini yazabilirsin.`,
      time: nowHHMM(),
    },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Sembol değiştiğinde hoşgeldin mesajı ekle
  const prevSymbolRef = useRef(symbol);
  useEffect(() => {
    if (prevSymbolRef.current !== symbol) {
      prevSymbolRef.current = symbol;
      // Sembol kalktıysa (genel moda geçiş) ya da tanımsızsa ek mesaj yok.
      if (!symbol) return;
      const nowTime = new Date().toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `Grafikte **${symbol}** sembolüne geçtin. Bu coin için ne öğrenmek istersin?`,
          time: nowTime,
        },
      ]);
    }
  }, [symbol]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  const sendMessage = async (textToSend?: string) => {
    const text = (textToSend || input).trim();
    if (!text || busy) return;

    const nowTime = new Date().toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
    const userMsg: Message = { role: "user", content: text, time: nowTime };
    const nextMessages = [...messages, userMsg];

    setMessages(nextMessages);
    setInput("");
    setBusy(true);
    setError("");

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      // Boş bir asistan mesajı ekle
      setMessages([...nextMessages, { role: "assistant", content: "", time: nowTime }]);

      // Token optimizasyonu: Bağlam şişmesini ve aşırı maliyeti önlemek için son 6 mesajı gönder
      const boundedContext = nextMessages.slice(-6).map((m) => ({ role: m.role, content: m.content }));

      await streamChat(
        `${API_BASE}/api/strategies/llm/chat`,
        boundedContext,
        (delta) => {
          setMessages((current) => {
            const last = current[current.length - 1];
            if (!last || last.role !== "assistant") return current;
            return [
              ...current.slice(0, -1),
              {
                ...last,
                content: last.content + delta,
              },
            ];
          });
        },
        {
          plain_turkish: true,
          chart_assistant: true,
          // Backend `symbol` okur; eski istemci/sürümler için `current_symbol` da gönderilir.
          ...(symbol ? { symbol, current_symbol: symbol } : {}),
          max_tokens: 4096,
        },
        {
          signal: controller.signal,
        }
      );
    } catch (err: any) {
      if (err.name !== "AbortError") {
        setError(err.message || "Asistan yanıt veremedi");
      }
    } finally {
      setBusy(false);
      abortControllerRef.current = null;
    }
  };

  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
  };

  const clearMessages = () => {
    const nowTime = new Date().toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
    setMessages([
      {
        role: "assistant",
        content: symbol
          ? `Sohbet temizlendi. **${symbol}** hakkında sormak istediğin bir şey var mı?`
          : "Sohbet temizlendi. Sormak istediğin bir şey var mı?",
        time: nowTime,
      },
    ]);
    setError("");
  };

  if (!isOpen) return null;

  return (
    <div className="fixed bottom-16 md:bottom-4 right-3 md:right-4 z-[95] flex flex-col w-[94vw] sm:w-[440px] h-[580px] max-h-[75vh] md:max-h-[85vh] rounded-2xl border border-cyan-500/40 bg-bunker-950/95 backdrop-blur-md shadow-2xl shadow-cyan-950/50 overflow-hidden animate-in fade-in slide-in-from-bottom-5 duration-200">
      {/* Üst Başlık Çubuğu */}
      <div className="flex items-center justify-between border-b border-bunker-800/80 bg-bunker-900/60 px-4 py-3 shrink-0">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-cyan-500/20 text-cyan-400 font-bold text-base border border-cyan-500/30 shadow-inner">
            🤖
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm font-bold text-white tracking-wide">
                {symbol || "Asistan"}
              </span>
              {symbol && currentPrice != null && (
                <span className="text-xs font-mono text-neon-green font-semibold">
                  ₺{currentPrice.toLocaleString("tr-TR")}
                </span>
              )}
            </div>
            <p className="text-[10px] text-cyan-300 font-medium truncate">
              {symbol ? "Grafik Asistanı" : "Genel Asistan"} · Sade Dil Modu (Teknik terimsiz)
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={clearMessages}
            title="Sohbeti Temizle"
            className="p-1.5 text-xs text-bunker-muted hover:text-white rounded-lg hover:bg-bunker-800 transition-colors"
          >
            🧹
          </button>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 text-sm text-bunker-muted hover:text-white rounded-lg hover:bg-bunker-800 transition-colors"
            aria-label="Kapat"
          >
            ✕
          </button>
        </div>
      </div>

      {/* Mesaj Listesi */}
      <div className="flex-1 overflow-y-auto p-3.5 space-y-3 font-sans text-xs">
        {messages.map((m, idx) => {
          const isUser = m.role === "user";
          return (
            <div
              key={idx}
              className={`flex flex-col ${isUser ? "items-end" : "items-start"}`}
            >
              <div
                className={`max-w-[88%] rounded-2xl px-3.5 py-2.5 leading-relaxed shadow-sm ${
                  isUser
                    ? "bg-cyan-600 text-[#ffffff] rounded-br-xs font-medium"
                    : "bg-bunker-900/90 text-bunker-100 border border-bunker-800/80 rounded-bl-xs"
                }`}
              >
                <div className="whitespace-pre-wrap break-words">{m.content}</div>
              </div>
              <span className="text-[9px] text-bunker-500 mt-1 px-1">{m.time}</span>
            </div>
          );
        })}

        {busy && (
          <div className="flex items-center gap-1.5 text-cyan-400 bg-bunker-900/50 border border-bunker-800 rounded-xl px-3 py-2 w-fit">
            <span className="inline-block h-2 w-2 rounded-full bg-cyan-400 animate-pulse" />
            <span className="inline-block h-2 w-2 rounded-full bg-cyan-400 animate-pulse delay-75" />
            <span className="inline-block h-2 w-2 rounded-full bg-cyan-400 animate-pulse delay-150" />
            <span className="text-[11px] text-bunker-muted ml-1">İnceleniyor...</span>
          </div>
        )}

        {error && (
          <div className="p-2.5 rounded-xl bg-neon-red/10 border border-neon-red/30 text-neon-red text-xs">
            ⚠️ {error}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Hızlı Butonlar */}
      <div className="p-2 bg-bunker-900/40 border-t border-bunker-800/60 shrink-0">
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 no-scrollbar">
          {quickPrompts.map((qp, i) => (
            <button
              key={i}
              type="button"
              disabled={busy}
              onClick={() => sendMessage(qp.query)}
              className="shrink-0 px-2.5 py-1 text-[11px] font-medium rounded-lg bg-bunker-800/80 hover:bg-cyan-950/60 hover:text-cyan-300 hover:border-cyan-500/40 border border-bunker-700/60 text-bunker-200 transition-all disabled:opacity-50"
            >
              {qp.label}
            </button>
          ))}
        </div>
      </div>

      {/* Mesaj Yazma Alanı */}
      <div className="p-2.5 border-t border-bunker-800/80 bg-bunker-950 shrink-0">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            sendMessage();
          }}
          className="flex items-center gap-2"
        >
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={symbol ? `${symbol} hakkında bir soru sor...` : "Bir soru sor…"}
            disabled={busy}
            className="flex-1 rounded-xl border border-bunker-800 bg-bunker-900/80 px-3.5 py-2 text-xs text-white placeholder:text-slate-500 focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500/50 disabled:opacity-50"
          />

          {busy ? (
            <button
              type="button"
              onClick={handleStop}
              className="rounded-xl border border-red-500/40 bg-red-500/20 px-3 py-2 text-xs font-semibold text-red-300 hover:bg-red-500/30 transition-colors"
            >
              Durdur
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim()}
              className="rounded-xl border border-cyan-500/40 bg-cyan-600/80 hover:bg-cyan-500 px-3.5 py-2 text-xs font-semibold text-[#ffffff] transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-md shadow-cyan-900/30"
            >
              Gönder
            </button>
          )}
        </form>
      </div>
    </div>
  );
}
