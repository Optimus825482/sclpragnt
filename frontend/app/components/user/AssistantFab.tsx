"use client";
import { useState } from "react";
import dynamic from "next/dynamic";
import { usePathname } from "next/navigation";

const ChartAssistantDrawer = dynamic(() => import("../../charts/ChartAssistantDrawer"), { ssr: false });

/**
 * Basit arayüzün her sayfasında sağ altta duran genel asistan (sembolsüz mod).
 * /charts kendi asistan örneğine sahip olduğundan orada hiçbir şey çizmez.
 * Mobilde bottom-20: alt menüyü (UserBottomNav ~56px + safe-area) aşar.
 */
export default function AssistantFab() {
  const pathname = usePathname() ?? "";
  const [open, setOpen] = useState(false);
  // Sürücü parçası yalnızca ilk açılıştan sonra yüklensin/bağlansın; kapatınca da
  // bağlı kalır (sohbet geçmişi korunur).
  const [everOpened, setEverOpened] = useState(false);

  if (pathname.startsWith("/charts")) return null;

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
          className="fixed bottom-20 md:bottom-5 right-4 md:right-5 z-[80] flex items-center gap-2 rounded-full border border-cyan-400/60 bg-cyan-600/90 hover:bg-cyan-500 text-[#ffffff] px-4 py-2.5 shadow-xl shadow-cyan-950/60 transition-all hover:scale-105 active:scale-95 font-sans font-bold text-xs"
          title="Asistanı Aç"
        >
          <span className="text-base">🤖</span>
          <span>Asistan</span>
        </button>
      )}
    </>
  );
}
