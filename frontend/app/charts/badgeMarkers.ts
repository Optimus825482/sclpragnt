/**
 * 2026-10-18: Rozet (badge) tarzı sinyal işaretleri — lightweight-charts seri primitive'i.
 *
 * Seri marker'larının (ok + yazı) ölçeği ayarlanamıyor ve büyütülünce grafiği kaplıyordu. Bu primitive,
 * mumun altına/üstüne SABİT piksel boyutunda (zoom'dan bağımsız) yuvarlak köşeli bir rozet çizer:
 * dolu zemin, beyaz kalın yazı ("BUY"), muma bakan küçük üçgen uç. Koordinatlar `update()` içinde
 * (fiyat→y, zaman→x) hesaplanır; çizim CSS piksel uzayında yapılır (DPR'ye göre otomatik ölçek).
 */
import type {
    IChartApi, IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesApi, ISeriesPrimitive, SeriesAttachedParameter, SeriesType, Time,
} from "lightweight-charts";
import type { Bar, StrategySignal } from "./signals";

export type Badge = { time: number; price: number; text: string; bg: string; fg: string; above: boolean };

type DrawTarget = Parameters<IPrimitivePaneRenderer["draw"]>[0];
export type Placed = { x: number; y: number; text: string; bg: string; fg: string; above: boolean };

// 2026-10-18 (kullanıcı örneği): TradingView "label.up" tarzı — köşeleri hafif yuvarlak DİKDÖRTGEN kutu,
// üstünde muma bakan belirgin üçgen uç, kalın beyaz yazı, düz yeşil zemin.
export const BADGE_H = 28;
export const BADGE_PAD_X = 10;
export const BADGE_GAP = 8;       // mum ucu ile üçgen ucu arası (px)
export const BADGE_TIP = 9;       // muma bakan üçgen uç yüksekliği (px)
export const BADGE_RADIUS = 3;    // köşe yarıçapı (px)
export const BADGE_MIN_W = 44;
export const BADGE_FONT = "bold 13px -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif";

/** Saf: strateji sinyali + mum → rozet (alış altta yeşil, satış üstte kırmızı). `badge` istemeyen sinyal → null. */
export function badgeFromSignal(s: StrategySignal, bar: Bar | undefined): Badge | null {
    if (!s.badge || !bar) return null;
    const buy = s.type !== "sell";
    const text = (s.text && s.text.trim()) || (buy ? "BUY" : "SELL");
    return {
        time: s.time,
        price: buy ? Number(bar.low) : Number(bar.high),
        text,
        bg: s.color ?? (buy ? "#16a34a" : "#dc2626"),
        fg: "#ffffff",
        above: !buy,
    };
}

/** Saf: metin genişliğinden rozet kutusu (x merkezli). */
export function badgeBox(textWidth: number, x: number, yEdge: number, above: boolean) {
    const w = Math.max(BADGE_MIN_W, Math.round(textWidth + BADGE_PAD_X * 2));
    const left = Math.round(x - w / 2);
    // above=true → rozet mumun ÜSTÜNDE (kutu yEdge − gap − tip − h … yEdge − gap − tip)
    const top = above ? yEdge - BADGE_GAP - BADGE_TIP - BADGE_H : yEdge + BADGE_GAP + BADGE_TIP;
    return { left, top, w, h: BADGE_H };
}

