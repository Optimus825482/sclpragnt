import GainerRadar from "../components/GainerRadar";

export default function GainerRadarPage() {
  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <header>
        <h1 className="font-mono text-xl font-bold tracking-tight">
          GAINER <span className="text-neon-green">RADAR</span>
        </h1>
        <p className="eyebrow mt-1">Binance TR TRY piyasasında momentum, hacim, CRSI ve order-flow taraması</p>
      </header>
      <GainerRadar />
      <div className="card bg-bunker-950">
        <p className="eyebrow mb-3">RADAR MODELİ</p>
        <p className="text-sm text-bunker-muted leading-relaxed">
          Radar adayları public Binance TR verisiyle skorlar. Uygun adaylar paper işlem için kullanılabilir; gerçek Binance emri gönderilmez.
          Canlıda gerçek order-book, backtestte candle order-flow proxy kullanılır.
        </p>
      </div>
    </div>
  );
}
