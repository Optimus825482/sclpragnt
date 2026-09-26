// TTS (Edge TTS) ayarlarının kalıcılık sözleşmesi — TEK doğruluk kaynağı.
//
// SORUN (denetim #50 / görev 1)
// ------------------------------
// Frontend `PUT /api/llm/chat-settings` gövdesine `tts_rate` / `tts_pitch`
// gönderiyor, kullanıcı "KAYDEDİLDİ" görüyor — ama backend
// (`backend/app/main.py:2232-2236`) yalnız `active_tools` / `active_skills`
// alanlarını saklıyor. `tts_rate`/`tts_pitch` sessizce düşüyor; sonraki
// açılışta `undefined` geldiği için kullanıcı ayarı 0'a (varsayılan) dönüyor.
//
// NEDEN `?? 0` İLE KAPATMIYORUZ
// -----------------------------
// Sessizce "0'a düş" yerine kullanıcıya bildiriyoruz: ayar kalıcı değil, bu bir
// veri kaybı (kritik) ve kullanıcının güvenini zedeliyor. Backend düzelene kadar
// ayarı göndermeyi sürdürüyoruz (backend alanları tanırsa kalıcı olur), ama
// panelde kalıcı olmadığını açıkça yazıyoruz.
//
// TESPİT KURALI
// -------------
// Yükleme sonrası yanıt gövdesi `tts_rate`/`tts_pitch` anahtarlarını taşımıyorsa
// backend bu sürümde saklamıyor demektir. Taşıyorsa `null`/`NaN` olabilir → 0'a
// çevrilmez, geçerli sayıysa kullanılır.

export type TtsFields = { tts_rate?: unknown; tts_pitch?: unknown };

export type TtsPersistSupport = {
  /** Backend `tts_rate`/`tts_pitch` alanlarını saklıyor mu? */
  supported: boolean;
  /** Yüklemeden dönen geçerli değerler (destekleniyorsa). */
  rate: number | null;
  pitch: number | null;
};

/** Yanıt gövdesinde backend'in TTS alanlarını sakladığını kanıtlayan imza. */
export function detectTtsSupport(payload: unknown): boolean {
  if (!payload || typeof payload !== "object") return false;
  const body = payload as Record<string, unknown>;
  return "tts_rate" in body || "tts_pitch" in body;
}

/** Yüklenen ayarları doğrular: destekleniyorsa sayısal değerleri döner. */
export function readTtsValues(payload: unknown): { rate: number | null; pitch: number | null } {
  if (!payload || typeof payload !== "object") return { rate: null, pitch: null };
  const body = payload as TtsFields;
  const rate = Number(body.tts_rate);
  const pitch = Number(body.tts_pitch);
  return {
    rate: Number.isFinite(rate) ? rate : null,
    pitch: Number.isFinite(pitch) ? pitch : null,
  };
}

/** Durum nesnesi üretir (tüketici tek çağrıda hem desteği hem değerleri alır). */
export function inspectTtsSettings(payload: unknown): TtsPersistSupport {
  const supported = detectTtsSupport(payload);
  const { rate, pitch } = readTtsValues(payload);
  return {
    supported,
    rate: supported ? rate : null,
    pitch: supported ? pitch : null,
  };
}

/**
 * Backend desteklemiyorsa kullanıcıya gösterilecek uyarı metni.
 * Kısa ve eylem-odaklı: ne olduğu + ne yapılacak.
 */
export const TTS_PERSIST_WARNING =
  "TTS ayarları bu backend sürümünde kalıcı değil (hız/perde kaydedilmiyor, sayfa yenilenince sıfırlanır). " +
  "Etkin TTS hız/perdesini Ayarlar > Chat bölümünde değiştirin.";
