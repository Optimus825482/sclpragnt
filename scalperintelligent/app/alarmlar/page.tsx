"use client";

import { useState } from "react";
import { apiRequest } from "../lib/api";
import { usePoll } from "../lib/hooks";
import { fmtDateTime, formatPrice } from "../lib/format";
import { useAuth } from "../lib/auth";
import { Badge, Card, EmptyState, SectionHeader, Skeleton } from "../components/ui";

type AlertRule = {
  id: number;
  symbol: string;
  rule_type: string;
  operator: string;
  threshold: number;
  rearm_threshold?: number | null;
  cooldown_seconds?: number | null;
  active?: boolean;
  created_by?: string;
};
type AlertEvent = { id?: number; rule_id?: number; symbol?: string; message?: string; created_at?: number };
type AlertsResponse = { alerts: AlertRule[]; events: AlertEvent[]; paper_only: boolean };

const OPERATORS: Array<{ id: string; label: string }> = [
  { id: "gte", label: "≥ üstüne çıkarsa" },
  { id: "gt", label: "> büyükse" },
  { id: "lte", label: "≤ altına inerse" },
  { id: "lt", label: "< küçükse" },
  { id: "eq", label: "= eşitse" },
];

function operatorLabel(op: string) {
  return OPERATORS.find((item) => item.id === op)?.label || op;
}

