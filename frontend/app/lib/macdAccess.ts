/**
 * MACD MONITOR sayfası görüntüleme yetkisi.
 *
 * Varsayılan: admin her zaman görür; normal kullanıcılardan yalnızca bu
 * listedeki kullanıcı adları görüntüleyebilir. Bu liste hem Sidebar menüsünü
 * hem de sayfanın erişim kapısını besler (tek kaynak).
 */
export const MACD_MONITOR_VIEWERS = ["caner"];

export const canViewMacdMonitor = (role: string | null | undefined, username: string | null | undefined): boolean => {
  if (role === "admin") return true;
  if (!username) return false;
  const name = String(username).trim().toLowerCase();
  return MACD_MONITOR_VIEWERS.some((viewer) => String(viewer).trim().toLowerCase() === name);
};
