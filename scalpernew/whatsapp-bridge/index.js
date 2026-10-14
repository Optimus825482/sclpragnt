/**
 * ScalperAgent V4 → WhatsApp grup köprüsü.
 *
 * NEDEN: WhatsApp'ın gruba mesaj gönderen ücretsiz resmi API'si YOK. Bu küçük
 * köprü, WhatsApp Web protokolünü (Baileys, MIT) kullanarak telefonu QR ile
 * bağlar ve backend'den gelen HTTP POST isteklerini gruba iletir. Backend
 * doğrudan WhatsApp'a bağlanmaz; yalnız bu servise POST atar.
 *
 * KULLANIM:
 *   1) .env oluştur (aşağıdaki örnek)
 *   2) npm install
 *   3) npm start  → terminalde QR çıkar, telefondan okut (bir kez)
 *   4) GET /groups ile grup ID'sini bul, .env'deki WHATSAPP_GROUP_ID'ye yaz
 *   5) Backend .env: WHATSAPP_NOTIFY_ENABLED=true + WHATSAPP_BRIDGE_URL
 *
 * UYARI: Baileys resmi olmayan bir yöntemdir; WhatsApp ToS'a aykırı olabilir.
 * Günde 1 mesaj düşük risklidir ama hesap banı riski sıfır değildir.
 */
import express from "express";
import makeWASocket, {
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
} from "@whiskeysockets/baileys";
import qrcode from "qrcode-terminal";
import pino from "pino";
import "dotenv/config";

const PORT = parseInt(process.env.PORT || "3001", 10);
const BRIDGE_KEY = (process.env.BRIDGE_KEY || "").trim();
const GROUP_ID = (process.env.WHATSAPP_GROUP_ID || "").trim();
const AUTH_DIR = process.env.AUTH_DIR || "./auth";

let sock = null;
let connected = false;
let lastQrAscii = "";   // /qr ucu için son QR (ASCII) — konteynerde log okumak zorsa
let cachedVersion = null;
let reconnectTimer = null;

// Baileys'in kendi (pino) logları varsayılan olarak GÜRÜLTÜLÜDÜR:
// "stream errored out", "init queries Timed Out", "presence update" gibi
// satırlar JSON olarak basılır. Biz yalnız MESAJ GÖNDERİYORUZ (okuma/geçmiş
// yok), bu yüzden bu gürültüyü varsayılan olarak susturuyoruz. İhtiyaç
// halinde LOG_LEVEL=debug ile açılabilir.
const logger = pino({ level: process.env.LOG_LEVEL || "silent" });

