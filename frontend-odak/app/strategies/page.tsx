"use client";

import { Badge, Card, EmptyState, SectionHeader, Skeleton } from "../components/ui";
import { usePoll } from "../lib/hooks";
import type { PipelineEntry, PipelineResponse } from "../lib/types";
import { fmtDateTime } from "../lib/format";

/** Promosyon hattı aşamasına göre rozet tonu. */
function stageTone(stage: string): "gain" | "accent" | "warn" | "neutral" {
  const s = stage.toLowerCase();
  if (s === "active") return "gain";
  if (s.includes("paper") || s === "shadow") return "accent";
  if (s.includes("promot")) return "warn";
  return "neutral";
}

export default function StrategiesPage() {
  const { data, error, loading } = usePoll<PipelineResponse>("/api/strategy/pipeline", 30_000);
  const entries: Array<[string, PipelineEntry]> = Object.entries(data?.strategies ?? {});

  return (
    <div className="space-y-5">
      <SectionHeader
        eyebrow="Stratejiler"
        title="Promosyon hattı"
        description="Stratejilerin gölge → paper → aktif aşama durumu."
      />

      {loading && !data ? (
        <Skeleton className="h-40" />
      ) : error && !data ? (
        <EmptyState title="Strateji durumu alınamadı" hint={error} tone="loss" />
      ) : entries.length === 0 ? (
        <EmptyState title="Kayıtlı strateji yok" hint="Promosyon hattına henüz strateji kaydedilmemiş." />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {entries.map(([name, entry]) => (
            <Card key={name} className="p-4">
              <div className="flex items-start justify-between gap-2">
                <h3 className="font-mono text-sm font-semibold text-ink-900">{name}</h3>
                <Badge tone={stageTone(entry.stage)}>{entry.stage}</Badge>
              </div>
              <p className="mt-2 text-xs text-ink-400">Güncellendi: {fmtDateTime(entry.updated_at)}</p>

              {entry.evidence && Object.keys(entry.evidence).length > 0 && (
                <dl className="mt-3 space-y-1 text-xs">
                  {Object.entries(entry.evidence).slice(0, 5).map(([k, v]) => (
                    <div key={k} className="flex items-center justify-between gap-2 border-t border-line/70 pt-1">
                      <dt className="text-ink-500">{k}</dt>
                      <dd className="font-mono text-ink-700">{typeof v === "number" ? v.toLocaleString("tr-TR") : String(v)}</dd>
                    </div>
                  ))}
                </dl>
              )}

              {entry.transitions && entry.transitions.length > 0 && (
                <p className="mt-3 text-[11px] text-ink-400">
                  {entry.transitions.length} geçiş · son: {entry.transitions[entry.transitions.length - 1]?.to}
                </p>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
