"use client";
import { useState } from "react";
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
        return (
            <Toggle value={!!value} onChange={onChange} />
        );
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

export default function IndicatorSettings({ entry, initialParams, initialStyle, editing, onAdd, onClose }: Props) {
    const [params, setParams] = useState<Record<string, any>>(() =>
        initialParams || Object.fromEntries(entry.inputConfig.map((c) => [c.id, c.defval]))
    );
    const [style, setStyle] = useState<IndicatorStyle>(initialStyle || DEFAULT_STYLE);
    const [activeColor, setActiveColor] = useState(0);

    return (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-start justify-center pt-16" onClick={onClose}>
            <div className="bg-bunker-900 border border-bunker-700 rounded-xl w-[440px] max-w-[95vw]" onClick={(e) => e.stopPropagation()}>
                <div className="p-4 border-b border-bunker-800 flex justify-between items-center">
                    <div>
                        <p className="font-mono text-sm font-bold text-white">
                            {entry.shortName} {editing && <span className="text-neon-green">— AYARLAR</span>}
                        </p>
                        <p className="text-xs text-bunker-muted">{entry.overlay ? "Grafik üstü (overlay)" : "Ayrı panel (pane)"}</p>
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

                        <div>
                            <p className="font-mono text-[11px] text-bunker-muted mb-1.5">Renk</p>
                            <div className="flex flex-wrap gap-1.5">
                                {SWATCHES.map((c, i) => (
                                    <button
                                        key={c}
                                        onClick={() => {
                                            setActiveColor(i);
                                            setStyle((s) => ({ ...s, colors: s.colors.map((_, ci) => (ci === 0 ? c : _)) }));
                                        }}
                                        className={`w-6 h-6 rounded-full border-2 transition-transform ${style.colors[0] === c ? "border-white scale-110" : "border-transparent hover:scale-110"}`}
                                        style={{ backgroundColor: c }}
                                        title={c}
                                    />
                                ))}
                            </div>
                        </div>

                        <div className="flex justify-between items-center">
                            <p className="font-mono text-[11px] text-bunker-muted">Çizgi Kalınlığı</p>
                            <select
                                value={style.lineWidth}
                                onChange={(e) => setStyle((s) => ({ ...s, lineWidth: Number(e.target.value) }))}
                                className="bg-bunker-950 border border-bunker-700 rounded-lg px-2 py-1 font-mono text-sm text-white focus:border-neon-green/50 outline-none"
                            >
                                {[1, 2, 3, 4].map((w) => (
                                    <option key={w} value={w}>{w}</option>
                                ))}
                            </select>
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