async function startSock() {
  // Yeniden bağlanmada eski soketi temizle (listener/soket sızıntısını önler).
  if (sock) {
    try {
      sock.ev.removeAllListeners("connection.update");
      sock.ev.removeAllListeners("creds.update");
      sock.end(undefined);
    } catch { /* yoksay */ }
    sock = null;
  }
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }

  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  if (!cachedVersion) {
    try { cachedVersion = (await fetchLatestBaileysVersion()).version; } catch { cachedVersion = undefined; }
  }

  sock = makeWASocket({
    ...(cachedVersion ? { version: cachedVersion } : {}),
    auth: state,
    logger,
    printQRInTerminal: false,
    browser: ["ScalperAgent", "Chrome", "1.0"],
    // Bizim kullanımımız YALNIZ GÖNDERİM: sohbet geçmişi/presence/okuma yok.
    // Bu ayarlar "init queries Timed Out" ve "presence update" gürültüsünü
    // gerçekten ortadan kaldırır (yalnız susturmak değil).
    markOnlineOnConnect: false,       // presence aboneliği açılmaz
    syncFullHistory: false,           // tüm mesaj geçmişi çekilmez
    shouldSyncHistoryMessage: () => false,
    getMessage: async () => undefined, // okuma yok → retry-receipt hatası olmaz
  });

  sock.ev.on("creds.update", saveCreds);
  // Gelen mesajları işleme (yalnız gönderen bir botuz) — çözülemeyen eski
  // mesajların "error in handling message" spam'ini önler.
  sock.ev.on("messages.upsert", () => {});

  sock.ev.on("connection.update", (update) => {
    const { connection, lastDisconnect, qr } = update;
    if (qr) {
      console.log("\n=== WHATSAPP QR — telefondan okutun (WhatsApp > Bağlı Cihazlar) ===");
      console.log("    (Konteyner logunda okumak zorsa: GET /qr ucu ASCII QR döner)\n");
      qrcode.generate(qr, { small: true }, (ascii) => { lastQrAscii = ascii; console.log(ascii); });
    }
    if (connection === "open") {
      connected = true;
      lastQrAscii = "";
      console.log("✅ WhatsApp bağlandı.");
    } else if (connection === "close") {
      connected = false;
      const code = lastDisconnect?.error?.output?.statusCode;
      const loggedOut = code === DisconnectReason.loggedOut;
      // 515 = restartRequired: QR eşleştirme sonrası WhatsApp "yeniden bağlan"
      // der — NORMAL. Diğer kodlar için de yeniden bağlanılır; yalnız gerçek
      // çıkışta (loggedOut) QR yeniden gerekir.
      const reason = loggedOut
        ? "Çıkış yapıldı — auth/ silinip yeniden QR gerekir."
        : (code === 515 ? "Yeniden başlatma istendi (normal)." : "Yeniden bağlanılıyor...");
      console.log(`⚠️  Bağlantı kapandı (kod ${code}). ${reason}`);
      if (!loggedOut) {
        reconnectTimer = setTimeout(() => startSock().catch((e) => console.error("yeniden bağlanma hatası:", e)), 3000);
      }
    }
  });
}

// ---------- HTTP API ----------
const app = express();
app.use(express.json({ limit: "256kb" }));

function auth(req, res) {
  if (!BRIDGE_KEY) return true;
  const key = req.headers["x-bridge-key"];
  if (key !== BRIDGE_KEY) {
    res.status(401).json({ ok: false, error: "geçersiz X-Bridge-Key" });
    return false;
  }
  return true;
}

app.get("/status", (req, res) => {
  res.json({
    ok: true,
    connected,
    group_configured: Boolean(GROUP_ID),
    group_id: GROUP_ID || null,
    qr_pending: Boolean(lastQrAscii) && !connected,
  });
});

app.get("/qr", (req, res) => {
  if (connected) return res.type("text/plain").send("✅ Zaten bağlı — QR gerekmez.");
  if (!lastQrAscii) return res.type("text/plain").send("QR henüz hazır değil; birkaç saniye sonra tekrar deneyin.");
  res.type("text/plain").send(lastQrAscii);
});

app.get("/groups", async (req, res) => {
  if (!auth(req, res)) return;
  if (!sock || !connected) return res.status(503).json({ ok: false, error: "WhatsApp bağlı değil" });
  try {
    const groups = await sock.groupFetchAllParticipating();
    const rows = Object.values(groups).map((g) => ({ id: g.id, subject: g.subject }));
    res.json({ ok: true, groups: rows });
  } catch (e) {
    res.status(500).json({ ok: false, error: String(e) });
  }
});

app.post("/send", async (req, res) => {
  if (!auth(req, res)) return;
  const message = (req.body?.message || "").toString();
  const to = (req.body?.to || GROUP_ID || "").toString().trim();
  if (!message) return res.status(400).json({ ok: false, error: "message boş" });
  if (!to) return res.status(400).json({ ok: false, error: "grup ID yok (WHATSAPP_GROUP_ID)" });
  if (!sock || !connected) return res.status(503).json({ ok: false, error: "WhatsApp bağlı değil" });
  try {
    await sock.sendMessage(to, { text: message });
    res.json({ ok: true, to });
  } catch (e) {
    res.status(500).json({ ok: false, error: String(e) });
  }
});

app.listen(PORT, () => {
  console.log(`📡 WhatsApp köprüsü dinliyor: http://0.0.0.0:${PORT}`);
  if (!BRIDGE_KEY) console.log("⚠️  BRIDGE_KEY ayarlı değil — köprü kimlik doğrulamasız (önerilmez).");
});

startSock().catch((e) => console.error("başlatma hatası:", e));
