"use client";
import { useEffect } from "react";
import UserNav from "./UserNav";
import UserBottomNav from "./UserBottomNav";
import RadarAlertModal from "../RadarAlertModal";
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
      <UserNav hidden={hidden} />
      <main className="mx-auto max-w-5xl px-4 pb-24 pt-4 md:pb-8">{children}</main>
      <UserBottomNav hidden={hidden} />
      <RadarAlertModal />
    </div>
  );
}