/** Fiyat alarmları: kural listesi + oluştur/sil. Oluşturma backend'de admin kapılıdır. */
export default function AlarmlarPage() {
  const { role } = useAuth();
  const isAdmin = String(role).toLowerCase() === "admin";
  const alerts = usePoll<AlertsResponse>("/api/alerts", 20_000);
  const [symbol, setSymbol] = useState("");
  const [operator, setOperator] = useState("gte");
  const [threshold, setThreshold] = useState("");
  const [ruleType, setRuleType] = useState("price");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "gain" | "loss"; text: string } | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);

  async function createAlert() {
    if (!symbol.trim() || !Number(threshold)) {
      setMessage({ tone: "loss", text: "Sembol ve eşik değeri gerekli." });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const response = await apiRequest("/api/alerts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: symbol.trim().toUpperCase(),
          operator,
          threshold: Number(threshold),
          rule_type: ruleType,
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body?.detail || `Alarm oluşturulamadı (${response.status})`);
      setMessage({ tone: "gain", text: "Alarm kuralı oluşturuldu." });
      setSymbol("");
      setThreshold("");
      alerts.reload();
    } catch (reason) {
      setMessage({ tone: "loss", text: reason instanceof Error ? reason.message : "Alarm oluşturulamadı" });
    } finally {
      setBusy(false);
    }
  }

  async function deleteAlert(id: number) {
    setBusy(true);
    try {
      const response = await apiRequest(`/api/alerts/${id}`, { method: "DELETE" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body?.detail || `Alarm silinemedi (${response.status})`);
      alerts.reload();
    } catch (reason) {
      setMessage({ tone: "loss", text: reason instanceof Error ? reason.message : "Alarm silinemedi" });
    } finally {
      setBusy(false);
      setDeleting(null);
    }
  }

  const rules = alerts.data?.alerts || [];
  const events = alerts.data?.events || [];

  return <div className="space-y-5">
    <SectionHeader
      eyebrow="Fiyat Alarmları"
      title="Alarm kuralları ve tetiklenen olaylar"
      description="Belirli fiyat/percent eşiğine ulaşan semboller bildirim üretir. Alarm kurma ve silme yönetici yetkisi gerektirir."
    />

    {message && <div role="status" className={`rounded-xl border p-3 text-sm ${message.tone === "gain" ? "border-gain/30 bg-gain-soft/40 text-gain" : "border-loss/30 bg-loss-soft/40 text-loss"}`}>{message.text}</div>}

    <Card className="p-4">
      <p className="odak-kicker">Yeni alarm kuralı</p>
      {!isAdmin && <p className="mt-1 text-[11px] text-warn">Alarm oluşturmak/silmek için yönetici oturumu gerekir. Kuralları görüntüleyebilirsiniz.</p>}
      <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_auto_1fr_auto]">
        <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} placeholder="BTC_TRY" aria-label="Sembol" className="rounded-lg border border-line bg-white px-3 py-2 font-mono text-sm text-ink-900 outline-none focus:border-accent" />
        <select value={operator} onChange={(e) => setOperator(e.target.value)} aria-label="Koşul" className="rounded-lg border border-line bg-white px-2 py-2 text-sm text-ink-900">
          {OPERATORS.map((op) => <option key={op.id} value={op.id}>{op.label}</option>)}
        </select>
        <input value={threshold} onChange={(e) => setThreshold(e.target.value.replace(/[^\d.]/g, ""))} inputMode="decimal" placeholder={ruleType === "price" ? "4.200.000" : "% 5"} aria-label="Eşik" className="rounded-lg border border-line bg-white px-3 py-2 font-mono text-sm text-ink-900 outline-none focus:border-accent" />
        <div className="flex gap-2">
          <select value={ruleType} onChange={(e) => setRuleType(e.target.value)} aria-label="Tür" className="rounded-lg border border-line bg-white px-2 py-2 text-sm text-ink-900">
            <option value="price">Fiyat</option>
            <option value="percent">Değişim %</option>
          </select>
          <button type="button" disabled={busy || !isAdmin} onClick={createAlert} className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">Ekle</button>
        </div>
      </div>
    </Card>

    {alerts.loading && !alerts.data ? <Skeleton className="h-40" /> : alerts.error && !alerts.data ? (
      <EmptyState title="Alarmlar alınamadı" hint={alerts.error} tone="loss" />
    ) : rules.length === 0 ? (
      <EmptyState title="Alarm kuralı yok" hint="Henüz hiç fiyat alarmı tanımlanmamış." />
    ) : (
      <Card className="p-4">
        <div className="odak-scroll"><table className="w-full min-w-[640px] border-collapse text-sm">
          <thead><tr className="text-left text-[11px] uppercase tracking-wide text-ink-400">
            <th className="pb-2 pr-3 font-medium">Sembol</th><th className="pb-2 pr-3 font-medium">Koşul</th>
            <th className="pb-2 pr-3 text-right font-medium">Eşik</th><th className="pb-2 pr-3 font-medium">Durum</th>
            <th className="pb-2 pr-3 font-medium">Kural No</th><th className="pb-2 font-medium">İşlem</th>
          </tr></thead>
          <tbody>{rules.map((rule) => {
            const pct = rule.rule_type === "percent";
            return <tr key={rule.id} className="border-t border-line">
              <td className="py-2 pr-3 font-mono font-semibold text-ink-900">{rule.symbol}</td>
              <td className="py-2 pr-3 text-xs text-ink-600">{operatorLabel(rule.operator)}{pct ? " (değişim %)" : ""}</td>
              <td className="py-2 pr-3 text-right font-mono text-ink-700">{pct ? `%${rule.threshold}` : formatPrice(rule.threshold)}</td>
              <td className="py-2 pr-3"><Badge tone={rule.active === false ? "neutral" : "gain"}>{rule.active === false ? "PASİF" : "AKTİF"}</Badge></td>
              <td className="py-2 pr-3 font-mono text-xs text-ink-400">#{rule.id}</td>
              <td className="py-2">
                {deleting === rule.id ? (
                  <div className="flex items-center gap-1.5">
                    <button type="button" disabled={busy || !isAdmin} onClick={() => deleteAlert(rule.id)} className="rounded-md bg-loss px-2.5 py-1 text-[11px] font-semibold text-white disabled:opacity-50">Onayla</button>
                    <button type="button" onClick={() => setDeleting(null)} className="rounded-md border border-line px-2 py-1 text-[11px] text-ink-500">Vazgeç</button>
                  </div>
                ) : (
                  <button type="button" disabled={!isAdmin} onClick={() => setDeleting(rule.id)} className="rounded-md border border-loss/40 px-2.5 py-1 text-[11px] font-semibold text-loss hover:bg-loss-soft disabled:opacity-40" title={isAdmin ? "Kuralı sil" : "Yönetici yetkisi gerekir"}>Sil</button>
                )}
              </td>
            </tr>;
          })}</tbody>
        </table></div>
      </Card>
    )}

    <Card className="p-4">
      <p className="odak-kicker">Son tetiklenen olaylar</p>
      {events.length === 0 ? (
        <p className="mt-2 text-xs text-ink-400">Henüz tetiklenen alarm olayı yok.</p>
      ) : (
        <ul className="mt-2 space-y-1.5 text-xs">
          {events.slice(0, 20).map((event, i) => (
            <li key={event.id ?? i} className="flex items-center justify-between gap-3 rounded-lg bg-canvas px-3 py-2">
              <span className="font-mono font-semibold text-ink-900">{event.symbol || "—"}</span>
              <span className="min-w-0 flex-1 truncate text-ink-500">{event.message || ""}</span>
              <span className="shrink-0 font-mono text-[10px] text-ink-400">{event.created_at ? fmtDateTime(event.created_at) : ""}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  </div>;
}
