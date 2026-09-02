"use client";
import { useMemo, useState } from "react";
import type { IndicatorStyle, RegistryEntry } from "./types";

type Props = {
    entry: RegistryEntry;
    initialParams?: Record<string, any>;
    initialStyle?: IndicatorStyle;
    editing?: boolean;
    onAdd: (params: Record<string, any>, style: IndicatorStyle) => void;
    onClose: () => void;
};

const SOURCE_OPTS = ["close", "open", "high", "low", "volume", "hl2", "hlc3", "ohlc4"];
const SWATCHES = ["#10b981", "#3b82f6", "#f59e0b", "#a855f7", "#ec4899", "#06b6d4", "#84cc16", "#f97316", "#ef4444", "#e5e7eb"];

const DEFAULT_STYLE: IndicatorStyle = {
    colors: ["#10b981", "#3b82f6", "#f59e0b", "#a855f7"],
    lineWidth: 2,
    showPriceLine: true,
    showBounds: true
};

function Toggle({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
    return (
        <button
            onClick={() => onChange(!value)}
            className={`w-10 h-5 rounded-full border transition-colors relative shrink-0 ${value ? "bg-neon-green/30 border-neon-green/50" : "bg-bunker-800 border-bunker-700"}`}
        >
            <span
                className={`absolute top-0.5 w-4 h-4 rounded-full transition-all ${value ? "left-5 bg-neon-green" : "left-0.5 bg-bunker-muted"}`}
            />
        </button>
    );
}

function ParamInput({
    cfg,
    value,
    onChange
}: {
    cfg: any;
    value: any;
    onChange: (v: any) => void;
}) {
    const base =
        "w-full bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white focus:border-neon-green/50 outline-none";

    if (cfg.type === "bool") {
        return <Toggle value={!!value} onChange={onChange} />;
    }

    if (cfg.type === "string" || cfg.type === "source") {
        const opts = cfg.type === "source" ? SOURCE_OPTS : cfg.options || [];
        return (
            <select value={value} onChange={(e) => onChange(e.target.value)} className={base}>
                {opts.map((o: string) => (
                    <option key={o} value={o}>{o}</option>
                ))}
            </select>
        );
    }

    return (
        <input
            type="number"
            value={value}
            min={cfg.min}
            max={cfg.max}
            step={cfg.step || (cfg.type === "float" ? 0.1 : 1)}
            onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
            className={base}
        />
    );
}

// Göstergenin kaç çizgi/histogram çizeceğini gerçek veri olmadan bilmek
// mümkün değil; sentetik örnek mumlarla bir kez hesaplatıp plot sayısını ölç.
// Hesap patlarsa tek çizgi varsay — kullanıcı yine de rengi/kalınlığı değiştirebilir.
function usePlotCount(entry: RegistryEntry): number {
    return useMemo(() => {
        try {
            const sample = Array.from({ length: 60 }, (_, i) => ({
                time: 1_700_000_000 + i * 60,
                open: 100 + i, high: 105 + i, low: 95 + i, close: 102 + i, volume: 1000 + i * 10
            }));
            const result = entry.calculate(sample as any, {});
            const count = Object.values(result?.plots || {}).filter(
                (p: any) => Array.isArray(p) && p.some((pt: any) => pt.value != null && !Number.isNaN(pt.value))
            ).length;
            return Math.max(1, Math.min(6, count));
        } catch {
            return 1;
        }
    }, [entry]);
}

export default function IndicatorSettings({ entry, initialParams, initialStyle, editing, onAdd, onClose }: Props) {
    const [params, setParams] = useState<Record<string, any>>(() =>
        initialParams || Object.fromEntries(entry.inputConfig.map((c) => [c.id, c.defval]))
    );
    const plotCount = usePlotCount(entry);
    const [style, setStyle] = useState<IndicatorStyle>(() =>
        initialStyle
            ? { ...DEFAULT_STYLE, ...initialStyle }
            : {
                ...DEFAULT_STYLE,
                colors: DEFAULT_STYLE.colors.slice(0, Math.max(plotCount, DEFAULT_STYLE.colors.length)),
                lineWidths: Array(Math.max(plotCount, DEFAULT_STYLE.colors.length)).fill(DEFAULT_STYLE.lineWidth)
            }
    );
    // en az plot sayısı kadar satır göster; kayıtlı stilde daha fazla çizgi varsa onları da koru
    const lineCount = Math.max(plotCount, style.colors.length);

    const setColor = (lineIndex: number, color: string) => {
        setStyle((s) => {
            const next = [...s.colors];
            while (next.length <= lineIndex) next.push(DEFAULT_STYLE.colors[next.length % DEFAULT_STYLE.colors.length]);
            next[lineIndex] = color;
            return { ...s, colors: next };
        });
    };
    const setWidth = (lineIndex: number, width: number) => {
        setStyle((s) => {
            const next = [...(s.lineWidths ?? Array(lineCount).fill(s.lineWidth))];
            while (next.length <= lineIndex) next.push(s.lineWidth);
            next[lineIndex] = width;
            return { ...s, lineWidths: next };
        });
    };

    return (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-start justify-center pt-16 px-3" onClick={onClose}>
            <div className="bg-bunker-900 border border-bunker-700 rounded-xl w-full max-w-[480px] min-w-0" onClick={(e) => e.stopPropagation()}>
                <div className="p-4 border-b border-bunker-800 flex justify-between items-center">
                    <div>
                        <p className="font-mono text-sm font-bold text-white">
                            {entry.shortName} {editing && <span className="text-neon-green">— AYARLAR</span>}
                        </p>
                        <p className="text-xs text-bunker-muted">
                            {entry.overlay ? "Grafik üstü (overlay)" : "Ayrı panel (pane)"} · {plotCount} çizgi
                        </p>
                    </div>
                    <button onClick={onClose} className="text-bunker-muted hover:text-white text-lg leading-none">✕</button>
                </div>

                <div className="p-4 space-y-4 max-h-[55vh] overflow-y-auto">
                    {/* GİRİŞLER */}
                    <div className="space-y-3">
                        <p className="eyebrow !text-[10px]">GİRİŞLER</p>
                        {entry.inputConfig.map((c) => (
                            <div key={c.id}>
                                <p className="font-mono text-[11px] text-bunker-muted mb-1">{c.title}</p>
                                <ParamInput cfg={c} value={params[c.id]} onChange={(v) => setParams((p) => ({ ...p, [c.id]: v }))} />
                            </div>
                        ))}
                    </div>

                    {/* STİL */}
                    <div className="border-t border-bunker-800 pt-4 space-y-3">
                        <p className="eyebrow !text-[10px]">STİL</p>

                        {/* çizgi bazlı renk + kalınlık: her çizgi kendi kutusunda */}
                        <div className="space-y-2">
                            {Array.from({ length: lineCount }, (_, li) => (
                                <div key={li} className="rounded-lg border border-bunker-800 bg-bunker-950/60 p-2.5 space-y-1.5">
                                    <p className="font-mono text-[11px] font-bold text-neon-green">
                                        {plotCount > 1 ? `ÇİZGİ ${li + 1}` : entry.shortName.toUpperCase()}
                                    </p>
                                    <div>
                                        <p className="font-mono text-[11px] text-bunker-muted mb-1">Renk</p>
                                        <div className="flex flex-wrap items-center gap-1.5">
                                            {SWATCHES.map((c) => (
                                                <button
                                                    key={c}
                                                    onClick={() => setColor(li, c)}
                                                    className={`w-5 h-5 rounded-full border-2 transition-transform ${(style.colors[li] || "") === c ? "border-white scale-110" : "border-transparent hover:scale-110"}`}
                                                    style={{ backgroundColor: c }}
                                                    title={c}
                                                />
                                            ))}
                                            <input
                                                type="color"
                                                value={/^#[0-9a-fA-F]{6}$/.test(style.colors[li] || "") ? style.colors[li] : "#10b981"}
                                                onChange={(e) => setColor(li, e.target.value)}
                                                title="Özel renk"
                                                aria-label={`Çizgi ${li + 1} özel renk`}
                                                className="h-5 w-8 cursor-pointer rounded border border-bunker-700 bg-transparent"
                                            />
                                        </div>
                                    </div>
                                    <div className="flex justify-between items-center">
                                        <p className="font-mono text-[11px] text-bunker-muted">Kalınlık</p>
                                        <select
                                            value={String(style.lineWidths?.[li] ?? style.lineWidth)}
                                            onChange={(e) => setWidth(li, Number(e.target.value))}
                                            className="bg-bunker-950 border border-bunker-700 rounded px-2 py-0.5 font-mono text-sm text-white focus:border-neon-green/50 outline-none"
                                        >
                                            {[1, 2, 3, 4].map((w) => <option key={w} value={w}>{w}</option>)}
                                        </select>
                                    </div>
                                </div>
                            ))}
                        </div>

                        <div className="flex justify-between items-center">
                            <p className="font-mono text-[11px] text-bunker-muted">Fiyat Çizgisi</p>
                            <Toggle value={style.showPriceLine} onChange={(v) => setStyle((s) => ({ ...s, showPriceLine: v }))} />
                        </div>

                        <div className="flex justify-between items-center">
                            <p className="font-mono text-[11px] text-bunker-muted">Min / Max Bantları</p>
                            <Toggle value={style.showBounds} onChange={(v) => setStyle((s) => ({ ...s, showBounds: v }))} />
                        </div>

                        <div className="grid grid-cols-2 gap-2">
                            <div>
                                <p className="font-mono text-[11px] text-bunker-muted mb-1">Min değer</p>
                                <input
                                    type="number"
                                    value={style.minValue ?? ""}
                                    onChange={(e) => setStyle((s) => ({ ...s, minValue: e.target.value === "" ? null : Number(e.target.value) }))}
                                    className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white focus:border-neon-green/50 outline-none"
                                />
                            </div>
                            <div>
                                <p className="font-mono text-[11px] text-bunker-muted mb-1">Max değer</p>
                                <input
                                    type="number"
                                    value={style.maxValue ?? ""}
                                    onChange={(e) => setStyle((s) => ({ ...s, maxValue: e.target.value === "" ? null : Number(e.target.value) }))}
                                    className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white focus:border-neon-green/50 outline-none"
                                />
                            </div>
                        </div>
                    </div>
                </div>

                <div className="p-4 border-t border-bunker-800 flex justify-end gap-2">
                    <button onClick={onClose} className="px-4 py-2 rounded-lg border border-bunker-700 font-mono text-sm text-bunker-muted hover:text-white">
                        İPTAL
                    </button>
                    <button
                        onClick={() => onAdd(params, style)}
                        className="px-5 py-2 rounded-lg bg-neon-green/15 border border-neon-green/40 font-mono text-sm text-neon-green hover:bg-neon-green/25"
                    >
                        {editing ? "UYGULA" : "EKLE"}
                    </button>
                </div>
            </div>
        </div>
    );
}
