import { readFileSync } from "node:fs";
import path from "node:path";
import { renderServiceWorker } from "../lib/swRender";

// `/sw.js` SABİT adres; içerik her build'de değişir (derleme kimliği + VAPID gömülü).
// Derleme zamanında bir kez üretilir (çalışma anında dosya okuması yok).
export const dynamic = "force-static";

export function GET() {
  const template = readFileSync(path.join(process.cwd(), "app", "sw.js", "sw.template.js"), "utf8");
  const body = renderServiceWorker(
    template,
    process.env.NEXT_PUBLIC_BUILD_ID || "dev",
    process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY || "",
  );
  return new Response(body, {
    headers: {
      "Content-Type": "text/javascript; charset=utf-8",
      "Cache-Control": "no-cache, no-store, must-revalidate",
      "Service-Worker-Allowed": "/",
    },
  });
}
