"use client";
import Link from "next/link";
import { useIsUserView } from "../lib/adminView";
import UserNotifications from "../components/user/UserNotifications";

export default function NotificationsPage() {
  const userView = useIsUserView();
  if (!userView) {
    return <p className="p-4 text-sm text-bunker-muted">Yönetici bildirimleri için <Link href="/monitoring" className="text-white underline">Radar sayfasını açın</Link> ve Bildirimler sekmesini seçin.</p>;
  }
  return <UserNotifications />;
}
