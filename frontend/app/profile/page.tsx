"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useIsUserView } from "../lib/adminView";
import ProfilePanel from "../components/ProfilePanel";

// 2026-10-17 (basit arayüz): kullanıcı arayüzünde Profil, Ayarlar içinde sekmedir; doğrudan
// bağlantılar /settings?tab=profile'a yönlenir. Yönetici (gelişmiş) arayüzü eski sayfayı korur.
export default function ProfilePage() {
  const userView = useIsUserView();
  const router = useRouter();
  useEffect(() => {
    if (userView) router.replace("/settings?tab=profile");
  }, [userView, router]);
  if (userView) return null;
  return <ProfilePanel />;
}