/** Çizim çekirdeği (test edilebilir): CSS piksel uzayındaki 2D bağlama rozetleri çizer; görünür alan dışı atlanır. */
export function drawBadges(ctx: CanvasRenderingContext2D, items: readonly Placed[], mediaWidth: number): number {
    let drawn = 0;
    ctx.save();
    ctx.font = BADGE_FONT;
    ctx.textBaseline = "middle";
    ctx.textAlign = "center";
    for (const it of items) {
        if (!Number.isFinite(it.x) || !Number.isFinite(it.y)) continue;
        if (it.x < -40 || it.x > mediaWidth + 40) continue;
        const tw = ctx.measureText(it.text).width;
        const box = badgeBox(tw, it.x, it.y, it.above);
        const r = BADGE_RADIUS;
        const { left, top, w, h } = box;
        // gövde (köşeleri hafif yuvarlak dikdörtgen) + muma bakan üçgen uç, TEK yol
        const tipBaseY = it.above ? top + h : top;
        const tipY = it.above ? tipBaseY + BADGE_TIP : tipBaseY - BADGE_TIP;
        const halfTip = Math.min(BADGE_TIP, w / 2 - r - 1);
        ctx.beginPath();
        ctx.moveTo(left + r, top);
        if (!it.above) {   // uç üstte (alış rozeti mumun altında)
            ctx.lineTo(it.x - halfTip, top);
            ctx.lineTo(it.x, tipY);
            ctx.lineTo(it.x + halfTip, top);
        }
        ctx.lineTo(left + w - r, top);
        ctx.quadraticCurveTo(left + w, top, left + w, top + r);
        ctx.lineTo(left + w, top + h - r);
        ctx.quadraticCurveTo(left + w, top + h, left + w - r, top + h);
        if (it.above) {    // uç altta (satış rozeti mumun üstünde)
            ctx.lineTo(it.x + halfTip, top + h);
            ctx.lineTo(it.x, tipY);
            ctx.lineTo(it.x - halfTip, top + h);
        }
        ctx.lineTo(left + r, top + h);
        ctx.quadraticCurveTo(left, top + h, left, top + h - r);
        ctx.lineTo(left, top + r);
        ctx.quadraticCurveTo(left, top, left + r, top);
        ctx.closePath();
        ctx.fillStyle = it.bg;
        ctx.fill();
        ctx.fillStyle = it.fg;
        ctx.fillText(it.text, box.left + box.w / 2, box.top + box.h / 2 + 0.5);
        drawn += 1;
    }
    ctx.restore();
    return drawn;
}

class BadgeRenderer implements IPrimitivePaneRenderer {
    constructor(private readonly items: readonly Placed[]) {}

    draw(target: DrawTarget): void {
        if (!this.items.length) return;
        target.useMediaCoordinateSpace(({ context, mediaSize }) => {
            drawBadges(context, this.items, mediaSize.width);
        });
    }
}

class BadgeView implements IPrimitivePaneView {
    private placed: Placed[] = [];
    constructor(private readonly owner: BadgeMarkers) {}

    update(): void {
        const chart = this.owner.chart;
        const series = this.owner.series;
        if (!chart || !series) { this.placed = []; return; }
        const ts = chart.timeScale();
        const out: Placed[] = [];
        for (const b of this.owner.badges) {
            const x = ts.timeToCoordinate(b.time as Time);
            const y = series.priceToCoordinate(b.price);
            if (x == null || y == null) continue;
            out.push({ x: Number(x), y: Number(y), text: b.text, bg: b.bg, fg: b.fg, above: b.above });
        }
        this.placed = out;
    }

    zOrder() { return "top" as const; }
    renderer(): IPrimitivePaneRenderer | null { return this.placed.length ? new BadgeRenderer(this.placed) : null; }
}

export class BadgeMarkers implements ISeriesPrimitive<Time> {
    chart: IChartApi | null = null;
    series: ISeriesApi<SeriesType, Time> | null = null;
    badges: Badge[] = [];
    private requestUpdate: (() => void) | null = null;
    private readonly view = new BadgeView(this);

    attached(p: SeriesAttachedParameter<Time>): void {
        this.chart = p.chart;
        this.series = p.series as ISeriesApi<SeriesType, Time>;
        this.requestUpdate = p.requestUpdate;
        this.view.update();
    }

    detached(): void {
        this.chart = null;
        this.series = null;
        this.requestUpdate = null;
        this.badges = [];
    }

    setBadges(badges: Badge[]): void {
        this.badges = badges.slice().sort((a, b) => a.time - b.time);
        this.view.update();
        this.requestUpdate?.();
    }

    updateAllViews(): void { this.view.update(); }
    paneViews(): readonly IPrimitivePaneView[] { return [this.view]; }
}
