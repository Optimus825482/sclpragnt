"use client";
import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { usePathname } from "next/navigation";
import { OPEN_ASSISTANT_EVENT } from "../../lib/assistantEvents";

const ChartAssistantDrawer = dynamic(() => import("../../charts/ChartAssistantDrawer"), { ssr: false });

/**
 * Basit arayüzün her sayfasında sağ altta duran genel asistan (sembolsüz mod).
 * /charts kendi asistan örneğine sahip olduğundan orada hiçbir şey çizmez.
 * Mobilde düğme GİZLİ (diğer düğmelerin üstüne biniyordu): asistan alt menüdeki "Diğer" listesinden açılır
 * (`open-assistant` olayı). Masaüstünde yüzen düğme aynen durur.
 */
export default function AssistantFab() {
  const pathname = usePathname() ?? "";
  const [open, setOpen] = useState(false);
  // Sürücü parçası yalnızca ilk açılıştan sonra yüklensin/bağlansın; kapatınca da
  // bağlı kalır (sohbet geçmişi korunur).
  const [everOpened, setEverOpened] = useState(false);

  const onCharts = pathname.startsWith("/charts");
  useEffect(() => {
    if (onCharts) return;
    const handleOpen = () => { setEverOpened(true); setOpen(true); };
    window.addEventListener(OPEN_ASSISTANT_EVENT, handleOpen);
    return () => window.removeEventListener(OPEN_ASSISTANT_EVENT, handleOpen);
  }, [onCharts]);

  if (onCharts) return null;

  return (
    <>
      {everOpened && <ChartAssistantDrawer isOpen={open} onClose={() => setOpen(false)} />}
      {!open && (
        <button
          type="button"
          onClick={() => {
            setEverOpened(true);
            setOpen(true);
          }}
          className="fixed bottom-5 right-5 z-[80] hidden md:flex items-center gap-2 rounded-full border border-cyan-400/60 bg-cyan-600/90 hover:bg-cyan-500 text-[#ffffff] px-4 py-2.5 shadow-xl shadow-cyan-950/60 transition-all hover:scale-105 active:scale-95 font-sans font-bold text-xs"
          title="Asistanı Aç"
        >
          <span className="text-base">🤖</span>
          <span>Asistan</span>
        </button>
      )}
    </>
  );
}
