"use client";
import { useEffect } from "react";
import UserNav from "./UserNav";
import UserBottomNav from "./UserBottomNav";
import PortfolioBand from "../PortfolioBand";
import RadarAlertModal from "../RadarAlertModal";
import AssistantFab from "./AssistantFab";
import { useUiPrefs } from "../../lib/useUiPrefs";

/** Normal kullanıcılar için sade, light temalı kabuk. Admin kabuğu AppShell'de kalır. */
export default function UserShell({ children }: { children: React.ReactNode }) {
  const { hidden } = useUiPrefs();
  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute("data-theme", "light");
    root.classList.remove("dark");
    return () => {
      root.removeAttribute("data-theme");
      root.classList.add("dark");
    };
  }, []);
  return (
    <div className="min-h-screen bg-bunker-950 text-white">
      {/* 2026-10-17 (basit arayüz): menü + portföy bandı tek yapışkan blok; kaydırmada
          ikisi de üstte kalır. Bant masaüstünde büyük boy (pband-lg), mobilde gizli. */}
      <div className="sticky top-0 z-30">
        <UserNav hidden={hidden} />
        <div className="pband-lg hidden md:block"><PortfolioBand /></div>
      </div>
      <div className="mx-auto max-w-5xl px-4 pb-24 pt-4 md:pb-8">{children}</div>
      <UserBottomNav hidden={hidden} />
      <RadarAlertModal />
      <AssistantFab />
    </div>
  );
}
