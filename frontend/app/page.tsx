import LiveTerminal from "./components/LiveTerminal";
import StrategyCards from "./components/StrategyCards";

export default function Home() {
  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <header className="mb-2">
        <h1 className="font-mono text-xl font-bold tracking-tight">
          CANLI <span className="text-neon-green">SCALPING</span>
        </h1>
        <p className="eyebrow mt-1">Strateji başarı durumu · canlı paper işlem akışı · bakiye ve açık pozisyonlar</p>
      </header>
      <StrategyCards />
      <LiveTerminal />
    </div>
  );
}
