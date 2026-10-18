import { CURRENT_BUILD } from "../lib/appVersion";

// Derleme zamanında üretilir (kimlik build'e gömülü). Kurulu uygulama bunu periyodik
// çekip kendi kimliğiyle kıyaslar; fark varsa "Yeni sürüm var" şeridi çıkar.
export const dynamic = "force-static";

export function GET() {
  return Response.json(
    { build: CURRENT_BUILD },
    { headers: { "Cache-Control": "no-cache, no-store, must-revalidate" } },
  );
}
