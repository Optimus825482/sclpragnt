"use client";
import { useAuth } from "../lib/auth";
import { useIsUserView } from "../lib/adminView";
import UserNotifications from "../components/user/UserNotifications";

export default function NotificationsPage() {
  const userView = useIsUserView();
  if (!userView) {
    return <p className="p-4 text-sm text-bunker-muted">Yönetici bildirimleri Radar sayfasındaki Bildirimler sekmesindedir.</p>;
  }
  return <UserNotifications />;
}
