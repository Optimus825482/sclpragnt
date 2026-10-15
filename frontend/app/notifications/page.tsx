"use client";
import { useAuth } from "../lib/auth";
import { isUserRole } from "../lib/userUi";
import UserNotifications from "../components/user/UserNotifications";

export default function NotificationsPage() {
  const { role } = useAuth();
  if (!isUserRole(role)) {
    return <p className="p-4 text-sm text-bunker-muted">Yönetici bildirimleri Radar sayfasındaki Bildirimler sekmesindedir.</p>;
  }
  return <UserNotifications />;
}
