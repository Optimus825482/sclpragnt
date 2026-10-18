/**
 * Service worker şablonunu derleme kimliği ve VAPID anahtarıyla doldurur.
 * Saf fonksiyon (istemci/sunucu direktifi yok): `app/sw.js/route.ts` ve testler kullanır.
 *
 * Jetonlar tırnaklarıyla birlikte değiştirilir ve JSON.stringify ile kaçışlanır;
 * böylece değerdeki tırnak/ters bölü şablonu bozamaz.
 */
export const SW_BUILD_TOKEN = '"__SW_BUILD__"';
export const SW_VAPID_TOKEN = '"__SW_VAPID__"';

export function renderServiceWorker(template: string, build: string, vapid: string): string {
  return template
    .split(SW_BUILD_TOKEN).join(JSON.stringify(build || "dev"))
    .split(SW_VAPID_TOKEN).join(JSON.stringify((vapid || "").trim()));
}
