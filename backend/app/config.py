import os
from pathlib import Path

from dotenv import load_dotenv

# Resolve the backend-local dotenv file from this module's location instead of
# the process working directory. This keeps secrets such as
# LLM_ENCRYPTION_KEY available when uvicorn is started from the repository
# root (or by a process manager with a different cwd). Explicit environment
# variables still win because override=False is the default.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
load_dotenv(override=False)


def _env_secret(name: str, default: str = "") -> str:
    """Secret oku: doğrudan env değeri, yoksa `<name>_FILE` dosyası (Docker secret).

    Docker/Coolify secret'ları dosya olarak bağlanır (ör. `/run/secrets/x`); bu
    yardımcı `SCALPER_ADMIN_PASSWORD_FILE`, `SCALPER_SESSION_SECRET_FILE` gibi
    değişkenlerle içeriği okumamızı sağlar.
    Öncelik: **boş olmayan env değeri kazanır**, yoksa dosya okunur. Dosya
    okunamazsa `default` döner — secret'ın yokluğu burada HATA değildir;
    fail-closed kararlar (boş/zayıf parola, boş session secret) çağıran tarafta
    verilir. Dosya içeriği strip edilir: `echo` ile yazılan secret'ın sonundaki
    satırsonu kimlik doğrulamayı sessizce bozabilir.
    """
    direct = os.getenv(name, "")
    if direct and direct.strip():
        return direct
    path = os.getenv(name + "_FILE", "").strip()
    if path:
        try:
            with open(path, encoding="utf-8") as fh:
                data = fh.read().strip()
            if data:
                return data
        except OSError as exc:
            print(f"[config] UYARI: {name}_FILE okunamadı ({path}): {exc}")
    return default


# G-24 (denetim): Aşağıdaki ayarların TAMAMI `class Config` gövdesinde, yani
# IMPORT anında okunur. Birkaç ayar (RETENTION_DAYS, microstructure retention,
# DATABASE_URL, SCALPER_SESSION_SECRET) ise çalışma zamanında okunur → iki
# farklı okuma rejimi vardır. Sonuç: çalışırken `os.environ` değiştirmek
# (test/reload senaryoları) bu sabitlere YANSIMAZ; süreci yeniden başlatmak
# gerekir. Davranışı kanıtlanmış bir dağıtım provası olmadan değiştirmemek için
# refactor yerine burada belgelenmiştir.


# ---------------------------------------------------------------------------
# Sembol yardımcıları (2026-10-07 — Global erken-tespit entegrasyonu için port)
# ---------------------------------------------------------------------------
# `base_asset_of`/`quote_asset_of` global repo'dan port edildi: TR↔Global sembol
# eşlemesi (BTCUSDT → BTC → BTCTRY) ve "bu sembolün quote'u bizimki mi" kontrolü
# tek merkezden yapılır. v4 tek borsa (Binance TR) ÇALIŞTIRIR ama Global taraması
# da aynı çatı altında olduğundan bilinen quote ekleri (TRY + USDT) birlikte
# tanınır — `app/binance_tr_symbols.is_binance_tr_symbol` bunları kullanır.


def _KNOWN_QUOTE_ASSETS() -> tuple:
    """Bilinen quote ekleri. Uzun ek ÖNCE denenir: `USDTTRY` içinde `TRY` de
    bulunduğu için sıra önemlidir (aksi hâlde `USD` + `TTRY` gibi kesme olurdu)."""
    assets = {"TRY", "USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USD", "BTC", "ETH", "BNB", "EUR"}
    return tuple(sorted(assets, key=len, reverse=True))


def base_asset_of(symbol: str) -> str:
    """`BTCTRY`/`BTCUSDT` → `BTC`. Sonda bilinen quote eki varsa keser."""
    value = str(symbol or "").upper()
    for quote in _KNOWN_QUOTE_ASSETS():
        if value.endswith(quote) and len(value) > len(quote):
            return value[: -len(quote)]
    return value


def quote_asset_of(symbol: str) -> str:
    """`BTCTRY`/`BTCUSDT` → `TRY`/`USDT`. Bilinen ek yoksa boş dize."""
    value = str(symbol or "").upper()
    for quote in _KNOWN_QUOTE_ASSETS():
        if value.endswith(quote) and len(value) > len(quote):
            return quote
    return ""


class Config:
    STRATEGY_REVISION = os.getenv("STRATEGY_REVISION", "filters-2026-08-06-adx18-keltner-retest-chop45")
    # Startup and top-gainer hydration use only the timeframes that active
    # paper paths consume. Other chart/research timeframes are hydrated on
    # demand and do not need to block process startup.
    PRIORITY_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")

    # ---- Borsa kimliği (2026-09-29, global'den port) ------------------------
    # Global repo aynı kod tabanını iki borsada çalıştırıyor (EXCHANGE
    # registry); v4 Binance TR kurulumudur, registry burada ölü kod olurdu.
    # Yalnızca quote kimliği port edildi: kod "TRY" literalleri yerine bu
    # sabitleri kullanır. TR'de davranış birebir aynı kalır; ileride USDT
    # örneği gerekirse QUOTE_ASSET env'i ile geçilir.
    QUOTE_ASSET = os.getenv("QUOTE_ASSET", "TRY").strip().upper() or "TRY"
    # Paper cüzdanın NAKİT satırı bu cinsten tutulur (virtual_wallet.asset).
    # DİKKAT: API alan adları (wallet_try, initial_balance_try) frontend
    # sözleşmesi olduğu için BİLİNCİLDİR DEĞİŞTİRİLMEDİ — etiket eski, değer
    # doğru (global repo'daki yaklaşımın aynısı).
    CASH_ASSET = QUOTE_ASSET

    # ---- Binance Global erken-tespit katmanı (2026-10-07) -------------------
    # Global piyasa TR'den DAHA LİKİT olduğu için, TR'de de listeli sembollerin
    # yükselişini birkaç saniye/dakika ERKEN gösterir. v4 aynı tarama
    # algoritmasını Global spot verisi üzerinde ARKA PLANDA çalıştırır; Global'de
    # bir hareket yakalanınca v4 yine BİNANCE TR sembolü için bildirim üretir ve
    # TR fiyatıyla otonom paper işlem açar. Arayüzde Global bir borsa/venue olarak
    # GÖRÜNMEZ (bkz. plan aşama 4) — yalnız görünmez bir erken-tespit girdisidir.
    #
    # VARSAYILAN KAPALI: davranış değişmez; bayrak açılana kadar hiçbir Global
    # bağlantısı kurulmaz. Gerçek emir yolu AÇILMAZ (Global salt-okunur tarama).
    GLOBAL_SCAN_ENABLED = os.getenv("GLOBAL_SCAN_ENABLED", "false").lower() == "true"
    # Global tarama yalnız TR'de listeli baz varlıklarla sınırlanır (BTCUSDT→BTCTRY);
    # TR'de işlem açılamayan bir coin için erken sinyal üretmenin faydası yoktur.
    # Bu kapı `binance_tr_symbols.is_binance_tr_symbol` üzerinden uygulanır.
    GLOBAL_SCAN_INTERVAL_SEC = max(15, int(os.getenv("GLOBAL_SCAN_INTERVAL_SEC", "30")))

    # Global spot public uç noktaları (api.binance.com havuzu + WS). TR adaptörünün
    # yedek havuzundaki `api.binance.com` ile KARIŞMAMASI için burada ayrı tutulur.
    GLOBAL_REST_BASES = (
        "https://api.binance.com",
        "https://api1.binance.com",
        "https://api2.binance.com",
        "https://api3.binance.com",
    )
    GLOBAL_WS_BASES = ("wss://stream.binance.com:9443", "wss://stream.binance.com:443")

    # Global (USDT) evreni — tarama genişliği. Env (`GLOBAL_SYMBOLS=BTCUSDT,...`)
    # verilirse o kullanılır. Tohum: TR majörlerinin USDT karşılıkları (taban
    # varlıklar birebir aynı) ki iki tarama aynı sembol kümesini görsün.
    _env_global_symbols = [
        s.strip().upper() for s in os.getenv("GLOBAL_SYMBOLS", "").split(",") if s.strip()
    ]
    GLOBAL_SYMBOLS = _env_global_symbols or [
        "BTCUSDT", "ETHUSDT", "SOLUSDT",
        "XRPUSDT", "ADAUSDT", "AVAXUSDT",
        "LINKUSDT", "NEARUSDT", "APTUSDT",
        "ARBUSDT", "OPUSDT", "SUIUSDT",
        "DOGEUSDT", "LTCUSDT", "BNBUSDT",
        "INJUSDT", "WLDUSDT", "DOTUSDT",
    ]

    SYMBOLS = [
    "BTCTRY", "ETHTRY", "SOLTRY",   # Ana Hacimliler (Balinalar)
    "XRPTRY", "ADATRY", "AVAXTRY",  # Orta Hacimliler (Trend Takipçileri)
    "LINKTRY", "NEARTRY", "APTTRY", # Güçlü Projeler (Kırılım avcıları)
    "ARBTRY", "OPTRY", "SUITRY",    # Yeni Nesil L2'ler (Hızlı Hareket)
    "DOGETRY", "LTCTRY","BNBTRY",         # Memecoinler (Hacim Patlaması Kralları)
    "INJTRY", "WLDTRY", "DOTTRY"               # Yüksek Volatilite (Agresif Skalp)
]
    MIN_NOTIONAL = 10.0
    # Env (`INITIAL_BALANCE`) verilirse o kazanır; varsayılan TR ölçeği.
    INITIAL_BALANCE_TRY = float(os.getenv("INITIAL_BALANCE", "10000.0"))
    # Spot paper işlemlerde varsayılan işlem tutarı (TRY cinsinden; adı tarihsel
    # olarak USDT kalmıştır, Binance TR tarafında bakiye TRY'dir).
    # Varsayılan paper işlem büyüklüğü (TRY). Arayüzden ayrıca değiştirilebilir.
    DEFAULT_ORDER_USDT = float(os.getenv("DEFAULT_ORDER_USDT", "1000.0"))
    # Aynı ayarın doğru adı; yeni kod bunu kullanmalı (eski ad geriye dönük uyum
    # için korunuyor, .env'deki DEFAULT_ORDER_USDT değişkeni hâlâ okunur).
    DEFAULT_ORDER_TRY = DEFAULT_ORDER_USDT
    # Likidite kapısının ATLANMA eşiği: emir değeri bu değerin altındayken
    # likidite ön-kapısına bakılmaz. Env (`MIN_PARTIAL_ORDER`) verilirse o kazanır.
    MIN_PARTIAL_ORDER_TRY = float(os.getenv("MIN_PARTIAL_ORDER", "100.0"))
    # Normal yüzde tutarı minimumun altına düştüğünde boş bakiyeyi eritmek
    # için kullanılacak kademeli paper işlem tutarı.
    FALLBACK_ORDER_TRY = float(os.getenv("FALLBACK_ORDER_TRY", "250.0"))
    # D-11 (2026-09-12): varsayılan artık 5 — eskiden 0 (= sınırsız) idi ve
    # zincirleme bildirimlerde cüzdanın tamamı tek turda pozisyona girebiliyordu.
    # 0 HÂLÂ sınırsız demektir (açıkça `0` verilirse), ancak güvenli varsayılan
    # artık sonlu. Env `MAX_OPEN_POSITIONS` > sınıf varsayılanı; çalışma anında
    # `PUT /api/config` (main.py `_apply_config_update`) DB'den üzerine yazar →
    # öncelik: çalışma-anı ayarı > env > bu sabit. Nakit/likidite/sembol-başı
    # (pyramiding) limitleri bundan bağımsız olarak ayrıca geçerlidir.
    MAX_OPEN_POSITIONS = max(0, int(os.getenv("MAX_OPEN_POSITIONS", "5")))
    MAX_TICKER_AGE_SEC = 15
    MAX_POSITION_HOLD_SEC = 4 * 60 * 60
    EARLY_FAILURE_SEC = int(os.getenv("EARLY_FAILURE_SEC", str(45 * 60)))
    EARLY_FAILURE_MIN_PROGRESS_PCT = float(os.getenv("EARLY_FAILURE_MIN_PROGRESS_PCT", "0.0015"))
    STALE_POSITION_SEC = int(os.getenv("STALE_POSITION_SEC", str(90 * 60)))
    STALE_POSITION_MIN_PROGRESS_PCT = float(os.getenv("STALE_POSITION_MIN_PROGRESS_PCT", "0.004"))
    STALE_POSITION_EXIT_BELOW_COST = os.getenv("STALE_POSITION_EXIT_BELOW_COST", "false").lower() == "true"
    # Not: EXIT_ON_OPPOSITE_SIGNAL (ters sinyalde çıkış) klasik strateji motoruyla
    # birlikte kaldırıldı — kalan kod yolu yoktu ve hiçbir yer okumuyordu (Madde 21).
    TIMEOUT_REENTRY_BLOCK_SEC = 24 * 60 * 60
    HARD_STOP_REENTRY_BLOCK_SEC = 2 * 60 * 60
    # Short-horizon velocity paper entries get a shorter, still non-zero
    # hard-stop lock. Classic strategy protection remains unchanged.
    VELOCITY_HARD_STOP_REENTRY_BLOCK_SEC = max(
        60, int(os.getenv("VELOCITY_HARD_STOP_REENTRY_BLOCK_SEC", str(15 * 60)))
    )
    # Not: MAX_POSITION_LAYERS kaldırıldı (Madde 21) — sembol başına katman
    # sınırı hiçbir kod yolunda okunmuyordu; tek-sembol-tek-pozisyon zaten
    # commit_open_position'ın "already_open" korumasıyla uygulanıyor.
    # LLM market commentary is a journaled, paper-only forecast.  These
    # horizons never authorize an order or mutate strategy parameters.
    LLM_FORECAST_HORIZONS_MINUTES = (5, 15, 60, 240)
    LLM_FORECAST_EVALUATION_INTERVAL_SEC = max(30, int(os.getenv("LLM_FORECAST_EVALUATION_INTERVAL_SEC", "60")))
    LLM_FORECAST_MIN_MOVE_PCT = max(0.0001, float(os.getenv("LLM_FORECAST_MIN_MOVE_PCT", "0.0015")))
    # Hedefe erişim ölçümü için ufuk sonrası ek gözlem süresi (dakika).
    # Değerlendirme ufuk kapanınca yapılır; hedef fiyat bu pencerede de izlenir
    # ve ilk dokunuş dakikası outcome_details.first_hit_minutes olarak kaydedilir.
    LLM_FORECAST_HIT_GRACE_MINUTES = max(0, int(os.getenv("LLM_FORECAST_HIT_GRACE_MINUTES", "120")))

    # ML fiyat-tahmin modeli (Faz 1: gecelik eğitim + artifact).
    ML_MODELS_DIR = os.getenv("ML_MODELS_DIR", "/data/ml_models")
    ML_TRAIN_INTERVAL_HOURS = max(1, int(os.getenv("ML_TRAIN_INTERVAL_HOURS", "12")))
    ML_TRAIN_LOOKBACK_DAYS = max(2, int(os.getenv("ML_TRAIN_LOOKBACK_DAYS", "10")))
    ML_MAX_BARS_PER_SYMBOL = max(500, int(os.getenv("ML_MAX_BARS_PER_SYMBOL", "3000")))
    ML_TARGET_QUANTILE = min(0.95, max(0.5, float(os.getenv("ML_TARGET_QUANTILE", "0.65"))))
    # ML hedef tahmini dinamik hedefe hangi güvenle uygulanır. Düşük güvenli
    # tahminler yukarı/aşağı sallantı yaratır; yalnızca güçlü tahminler aktif olsun.
    ML_TARGET_MIN_PROB = min(0.95, max(0.5, float(os.getenv("ML_TARGET_MIN_PROB", "0.65"))))
    # Yüksek güven eşiği: ML hedefi bu olasılığın ÜSTÜNDE daha güçlü (0.5), altında
    # daha zayıf (0.25) harmanlanır. MIN_PROB'un altına inemez — aksi halde
    # "yüksek güven" kademesi erişilemez olurdu (2026-09-17 denetimi).
    ML_TARGET_HIGH_PROB = min(0.95, max(ML_TARGET_MIN_PROB, float(os.getenv("ML_TARGET_HIGH_PROB", "0.8"))))
    ML_JOURNAL_SAMPLE_WEIGHT = max(1.0, float(os.getenv("ML_JOURNAL_SAMPLE_WEIGHT", "3.0")))
    ML_HIT_TARGET_PCT = {5: 0.02, 15: 0.03}  # ufuk -> sınıflandırıcı hedefi (kesir)
    LLM_FORECAST_LESSON_MIN_SAMPLES = max(8, int(os.getenv("LLM_FORECAST_LESSON_MIN_SAMPLES", "12")))
    # Desen madenciliği minimum destek sayısı (koşula uyan ölçülmüş tahmin).
    LLM_PATTERN_MIN_SUPPORT = max(5, int(os.getenv("LLM_PATTERN_MIN_SUPPORT", "8")))
    # Chat M5/M15 yükseliş adayları için desen kapısı ve otomatik paper işlem.
    # Desen: replay train penceresinden çıkan etiketler; min eşleşme şartı
    # sağlanmayan aday yalnızca izleme listesinde kalır, journal'a "watch" yazılır.
    CHAT_PREDICTION_PATTERN_ENABLED = os.getenv("CHAT_PREDICTION_PATTERN_ENABLED", "true").lower() == "true"
    CHAT_PREDICTION_MIN_PATTERN_MATCHES = max(1, int(os.getenv("CHAT_PREDICTION_MIN_PATTERN_MATCHES", "2")))
    CHAT_PREDICTION_HIGH_CONFIDENCE_MATCHES = max(2, int(os.getenv("CHAT_PREDICTION_HIGH_CONFIDENCE_MATCHES", "3")))
    # Replay simülasyonundan çıkan asimetrik çıkış: hedef > stop.
    CHAT_PREDICTION_TP_PCT = max(0.1, float(os.getenv("CHAT_PREDICTION_TP_PCT", "2.0")))
    CHAT_PREDICTION_SL_PCT = max(0.1, float(os.getenv("CHAT_PREDICTION_SL_PCT", "0.5")))
    CHAT_PREDICTION_MAX_HOLD_SEC = max(300, int(os.getenv("CHAT_PREDICTION_MAX_HOLD_SEC", "900")))
    # Otomatik paper açılış: yüksek güven + LLM paper trade ayarı açık olmalı.
    CHAT_PREDICTION_AUTO_TRADE_ENABLED = os.getenv("CHAT_PREDICTION_AUTO_TRADE_ENABLED", "false").lower() == "true"
    CHAT_PREDICTION_MAX_OPEN_POSITIONS = max(0, int(os.getenv("CHAT_PREDICTION_MAX_OPEN_POSITIONS", "0")))  # 0 = sınırsız
    CHAT_PREDICTION_ORDER_VALUE_TRY = max(50.0, float(os.getenv("CHAT_PREDICTION_ORDER_VALUE_TRY", "300.0")))
    # Otonom hız avcısı: her M5 kapanışında tarama, en iyi adaya (GEÇTİ veya
    # İZLEME) serbest TL'nin %50'si ile pozisyon. Kapanış modeli analyzer'da:
    # açılışta tahmin edilen hedef TP olarak konur (5dk-%2 / 15dk-%3) → fiyat
    # oraya ulaşınca take_profit ile kapanır; +%0.5'te kâr kilidi stop'u
    # maliyet üstüne çeker (trailing yok); 30dk max-hold + -%3 acil stop.
    VELOCITY_AUTO_ENABLED = os.getenv("VELOCITY_AUTO_ENABLED", "false").lower() == "true"
    VELOCITY_AUTO_INTERVAL_SEC = max(300, int(os.getenv("VELOCITY_AUTO_INTERVAL_SEC", "300")))
    VELOCITY_AUTO_BALANCE_PCT = 50.0
    VELOCITY_AUTO_SL_PCT = float(os.getenv("VELOCITY_AUTO_SL_PCT", "2.5"))  # Hız Avcısı sert stop %2.5
    # Sinyal sonrası fiyat önce geri çekilip sonra yükseldiği için açılışta sert
    # stop koyma; kâr kilidi (+%0.5) ve hedef TP çıkışı yine çalışır.
    VELOCITY_NO_INITIAL_STOP = os.getenv("VELOCITY_NO_INITIAL_STOP", "true").lower() == "true"
    VELOCITY_POOL_SIZE = max(5, min(50, int(os.getenv("VELOCITY_POOL_SIZE", "30"))))  # Hız Avcısı aday havuzu (top gainer)
    VELOCITY_TRAIL_TRIGGER_PCT = float(os.getenv("VELOCITY_TRAIL_TRIGGER_PCT", "0.5"))  # Kâr kilidi bu kâr yüzdesinde devreye girer (3-gün walk-forward: 0.5 > 0.7)
    # Not: dinamik trailing kaldırıldı (2026-09-03). Aşağıdaki iki ayar yalnızca
    # kâr kilidinin stop'unu hesaplarken tepe takibi için korunur; çıkış hedef
    # TP'sinde yapılır. Kod eski trailing dalını çağırmaz.
    VELOCITY_TRAIL_GAP_PCT = float(os.getenv("VELOCITY_TRAIL_GAP_PCT", "0.3"))
    # Trailing tepe takibi: max_price mum high'ıyla güncellenir. ÇIKIŞ her
    # zaman kapanış fiyatından yapılır — intrabar low'dan kapatmak slippage
    # yaratıyordu (ZKTRY: stop 0.4915, fill 0.48).
    VELOCITY_TRAIL_INTRABAR = os.getenv("VELOCITY_TRAIL_INTRABAR", "true").lower() == "true"
    # Maksimum tutma süresi (dk): 30dk sonra kapanıştan çık — kâr erimesini önler.
    VELOCITY_MAX_HOLD_MIN = int(os.getenv("VELOCITY_MAX_HOLD_MIN", "30"))
    # UZUN UFUK (2026-10-13): 30dk/60dk profilleri. Ufuk büyüdükçe tutma süresi
    # de uzamalı (yoksa 60dk hedefi 30dk'da kesilir). Bayrak kapalıysa yalnız
    # 5dk/15dk taranır — davranış öncekiyle BİREBİR aynı.
    # 2026-10-14 (radar analizi, docs/radar-improvement-analysis.md): 30/60 dk
    # profillerinde MAE>MFE → pump-and-fade kanıtlandı (velocity.py profil
    # yorumu); varsayılan KAPALI. Kanıtlanmış peak-capture çıkışı devreye
    # girmeden yalnız bilinçli env ile açılmalı.
    VELOCITY_EXTRA_HORIZONS_ENABLED = os.getenv(
        "VELOCITY_EXTRA_HORIZONS_ENABLED", "false").lower() == "true"
    # --- RADAR GÜÇLENDİRME (2026-10-14, Faz 1) -------------------------------
    # 1.1 REJİM KAPISI: choppiness (+ varsa 15m ADX) chop rejiminde trend
    # modundaki sinyalleri bastırır; notr mod skorunu çarpanla kırpar.
    # Literatür: BBW/Choppiness rejim filtresi false-positive'i en ucuz düşüren
    # AND gate'tir (meta-labeling çalışmaları).
    VELOCITY_REGIME_GATE_ENABLED = os.getenv(
        "VELOCITY_REGIME_GATE_ENABLED", "true").lower() == "true"
    VELOCITY_REGIME_CHOPPINESS_MAX = float(os.getenv("VELOCITY_REGIME_CHOPPINESS_MAX", "61.8"))
    VELOCITY_REGIME_CHOP_ADX_MAX = float(os.getenv("VELOCITY_REGIME_CHOP_ADX_MAX", "20.0"))
    VELOCITY_REGIME_CHOP_SCORE_MULT = float(os.getenv("VELOCITY_REGIME_CHOP_SCORE_MULT", "0.5"))
    # 1.2 TAKER TEYİDİ: kline takerBuyBaseVolume (index 9) ile agresif alıcı
    # payı. Yükseliş hareketinde taker alım payı zayıfsa (≤0.45) skor cezalanır,
    # güçlüyse (≥0.58) küçük teyit bonusu.
    VELOCITY_TAKER_CONFIRM_ENABLED = os.getenv(
        "VELOCITY_TAKER_CONFIRM_ENABLED", "true").lower() == "true"
    VELOCITY_TAKER_STRONG_RATIO = float(os.getenv("VELOCITY_TAKER_STRONG_RATIO", "0.58"))
    VELOCITY_TAKER_STRONG_MULT = float(os.getenv("VELOCITY_TAKER_STRONG_MULT", "1.05"))
    VELOCITY_TAKER_WEAK_RATIO = float(os.getenv("VELOCITY_TAKER_WEAK_RATIO", "0.45"))
    VELOCITY_TAKER_WEAK_MULT = float(os.getenv("VELOCITY_TAKER_WEAK_MULT", "0.95"))
    # 1.4 P&D / LİKİDİTE HİJYENİ:
    # - 24s quote hacim tabanı (TRY): altındaki semboller taramaya hiç alınmaz
    #   (wash-trade/P&D havuzu filtresi; NBER w30783).
    VELOCITY_MIN_QUOTE_VOL_24H = float(os.getenv("VELOCITY_MIN_QUOTE_VOL_24H", "1000000"))
    # - Geç faz etiketi: 24s değişim çok yüksekse (parabolik pump) yeni long
    #   sinyali düşürülür (P&D literatürü: geç giren ortalama kaybeder).
    VELOCITY_LATE_PHASE_CHANGE_PCT = float(os.getenv("VELOCITY_LATE_PHASE_CHANGE_PCT", "40.0"))
    # 2026-10-18: 0.6 → 1.0 (CEZA KAPALI). Ölçüm (SKOR_DENETIMI §4.1, replay n=972 geç fazlı aday): geç fazda
    # isabet ATR-strata içinde +15,5±2,1 puan, net +0,03±0,11 → ceza yön olarak YANLIŞ. Eski davranış: 0.6.
    # NOT: CVD işareti skora EKLENMEDİ (ATR kontrollü +5,8 puan / +0,29 net görünse de `cvd_try` ölçüm penceresi
    # ile sinyal anı hizası, yani look-ahead, doğrulanmadı); doğrulanınca ayrı bayrakla eklenir.
    VELOCITY_LATE_PHASE_SCORE_MULT = float(os.getenv("VELOCITY_LATE_PHASE_SCORE_MULT", "1.0"))
    # - Spread fail-closed: spread verisi YOKSA aday kör geçmesin; skor
    #   görünür biçimde kırılır (`spread_unknown` alanıyla raporlanır).
    VELOCITY_SPREAD_FAIL_CLOSED = os.getenv(
        "VELOCITY_SPREAD_FAIL_CLOSED", "true").lower() == "true"
    VELOCITY_SPREAD_UNKNOWN_SCORE_MULT = float(os.getenv("VELOCITY_SPREAD_UNKNOWN_SCORE_MULT", "0.85"))
    # Faz 3.4: global radar geç faz koruması — global 24s değişimi bu eşiği
    # aşmışsa sinyal "geç faz" kabul edilir, TR bildirimine/işlemine dönmez.
    GLOBAL_LATE_PHASE_CHANGE_PCT = float(os.getenv("GLOBAL_LATE_PHASE_CHANGE_PCT", "25.0"))
    # Faz 3.3: SQUEEZE TEYİDİ (OI delta + funding trendi). OI 1 saatte +%10+
    # ise short sıkışması KAPANIYOR demektir (teyit, skor ×1.25); OI hızla
    # eriyorsa (≤−%8) squeeze sönmüş olur (skor ×0.7). JFM 2026: funding
    # gelecekteki spot volatilitesi hakkında ayrı bilgi taşır.
    SQUEEZE_OI_CONFIRM_ENABLED = os.getenv(
        "SQUEEZE_OI_CONFIRM_ENABLED", "true").lower() == "true"
    SQUEEZE_OI_STRONG_PCT = float(os.getenv("SQUEEZE_OI_STRONG_PCT", "10.0"))
    SQUEEZE_OI_FADE_PCT = float(os.getenv("SQUEEZE_OI_FADE_PCT", "-8.0"))
    SQUEEZE_OI_CONFIRM_MULT = float(os.getenv("SQUEEZE_OI_CONFIRM_MULT", "1.25"))
    SQUEEZE_OI_FADE_MULT = float(os.getenv("SQUEEZE_OI_FADE_MULT", "0.7"))
    # Ufuk → maksimum tutma (dk). Ufuk sonundaki getiri NEGATİF olduğu için
    # (pump-and-fade) çıkış peak-capture'a (TP/trailing) dayanır; bu süre üst sınır.
    VELOCITY_MAX_HOLD_BY_HORIZON = {
        5: VELOCITY_MAX_HOLD_MIN,
        15: VELOCITY_MAX_HOLD_MIN,
        30: int(os.getenv("VELOCITY_MAX_HOLD_30M_MIN", "30")),
        60: int(os.getenv("VELOCITY_MAX_HOLD_60M_MIN", "60")),
    }
    # Kâr kilidi tetiklenmeden ÖNCE güvenlik stopu: fiyat +%0.5'i hiç görmeden
    # bu kadar düşerse kapat. Stopsuz açılış, fiyat hiç yükselmezse sınırsız
    # zarar demek (canlıda -%7.5 görüldü); -%3 stop EV'yi korur, max kaybı
    # sınırlar. Kâr kilidi devreye girince bu stop zaten anlamsızlaşır (kâr
    # kilidi stop'u daha yukarıdadır).
    VELOCITY_EMERGENCY_STOP_PCT = float(os.getenv("VELOCITY_EMERGENCY_STOP_PCT", "3.0"))
    # Otonom açılış için minimum velocity skoru. Journal analizi (2026-08-31):
    # skor <10 geçen adaylarda dokunuş %16.7 (n=12), 10-30 arası %47.6 (n=21),
    # 30+ %50.0 (n=14) — 10 altı adaylarda açılış yapmak EV'yi düşürüyor.
    # 0 = filtre kapalı. ÖLÇEK (2026-09-12): bu eşik PANEL (0-100) ölçeğindedir
    # ve ham velocity_score ile karşılaştırılmadan `velocity._velocity_raw_score_gate`
    # üzerinden ham ölçeğe çevrilir (aktif haritanın TERSİ).
    # A3 (2026-09-14) ANKRAJI: eski panel 10 = ham 200 (lineer, cap 2000); log
    # haritada aynı ham nokta panel 52.4'e denk gelir → DEĞER KORUNARAK yeniden
    # ankrajlandı (aksi halde kapı ham 200'den ham ~1.8'e düşüp fiilen ölürdü).
    VELOCITY_AUTO_MIN_SCORE = float(os.getenv("VELOCITY_AUTO_MIN_SCORE", "52.4"))
    # Otonom Hız Avcısı M1/M3 öncü ATR çarpanı (1.50 -> 1.15, aşırı manipülasyonu önler)
    # 2026-10-18: 1.15 → 1.0 (BONUS KAPALI). Ölçüm (SKOR_DENETIMI §4.1): öncü ATR bonusu isabeti artırıyor
    # (+8,4 puan) ama net'i düşürüyor (replay −0,22±0,10, DB −0,12±0,07). Eski davranış: 1.15.
    VELOCITY_LEADING_MULTIPLIER = float(os.getenv("VELOCITY_LEADING_MULTIPLIER", "1.0"))
    # İntraday aktif ve akışı olan sembolleri dinamik havuza dahil etme
    DYNAMIC_ACTIVE_POOL_ENABLED = os.getenv("DYNAMIC_ACTIVE_POOL_ENABLED", "true").lower() == "true"
    DYNAMIC_ACTIVE_POOL_LIMIT = max(5, min(50, int(os.getenv("DYNAMIC_ACTIVE_POOL_LIMIT", "15"))))
    # Boot anında bildirim fırtınasını önleyici grace period süresi (sn)
    BOOT_SUPPRESS_SECONDS = int(os.getenv("BOOT_SUPPRESS_SECONDS", "60"))
    # Otonom Hız Avcısı'nin açık pozisyon üst sınırı. Velocity pozisyonları
    # CHAT_PREDICTION stratejisi + signal_context.source=="velocity_auto"
    # işaretiyle taşınır (yönetim merdiveni ortak); bu cap yalnızca velocity
    # kaynaklı pozisyonları sayar (H2 düzeltmesi). 0 = sınırsız.
    VELOCITY_AUTO_MAX_OPEN_POSITIONS = max(0, int(os.getenv("VELOCITY_AUTO_MAX_OPEN_POSITIONS", "0")))
    # Journal tabanlı sembol kalitesi: hız avcısı adaylarının ölçülmüş geçmişi
    # (dokunuş oranı, ort. MFE) yalnızca sıralama çarpanı ve LLM bağlamı için
    # kullanılır. Açılış engelleyen sembol kalite filtresi kaldırıldı
    # (2026-09-03, kullanıcı kararı); journal dokunuş oranı _rank_score'u besler.
    VELOCITY_SYMBOL_QUALITY_JOURNAL_MIN_EVALUATED = max(1, int(os.getenv("VELOCITY_SYMBOL_QUALITY_JOURNAL_MIN_EVALUATED", "3")))
    VELOCITY_SYMBOL_QUALITY_JOURNAL_MAX_AVG_MFE_PCT = float(os.getenv("VELOCITY_SYMBOL_QUALITY_JOURNAL_MAX_AVG_MFE_PCT", "1.0"))
    # ---- Hibrit monitoring sıralaması (2026-09-04) ----
    # Chat upside-scout'un dakika-normalize sıralaması + sembol kalite çarpanı
    # monitoring'e taşındı (LLM'siz). Aşağıdaki eşikler kullanıcının 04.09.2026
    # radar verisine dayanır: skor >=70 kovasında ort. MFE ~%5.2 (hedef %3'ün
    # üstünde), skor <10 kovasında başarı %19 (gürültü).
    # Global bildirim eşiği: admin tek değer ayarlar, tüm kullanıcılar etkilenir.
    # A3 (2026-09-14): panel ölçeği DOYGUNLUĞU kaldırıldı.
    # Eski harita `min(100, raw/CAP×100)` HAM 2000'de sert kırpıyordu; gerçek
    # dağılım (n=42773): p50=3.0, p90=18.3, p99=159, p99.9=1024, max=21389.
    # Tüm tabloda yalnız %0.06 satır kırpılıyor AMA bildirilen bant (ham ≥1400)
    # tamamen kırpılan bölgede → kullanıcının tablosunda 104 tespitin 100'ü tam
    # 100.00 görünüyordu (sıralama bilgisi kaybı; D-08 bulgusu).
    # Yeni harita MONOTON ve REF'e kadar kırpma YOK:
    #   panel = 100 × log1p(raw) / log1p(REF)
    # `MONITORING_SCORE_NORM_MODE=linear` eski davranışı aynen korur (geri dönüş).
    MONITORING_SCORE_NORM_MODE = os.getenv("MONITORING_SCORE_NORM_MODE", "log").lower()
    # REF gözlenen max'ın (21389) üstünde seçildi → pratikte hiç kırpma olmaz
    # (raw 21389 → panel 98.46). Dağılım değişirse bu değer YENİDEN ÖLÇÜLMELİ.
    MONITORING_SCORE_NORM_LOG_REF = float(os.getenv("MONITORING_SCORE_NORM_LOG_REF", "25000"))
    MONITORING_SCORE_NORM_CAP = float(os.getenv("MONITORING_SCORE_NORM_CAP", "2000"))  # yalnız `linear` modda kullanılır
    # PANEL ölçeğindeki eşikler (admin girdisi bu ölçekte düşünür). Log moda
    # geçerken HAM ÇALIŞMA NOKTALARI KORUNACAK şekilde yeniden ankrajlandı
    # (strateji kayması olmasın). DİKKAT: panel skoru 1 ondalığa yuvarlanır, bu
    # yüzden eşikler de 1 ondalık yazılır — 2 ondalıklı bir eşik (ör. 71.54)
    # `_panel_score(1400)=71.5` ile KIL PAYI kaçırır ve bandı ölü bırakır.
    #   eski panel 70 (%70×2000 = ham 1400) → yeni panel 71.5  (ham 1393.6)
    #   eski panel 85 (ham 1700)            → yeni panel 73.5  (ham 1707.0)
    #   eski panel 90 (ham 1800)            → yeni panel 74.0  (ham 1792.3)
    #   eski panel 50 (ham 1000)            → yeni panel 68.2  (ham  999.0)
    #   eski panel 10 (ham 200)             → yeni panel 52.4  (ham  200.9)
    MONITORING_MIN_SCORE_DEFAULT = float(os.getenv("MONITORING_MIN_SCORE_DEFAULT", "71.5"))
    # velocity_score HAM ölçekte üretilir (formül: atr_ratio × bb_ratio × yapı ×
    # momentum; saturation kaldırıldığından sınırsızdır; ölçülen p50=3.0,
    # p99=159, max=21389). Panel gösterimi yukarıdaki harita ile 0-100'e
    # normalize edilir; admin eşikleri (MONITORING_MIN_SCORE_DEFAULT,
    # VELOCITY_AUTO_MIN_SCORE) PANEL ölçeğindedir ve kod tarafında ham ölçeğe
    # çevrilir (ters harita). Admin PUT /api/monitoring/settings ile düşürebilir.
    # M1/P0 (R2-01/R2-02/R3-01): ADAY KAPISI ham velocity_score üzerinden tanımlanır.
    # Panel normalizasyonu yalnızca GÖSTERİM ölçeğidir; ölçek değişince eşiğin
    # anlamı sessizce kaymasın diye varsayılan kapı mutlak ham skora bağlandı.
    # 1400 ≈ eski varsayılan (panel 70) × cap 2000; ölçek artık kapıyı HAREKET
    # ETTİRMEZ (A3 sonrası da aynı ham nokta korunur).
    # Öncelik: açık admin panel eşiği (min_score) > bu varsayılan ham eşik.
    MONITORING_MIN_RAW_SCORE = float(os.getenv("MONITORING_MIN_RAW_SCORE", "1400"))
    # Hızlı şerit: bu skor üstü adaylar debounce beklemeden anında bildirilir
    # (yüksek skor hızlı pump'larda gelir; bekleme fırsatı kaçırır).
    # M1/P1 (R2-04/R3-10/R5-C2.4): eşik varsayılan KAPI'nın (panel 71.5) KESİN
    # ÜSTÜNDE olmalı; aksi halde debounce bandı boş kalır ve gürültü filtresi hiç
    # çalışmaz. 73.5 = eski 85'in ham karşılığı (ham ~1707) — A3 ankrajı.
    MONITORING_FAST_LANE_SCORE = float(os.getenv("MONITORING_FAST_LANE_SCORE", "73.5"))
    # Debounce: fast-lane altı aday N ardışık taramada aday kalırsa bildirilir.
    MONITORING_DEBOUNCE_SCANS = max(1, int(os.getenv("MONITORING_DEBOUNCE_SCANS", "2")))
    # Bu andan itibaren monitoring bildirim skoru panel (0-100) ölçeğinde yazılır
    # (06d6a4d, 2026-09-04 18:11 +03). Öncesindeki kayıtlar ham velocity_score'tur;
    # rapor filtresi eski kayıtları tek kez normalize eder. Çift normalize uygulamak
    # eşiği fiilen 2.5× gevşetiyordu (panel 50 -> etkin 20), 2026-09-04 teşhis.
    # A3 (2026-09-14): bu tarihten SONRAKİ kayıtlar lineer ölçekle yazılmış panel
    # değerleri taşır. Ölçek sürümü satır başına `norm_version` ile taşınır
    # (`_stored_panel_score` sürüme göre okur); SINCE yalnızca "ham mı panel mi"
    # ayrımı için kalır.
    MONITORING_SCORE_NORM_SINCE = float(os.getenv("MONITORING_SCORE_NORM_SINCE", "1788534693"))
    # Skor-bantlı dinamik hedef: "skor_esigi:hedef_pct" çiftleri virgülle; eşiği
    # karşılayan EN YÜKSEK bant hedefi belirler (A3 ankrajı: ham çalışma noktaları
    # korunur — eski 90/70/50 = ham 1800/1400/1000 = yeni 74.0/71.5/68.2; 1 ondalık
    # çünkü panel skoru 1 ondalığa yuvarlanır).
    MONITORING_TARGET_SCORE_TIERS = os.getenv(
        "MONITORING_TARGET_SCORE_TIERS", "74.0:4.0,71.5:2.5,68.2:2.0")
    # Dinamik hedef sınırları ve adaptif esnetme: sembolün journal'dan öğrenilmiş
    # (get_symbol_target_state) hedefi İKİ YÖNLÜ harmanlanır — MFE'si banttan
    # düşük sembollerde hedef aşağı da çekilir (2026-09-17).
    MONITORING_TARGET_ADAPTIVE = os.getenv("MONITORING_TARGET_ADAPTIVE", "true").lower() == "true"
    # Öğrenilmiş sembol hedefi için ASGARİ örnek sayısı: bu sayının altında harman
    # uygulanmaz (tek örnek hedefi zıplatmasın).
    LEARNED_TARGET_MIN_SAMPLES = max(1, int(os.getenv("LEARNED_TARGET_MIN_SAMPLES", "3")))
    MONITORING_TARGET_PCT_MIN = float(os.getenv("MONITORING_TARGET_PCT_MIN", "1.5"))
    MONITORING_TARGET_PCT_MAX = float(os.getenv("MONITORING_TARGET_PCT_MAX", "6.0"))
    # ------------------------------------------------------------------
    # 2026-10-18 BİLDİRİM SAYILARI DÜRÜSTLEŞTİRME (kullanıcı onaylı; kaynak:
    # docs/HEDEF_SKOR_OLASILIK_OZET_2026-10-18.md + üç denetim raporu). Hiçbiri net kârı pozitife çevirmez;
    # yalnız gösterilen sayıları (hedef / isabet olasılığı) ölçülmüş gerçeğe yaklaştırır. Kayıt: DENEY_KAYDI.
    # ÇAĞRI ANINDA okunur (restart gerekmez).
    # Hedef modu: "measured" = T = clamp(exp(a)·ATR%^b·(ufuk/5)^d·exp(c·(skor−70)/10), 0,5, 6,0) (ölçülmüş
    # ulaşılabilirlik; nominal %30 isabet, katsayılar HEDEF_DENETIMI §6). Skor kademesi / öğrenilmiş sembol
    # hedefi / ML karışımı / hedef kalibrasyonu / net-kâr tabanı BU modda devre dışıdır; dürüstlük ayrı
    # `target_net_pct` alanıyla taşınır. "chain" = eski zincir (ESKİ davranış).
    # 2026-10-18 (kullanıcı kararı): NET hedef (brüt − kâr-al maliyeti) en az bu yüzde olmalı. Brüt hedef tabanı =
    # RADAR_TARGET_MIN_NET_PCT + round_trip_cost_tp (%0,205) = %1,705. Hem "measured" hem "chain" modunda uygulanır.
    # 0 = taban yok.
    RADAR_TARGET_MIN_NET_PCT = max(0.0, float(os.getenv("RADAR_TARGET_MIN_NET_PCT", "").strip() or "1.5"))
    # 2026-10-18 (kullanıcı kararı): bildirim GÖNDERİLDİKTEN sonra hedef, skor, ufuk, beklenen fiyat ve kalibre
    # isabet DEĞİŞMEZ. Eskiden bekleyen bildirim her taramada yeni hedefle güncelleniyordu (1,15 → 0,7 gibi).
    # 0 = eski davranış (her taramada güncelle).
    RADAR_NOTIFY_FREEZE_ON_SEND = os.getenv("RADAR_NOTIFY_FREEZE_ON_SEND", "1").strip().lower() not in {"0", "false", "no", "off"}
    # 2026-10-18 MA ŞERİT BUY İZLEYİCİ (kullanıcı isteği; app/ma_buy_tracker.py): aktif sembollerde yeni kapanan mumda
    # "MA şerit BUY" kuralı (grafikteki rozetle aynı) tetiklenince kaydedilir, 15 dk sonra en yüksek yükseliş ölçülür.
    # Yalnız yönetici sayfası içindir (emir/bildirim/karar YOK). 0 = kapalı.
    # 2026-10-18: admin Radar tarama günlüğü (bellek içi halka tampon; her tur 1 kayıt, ~30 sn) — tutulan tur sayısı.
    ADMIN_SCAN_LOG_KEEP = max(5, int(os.getenv("ADMIN_SCAN_LOG_KEEP", "60") or 60))
    MA_BUY_TRACKER_ENABLED = os.getenv("MA_BUY_TRACKER_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
    # "active" = symbol_activity_status ACTIVE olanlar (yoksa izlenen semboller); "tracked" = yalnız izlenen semboller.
    MA_BUY_SYMBOL_SCOPE = os.getenv("MA_BUY_SYMBOL_SCOPE", "active").strip().lower() or "active"
    MA_BUY_TIMEFRAMES = os.getenv("MA_BUY_TIMEFRAMES", "5m,15m,30m,1h,4h").strip() or "5m"   # 2026-10-20 replay: M1 medyan %0,19 < komisyon, kapali; virgüllü: 1m,5m,15m,30m,1h,4h (2026-10-21: H4)
    MA_BUY_PERIODS = os.getenv("MA_BUY_PERIODS", "7,20,99").strip() or "7,20,99"    # hızlı, orta, yavaş (EMA)
    # 2026-10-18 (canlı hata: SENTTRY M5): grafikteki MA Ribbon varsayılanı SMA; EMA ile hesaplanan sinyal grafikte
    # AŞAĞI kesişen mumda "yukarı kesti" bildirimi üretti. Varsayılan SMA (Ayarlar > MA BUY ile değiştirilebilir).
    MA_BUY_MA_TYPE = (os.getenv("MA_BUY_MA_TYPE", "sma").strip().lower() or "sma")   # sma | ema — grafikteki MA Ribbon türüyle aynı olmalı
    MA_BUY_STOCH_MAX = float(os.getenv("MA_BUY_STOCH_MAX", "80") or 80)   # 2. kural: StochRSI K bunun üstündeyse sinyal yok; 100 = kapalı
    MA_BUY_STOCH_OFF_TIMEFRAMES = os.getenv("MA_BUY_STOCH_OFF_TIMEFRAMES", "1m").strip()   # bu zaman dilimlerinde StochRSI sınırı uygulanmaz
    # 2026-10-21: H4 ÖZEL PROFİLİ. Sinyal (kullanıcı kararı, 2026-10-21 18:30): MA7 MA20'yi yukarı keser → sinyal;
    # MA99 (orta > yavaş) şartı ARANMAZ, gövde/StochRSI eleği YOK, MA türü MA_BUY_MA_TYPE (grafik şeridi).
    # Önceki arama sonucu (SMA 8/34/89, orta×yavaş, gövde ≥ %1; docs/MA_KESISIM_H4_ARAMA_90g_2026-10-21.md) ortam
    # değişkenleriyle geri alınabilir. Paper çıkışı: hedef %10 (MA_BUY_TARGET_PCT 4h), stop %8, en çok 1 gün, iz süren
    # stop 3/1,5, başabaş stop YOK. Kapatmak için MA_BUY_H4_PROFILE_ENABLED=0 (H4 genel kurala + genel paper çıkışına döner).
    MA_BUY_H4_PROFILE_ENABLED = os.getenv("MA_BUY_H4_PROFILE_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
    MA_BUY_H4_PERIODS = os.getenv("MA_BUY_H4_PERIODS", "7,20,99").strip() or "7,20,99"
    MA_BUY_H4_RULES = os.getenv("MA_BUY_H4_RULES", "fast_cross_mid").strip() or "fast_cross_mid"
    MA_BUY_H4_REQUIRE_MID_ABOVE_SLOW = os.getenv("MA_BUY_H4_REQUIRE_MID_ABOVE_SLOW", "0").strip().lower() in {"1", "true", "yes", "on"}
    MA_BUY_H4_MIN_BODY_PCT = float(os.getenv("MA_BUY_H4_MIN_BODY_PCT", "0") or 0.0)
    # 2026-10-21 19:15 (kullanıcı kararı): H4 sinyali için SEMBOL HACİM TABANI — 24 sa TL hacmi bunun altındaki çiftte H4
    # sinyali üretilmez (izleyici: push/paper yok; radar sekmesi: listede yok). Bugünkü 155 kesişimde 1–5M grubu en zayıf
    # zirveyi verdi (ort +%2,75, %5+ payı %9) → taban 5M. Eski MA_BUY_H4_SCAN_MIN_QUOTE_VOLUME adı yedek olarak okunur.
    MA_BUY_H4_MIN_QUOTE_VOLUME = float(os.getenv("MA_BUY_H4_MIN_QUOTE_VOLUME", os.getenv("MA_BUY_H4_SCAN_MIN_QUOTE_VOLUME", "5000000")) or 5_000_000)
    MA_BUY_H4_SCAN_TTL_SEC = max(60.0, float(os.getenv("MA_BUY_H4_SCAN_TTL_SEC", "600") or 600))   # önbellek tazeliği
    MA_BUY_H4_STOP_PCT = float(os.getenv("MA_BUY_H4_STOP_PCT", "8.0") or 8.0)
    # 2026-10-21 19:46 (kullanıcı kararı, docs/MA_BUY_H4_REPLAY_7_20_90g_2026-10-21.md B tablosu): tutma 1 gün, iz süren
    # stop %3 tetik / %1,5 mesafe (eğitim +%0,28 / test +%0,33, kazanma %58–59; 3 günlük tutma son ayda −%0,92 idi).
    MA_BUY_H4_MAX_HOLD_MIN = float(os.getenv("MA_BUY_H4_MAX_HOLD_MIN", "1440") or 1440)
    MA_BUY_H4_TRAILING = os.getenv("MA_BUY_H4_TRAILING", "1").strip().lower() not in {"0", "false", "no", "off"}
    MA_BUY_H4_TRAIL_TRIGGER_PCT = float(os.getenv("MA_BUY_H4_TRAIL_TRIGGER_PCT", "3.0") or 3.0)
    MA_BUY_H4_TRAIL_GAP_PCT = float(os.getenv("MA_BUY_H4_TRAIL_GAP_PCT", "1.5") or 1.5)
    MA_BUY_LOOKBACK_BARS = max(1, int(os.getenv("MA_BUY_LOOKBACK_BARS", "3") or 3))   # her turda son N kapanmış mum
    MA_BUY_SCAN_INTERVAL_SEC = max(10.0, float(os.getenv("MA_BUY_SCAN_INTERVAL_SEC", "30") or 30))
    MA_BUY_RETENTION_DAYS = max(0, int(os.getenv("MA_BUY_RETENTION_DAYS", "120") or 0))  # 0 = silme yok
    # 2026-10-18 (kullanıcı isteği): MA BUY sinyali → push (TF etiketli) + otonom paper (app/ma_buy_notify.py).
    MA_BUY_NOTIFY_ENABLED = os.getenv("MA_BUY_NOTIFY_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
    MA_BUY_NOTIFY_TIMEFRAMES = os.getenv("MA_BUY_NOTIFY_TIMEFRAMES", "15m,1h,4h").strip()      # M1 kapali (replay 2026-10-20); M5/M30 push'u kaldirildi (2026-10-26, ma_buy_notify.PUSH_DISABLED_TFS); push + paper bu TF'lerde (H4 dahil)
    # 2026-10-26 (kullanıcı isteği): her sembol için günde (Europe/Istanbul) EN FAZLA 1 push; tüm taramalar için
    # geçerli (alerting.deliver_web_push kapısı). Kapatılırsa eski davranış: her push gider, başlıkta #N sayacı.
    PUSH_ONE_PER_SYMBOL_PER_DAY = os.getenv("PUSH_ONE_PER_SYMBOL_PER_DAY", "true").strip().lower() not in {"0", "false", "no", "off"}
    # 2026-10-26 (kullanıcı isteği): N7 taraması her saat başı otomatik koşar; sıra 1-2 sonuç skoru eşikten BÜYÜKSE push.
    N7_HOURLY_ENABLED = os.getenv("N7_HOURLY_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
    N7_PUSH_MIN_SCORE = float(os.getenv("N7_PUSH_MIN_SCORE", "10") or 10)
    N7_PUSH_TOP = max(1, int(os.getenv("N7_PUSH_TOP", "2") or 2))
    MA_BUY_NOTIFY_COOLDOWN_MIN = max(0.0, float(os.getenv("MA_BUY_NOTIFY_COOLDOWN_MIN", "15") or 0))  # sembol başına (TF'ler ortak)
    MA_BUY_NOTIFY_MAX_AGE_SEC = max(10.0, float(os.getenv("MA_BUY_NOTIFY_MAX_AGE_SEC", "90") or 90))  # mum kapanışından bu kadar sonra bayat
    MA_BUY_AUTO_PAPER_ENABLED = os.getenv("MA_BUY_AUTO_PAPER_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
    MA_BUY_TARGET_PCT = os.getenv("MA_BUY_TARGET_PCT", "1m:1.0,5m:1.5,15m:2.0,30m:2.5,1h:3.0,4h:10.0").strip()  # TF:hedef% (paper TP); 30m/1h başlangıç değeri, replay raporuna göre ayarlanır
    RADAR_TARGET_MODE = (os.getenv("RADAR_TARGET_MODE", "measured").strip().lower() or "measured")
    # a,b,c,d (sırayla: sabit, ATR üssü, skor katsayısı, ufuk üssü); nominal %30 isabet.
    RADAR_TARGET_MEASURED_COEFS = os.getenv("RADAR_TARGET_MEASURED_COEFS", "0.27,0.71,0.06,0.51").strip()
    # Ölçülmüş modda hedef tabanı 0,5'e kadar iner; eski `min_target_pct` ayarı ve R/R kapısı (hedef < %0,9)
    # zincir hedeflerine (≥%1,5) göre kurulmuştu → açıkken ölçülmüş modda bu İKİ kapı uygulanmaz
    # (aksi halde bildirimlerin yarısı sessizce düşerdi). 0 = kapılar ölçülmüş hedefe de uygulanır.
    RADAR_TARGET_MEASURED_SKIP_TARGET_GATES = os.getenv(
        "RADAR_TARGET_MEASURED_SKIP_TARGET_GATES", "1").strip().lower() not in {"0", "false", "no", "off"}
    # ML hedef karışımı (p ≥ ML_TARGET_MIN_PROB): hedefi düşürüp isabeti %12 → %23'e çıkarıyor ama net fark ≈0;
    # "olasılık hedefi etkilemez" denmesine rağmen etkiliyordu. 0 = karışım kapalı (yalnız "chain" modunu etkiler).
    RADAR_TARGET_ML_BLEND_ENABLED = os.getenv("RADAR_TARGET_ML_BLEND_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
    # Birleşik (füzyon) yol: sabit 4,0 (ya da 1,5) hedef yerine velocity ile AYNI dinamik zincir (ATR + ufuk + skor).
    RADAR_FUSION_TARGET_DYNAMIC = os.getenv("RADAR_FUSION_TARGET_DYNAMIC", "1").strip().lower() not in {"0", "false", "no", "off"}
    # Ham ML % bildirim başlığında/mesajında GÖSTERİLMEZ (ECE 0,22–0,37, kalibre değil); `ml_hit_probability`
    # DB/payload'da ölçüm için kalır. 1 = eski "| ML %xx" eki.
    RADAR_NOTIFY_SHOW_ML_PROB = os.getenv("RADAR_NOTIFY_SHOW_ML_PROB", "0").strip().lower() in {"1", "true", "yes", "on"}
    # Kalibre isabet yüzdesi: σ(b0 + b1·ln ATR% + b2·ln(hedef/ATR) + b3·[ufuk≥15]) (SKOR_DENETIMI §6.1, SL %5 rejimi,
    # DB R2a+R2b 10-08..10-17; HAFTALIK yeniden uydurulmalı). "off" → alan None.
    RADAR_HIT_PROB_MODEL = (os.getenv("RADAR_HIT_PROB_MODEL", "logistic").strip().lower() or "logistic")
    RADAR_HIT_PROB_COEFS = os.getenv("RADAR_HIT_PROB_COEFS", "1.106,-0.675,-1.402,0.059").strip()
    # Mikro-yapı sıralama çarpanları (kapı değil, yalnızca aday sıralaması).
    # 2026-09-05 journal analizi (n≈52k evaluated): whale dağıtım/mixed sinyalli
    # GEÇEN adayların dokunuş oranı (%21.9/%20.7) accumulation'dan (%20.7) düşük
    # DEĞİL; no_whale en düşük (%14.8). Bu yüzden dağıtım cezası kaldırıldı —
    # whale aktivitesi OLAN semboller nötr/bonus, hiç whale olmayan hafif ceza alır.
    MONITORING_MICRO_WHALE_MULT = float(os.getenv("MONITORING_MICRO_WHALE_MULT", "1.05"))
    MONITORING_MICRO_NO_WHALE_MULT = float(os.getenv("MONITORING_MICRO_NO_WHALE_MULT", "0.9"))
    # CVD işareti dokunuşu anlamlı ayırmıyor (negatif %14.4 vs pozitif %15.0) → nötr.
    # Nötr olduğu için çarpan sabiti kaldırıldı (Madde 21); kod CVD işaretini
    # sıralamaya hiç dahil etmiyor.
    # Mikro-yapı giriş filtreleri (2026-08-31, microflow verisiyle):
    # 1) Whale dağıtım filtresi: son whale'ler dağıtım ağırlıklıysa (fiyat etkisi
    #    analizi) girişi engelle — "sahte kırılım" elemesi. Varsayılan OFF:
    #    canlı istatistik (kaç açılışın dağıtım sinyaliyle engellendiği) toplanmadan
    #    giriş kalitesini bozabilecek bir filtreyi zorunlu kılma.
    VELOCITY_WHALE_DISTRIBUTION_FILTER = os.getenv("VELOCITY_WHALE_DISTRIBUTION_FILTER", "false").lower() == "true"
    # 2) Agresif akış onayı: giriş yönüne (long) aykırı net agresif satış akışı
    #    (CVD) varsa girişi reddet. Varsayılan OFF (aynı gerekçe).
    VELOCITY_FLOW_CONFIRMATION_FILTER = os.getenv("VELOCITY_FLOW_CONFIRMATION_FILTER", "false").lower() == "true"
    VELOCITY_PROFIT_LOCK_PCT = 0.01  # Kâr kilidi SABİT TABANI. BİRİM: yüzde (0.01 == %0.01). Gerçek kilit zemini = max(bu taban, min_net_exit_pct) → tipik olarak round-trip maliyet (~%0.355) bu tabanı aşar ve zemin ONU kullanır; sabit taban yalnız emniyet ağıdır. (2026-09-26 denetimi: değer DOĞRU, eski "+%0.5" yorumu yanıltıcıydı.)
    # 7 günlük replay doğrulamasıyla bulunan M5 momentum+volatilite deseni
    # (24s/72s/7g altı pencerede %66-68 başarı). Aday pozisyon açmadan önce
    # bu eşikleri karşılamalıdır. VELOCITY_PATTERN_FILTER_ENABLED=true ise
    # pattern koşulu sağlanmazsa aday "watch" olarak journal'a düşer, açılmaz.
    VELOCITY_PATTERN_FILTER_ENABLED = os.getenv("VELOCITY_PATTERN_FILTER_ENABLED", "true").lower() == "true"
    VELOCITY_PATTERN_G0_CHG5 = float(os.getenv("VELOCITY_PATTERN_G0_CHG5", "1.2177"))
    VELOCITY_PATTERN_G0_CHG3 = float(os.getenv("VELOCITY_PATTERN_G0_CHG3", "0.8834"))
    VELOCITY_PATTERN_G0_ROC = float(os.getenv("VELOCITY_PATTERN_G0_ROC", "1.6839"))
    VELOCITY_PATTERN_G0_ATR = float(os.getenv("VELOCITY_PATTERN_G0_ATR", "0.5779"))
    VELOCITY_PATTERN_G1_ATR = float(os.getenv("VELOCITY_PATTERN_G1_ATR", "0.5432"))
    VELOCITY_PATTERN_G2_ATR = float(os.getenv("VELOCITY_PATTERN_G2_ATR", "0.5097"))
    # MACD teyidi (radar skorlaması) — MACD MONITOR'un kanıta dayalı çoklu-TF /
    # kapanmış-mum felsefesi radara taşınır. AÇIKKEN (varsayılan) aday skoru
    # kapanmış 1m/5m MACD histogramına göre hafif çarpılır; derin negatif + düşüşteki
    # aday geriye düşürülür (başarı odaklı ayıklama). Kapı değil, sıralama/skora
    # etki eden fitre çarpanıdır — yenilik keskin eşik yapılmaz.
    VELOCITY_MACD_CONFIRMATION_ENABLED = os.getenv("VELOCITY_MACD_CONFIRMATION_ENABLED", "true").lower() == "true"
    # ------------------------------------------------------------------
    # GÜNLÜK MOMENTUM KATMANI (2026-10-10)
    # Amaç: OGN/MAGIC gibi günlük pump adaylarını yakalamak. Backtest (2670
    # gözlem, 80 sembol, 70 gün): ret_8h>=+2 & ATR%>=0.5 & ADX>=25(+DI>20) &
    # slope>=0.3 → %19,8 isabet (baz %5,3'ün ~3,7 katı). Çıkış tarafı mevcut
    # kâr kilidi + trailing (VELOCITY_TRAIL_TRIGGER_PCT) ile yönetilir.
    # VARSAYILAN AÇIK (2026-10-10 kullanıcı kararı): "direkt çalışsın".
    # Kapatmak için DAILY_MOMENTUM_ENABLED=false yeterlidir (fail-safe).
    # ------------------------------------------------------------------
    DAILY_MOMENTUM_ENABLED = os.getenv("DAILY_MOMENTUM_ENABLED", "true").lower() == "true"
    DAILY_MOMENTUM_INTERVAL_MIN = max(5, int(os.getenv("DAILY_MOMENTUM_INTERVAL_MIN", "15")))
    # Tarama ÇAPASI (2026-10-10): kanıtlanan edge GÜNDE BİR KEZ, 11:30 snapshot'ı
    # içindi (backtest 11:30 bazlı). Bu yüzden tarama her 15 dk DEĞİL, günde bir
    # kez bu saatte yapılır. Saat dilimi AÇIKÇA verilir (varsayılan Türkiye) —
    # sunucu UTC olsa bile 11:30 TÜRKİYE saatiyle çalışır.
    DAILY_MOMENTUM_SCAN_HOUR = max(0, min(23, int(os.getenv("DAILY_MOMENTUM_SCAN_HOUR", "11"))))
    DAILY_MOMENTUM_SCAN_MINUTE = max(0, min(59, int(os.getenv("DAILY_MOMENTUM_SCAN_MINUTE", "30"))))
    DAILY_MOMENTUM_TZ = os.getenv("DAILY_MOMENTUM_TZ", "Europe/Istanbul")
    # WhatsApp grup bildirimi (Baileys köprüsü üzerinden, 2026-10-10).
    # Resmi API YOK; ayrı `whatsapp-bridge/` Node servisiyle HTTP konuşulur.
    # VARSAYILAN KAPALI: yapılandırılmadıkça hiçbir şey gönderilmez.
    WHATSAPP_NOTIFY_ENABLED = os.getenv("WHATSAPP_NOTIFY_ENABLED", "false").lower() == "true"
    WHATSAPP_BRIDGE_URL = os.getenv("WHATSAPP_BRIDGE_URL", "").strip()
    WHATSAPP_BRIDGE_KEY = os.getenv("WHATSAPP_BRIDGE_KEY", "").strip()
    WHATSAPP_GROUP_ID = os.getenv("WHATSAPP_GROUP_ID", "").strip()
    # Saat başı takip tablosu: 11:30'da seçilen adayların anlık fiyat/değişimini
    # her saat başı gruba gönderir (11:00–23:00 TR arası).
    WHATSAPP_HOURLY_ENABLED = os.getenv("WHATSAPP_HOURLY_ENABLED", "false").lower() == "true"
    WHATSAPP_HOURLY_START_HOUR = max(0, min(23, int(os.getenv("WHATSAPP_HOURLY_START_HOUR", "11"))))
    WHATSAPP_HOURLY_END_HOUR = max(0, min(23, int(os.getenv("WHATSAPP_HOURLY_END_HOUR", "23"))))
    # Gönderim aralığı (dakika): 30 = yarım saatte bir (2026-10-10 kullanıcı kararı).
    WHATSAPP_HOURLY_INTERVAL_MIN = max(5, int(os.getenv("WHATSAPP_HOURLY_INTERVAL_MIN", "30")))
    # ------------------------------------------------------------------
    # KOMBİNE YÜKSELİŞ DÖNGÜSÜ (2026-10-11 kullanıcı kararı) — TEK WhatsApp
    # gönderim sistemi. Radar döngülerindeki TÜM stratejiler (velocity/hız,
    # günlük momentum, short-squeeze, MACD jump/erken, yükseliş eğilimi, Master
    # Surge 4 katman, MACD MTF konfluans, mikro yapı) TEK taramada birleşir;
    # TEK birleşik puan üretilir:
    #   HER 20 DK → eşiğin ÜZERİNDEKİ en yüksek puanlı TOP_N (max 3) aday LİSTE
    #               olarak gruba gider (sembol · o anki fiyat · yükselme ihtimali ·
    #               potansiyel · yükselme miktarı(%) · tarama puanı)
    #   HER 5 DK  → o adayların bildirim anına göre ANLIK durumu (değişim farkı)
    #               + ortalaması; BİR SONRAKİ listeden önceki SON bildirimde ayrıca
    #               "liste oluşturulduktan sonraki EN YÜKSEK değişim" gösterilir
    # Her gönderim DB'ye kaydedilir. Eski 11:30 raporu / 30 dk takip / slot
    # döngüleri KALDIRILDI (çift gönderim yok).
    # ------------------------------------------------------------------
    COMBINED_RISING_ENABLED = os.getenv("COMBINED_RISING_ENABLED", "true").lower() == "true"
    # Kullanıcı kararı (2026-10-11): liste 15 dk, durum 5 dk, en fazla 2 aday.
    COMBINED_RISING_LIST_MIN = max(5, int(os.getenv("COMBINED_RISING_LIST_MIN", "15")))
    COMBINED_RISING_TRACK_MIN = max(1, int(os.getenv("COMBINED_RISING_TRACK_MIN", "5")))
    COMBINED_RISING_TOP_N = max(1, int(os.getenv("COMBINED_RISING_TOP_N", "2")))
    # Birleşik puan eşiği: listedeki 1. aday bile bunun altındaysa gönderilmez.
    COMBINED_RISING_MIN_SCORE = float(os.getenv("COMBINED_RISING_MIN_SCORE", "10.0"))
    # 2026-10-12 düzeltmesi: varsayılan pencere 09-23'tü → gece gönderim DURUYORDU
    # (kullanıcı 01:17'de liste bekledi, gelmedi). Artık 24 SAAT (00-23): aksi
    # açıkça ayarlanmadıkça gece de gönderilir. Pencere gece yarısını SARABİLİR
    # (start > end ise ör. 23→09) — bkz. `_in_send_window`.
    COMBINED_RISING_START_HOUR = max(0, min(23, int(os.getenv("COMBINED_RISING_START_HOUR", "0"))))
    COMBINED_RISING_END_HOUR = max(0, min(23, int(os.getenv("COMBINED_RISING_END_HOUR", "23"))))
    # ------------------------------------------------------------------
    # 2026-10-16 (tarama güncellemesi): KANITA DAYALI LİSTE POLİTİKASI
    # Kaynak: docs/BACKTEST_RAPORU_7G_2026-10-16.md §2.5/§3 ve
    # docs/RADAR_TARAMA_ANALIZI_2026-10-15.md §3 (14k+ journal satırı).
    # Üç anahtar da `gate_candidate` / `_combined_quality_score` içinde ÇAĞRI
    # ANINDA okunur (getattr(config, ...)); kayıt: docs/DENEY_KAYDI.md.
    # ------------------------------------------------------------------
    # (1) Kaynak AİLESİ kara listesi (virgüllü). Adayın TÜM kaynak etiketleri
    # bu kümedeyse `gate_candidate` "aile devre dışı: ..." ile bloklar (satır
    # UI'da `blocked_by` ile gri kalır; gönderilen listeye / bildirime girmez).
    # Kanıt: short_squeeze n=9166 hit %0.1 lift 0.01; snapback n=347 lift 0.00.
    # `fusion` (n=35, lift 0.00 ama GA geniş) BİLEREK dahil değil. Velocity /
    # jump / macd_mtf da taşıyan aday BLOKLANMAZ. Boş değer = kara liste kapalı.
    RADAR_DISABLED_SOURCE_FAMILIES = os.getenv(
        "RADAR_DISABLED_SOURCE_FAMILIES", "short_squeeze,snapback").strip()
    # (2) Liste SKOR TABANI. Alan: journal `unified_candidate_outcomes.scan_score`
    # = `unified_scan._combined_quality_score` KALİTE puanı (0-99; panel 0-100
    # DEĞİL). Ölçüm: scan_score < 70 → lift 0.21; 85+ → lift 3.5-4.4.
    # `COMBINED_RISING_MIN_SCORE` (kullanıcı ayarı, vars. 10) AYNI alandadır;
    # etkin taban max(ikisi) — bu ölçülen taban, öteki kullanıcı ayarı. 0 = kapalı.
    # Varsayılan KAPALI (0): "<70 → lift 0.21" ölçümü büyük ölçüde short_squeeze
    # satırlarından (n=9166, ufuk 0) geliyor; 7 günlük bildirim ölçümünde tek kaynaklı
    # velocity (kalite tavanı ~66) en iyi aile (hit60 %42.5). Kara liste devreye
    # girdikten 14 gün sonra lift yeniden ölçülmeden taban açılmaz (DENEY_KAYDI).
    RADAR_LIST_MIN_SCAN_SCORE = max(0.0, float(
        os.getenv("RADAR_LIST_MIN_SCAN_SCORE", "").strip() or "0.0"))
    # (3) jump+velocity UYUM BONUSU: kaynaklar HEM `jump` HEM `velocity` içeriyorsa
    # kalite puanına eklenir (tavan 99 korunur). Replay'de tek pozitif alt küme
    # (n≈190, isabet ~%65, ort. net +0.13) — HİPOTEZ düzeyi, n küçük → varsayılan
    # 0.0 (KAPALI). Açmak için ör. 8.0.
    RADAR_JUMP_VELOCITY_BONUS = max(0.0, float(
        os.getenv("RADAR_JUMP_VELOCITY_BONUS", "").strip() or "0"))
    # ------------------------------------------------------------------
    # 2026-10-16 (sinyal politikası): BİLDİRİM POLİTİKASI — ortak lavabo
    # (`database.save_monitoring_notifications` → `app/notification_policy.py`).
    # Kanıt: docs/BACKTEST_RAPORU_7G_2026-10-16.md §7 (30 gün hit60): trend_devam
    # %53,6; unified %32,8 (skor>=95 %54,4 / 85-95 %36,7); notr %41,1 (eşleşen şans
    # %45,9'un altı); llm_ikinci_goz %22,1; v_donusu %19,0 (n=21). Kayıt: DENEY_KAYDI.
    # ÇAĞRI ANINDA okunur. Bloklanan kayıt DB'ye yazılmaz (log + sayaç).
    RADAR_NOTIFY_POLICY_ENABLED = os.getenv("RADAR_NOTIFY_POLICY_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
    RADAR_NOTIFY_DISABLED_MODES = os.getenv(
        "RADAR_NOTIFY_DISABLED_MODES", "notr,v_donusu,llm_ikinci_goz").strip()
    # unified yalnız panel skoru (<=100) bu tabanın üstündeyse; 0 = taban kapalı.
    RADAR_NOTIFY_UNIFIED_MIN_SCORE = max(0.0, float(
        os.getenv("RADAR_NOTIFY_UNIFIED_MIN_SCORE", "").strip() or "95.0"))
    # 2026-10-17 (docs/TEYIT_UNSURLARI_ANALIZI_2026-10-17.md, kullanıcı kararı): TEYİT KURALI —
    # push yalnız en az `RADAR_NOTIFY_MIN_SOURCES` FARKLI kaynak teyidi varsa, kaynaklardan biri
    # `RADAR_NOTIFY_REQUIRED_SOURCE` ise (Hız = velocity) ve mod `RADAR_NOTIFY_CONFIRM_EXCLUDED_MODES`
    # içinde değilse gider. 17.09–09.10'da seçildi, 10.10–17.10'da dokunulmadan: isabet %33,3 (≥2 kaynak
    # %17,9; tümü %13,6), günde ~10 bildirim (tümü ~64). Maliyet sonrası net hâlâ negatif (−0,40):
    # bu bir YANLIŞ ALARM azaltmasıdır, kâr sinyali değil. 0 = kapalı.
    RADAR_NOTIFY_CONFIRM_RULE_ENABLED = os.getenv("RADAR_NOTIFY_CONFIRM_RULE_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
    RADAR_NOTIFY_MIN_SOURCES = max(1, int(os.getenv("RADAR_NOTIFY_MIN_SOURCES", "2") or 2))
    RADAR_NOTIFY_REQUIRED_SOURCE = os.getenv("RADAR_NOTIFY_REQUIRED_SOURCE", "velocity").strip().lower()
    RADAR_NOTIFY_CONFIRM_EXCLUDED_MODES = os.getenv("RADAR_NOTIFY_CONFIRM_EXCLUDED_MODES", "unified").strip()
    # GÖLGE KURAL (kayıt, karar DEĞİL): "≥2 kaynak ∧ mod = trend_devam" — 7 günde net −0,02 ama tek hafta,
    # n=50; önceki haftalar −0,41…−0,55. Uyan her aday `notification_shadow` tablosuna canlı kararla
    # birlikte yazılır; 2–3 hafta sonra `scripts/confirm_elems_study.py` ile ölçülür. 0 = kayıt yok.
    RADAR_NOTIFY_SHADOW_RULE_ENABLED = os.getenv("RADAR_NOTIFY_SHADOW_RULE_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
    # 2026-10-18 İKİNCİ KADEME (kullanıcı kararı): teyit kuralına takılan TEK kaynaklı Hız (velocity)
    # bildirimi, skoru bu tabanın üstündeyse yine push edilir; başlık "TEK KAYNAK · " ile başlar.
    # 30 günlük yerel ölçüm: yalnız-velocity trend_devam skor ≥ 90 → hedef %28,9 / stop %26,7 (n=135),
    # ≥2 kaynaklı geçen sınıf %29,0 / %37,7; skor 80–90 → hedef %16,7 (n=78). 0 = kapalı.
    RADAR_NOTIFY_SINGLE_SOURCE_MIN_SCORE = max(0.0, float(os.getenv("RADAR_NOTIFY_SINGLE_SOURCE_MIN_SCORE", "").strip() or "85"))
    # 2026-10-18 SESSİZLİK NABZI (kullanıcı kararı): bu kadar dakika hiç push gitmediyse, son taramanın
    # politikaya (yalnız teyit nedeniyle) takılan en yüksek skorlu adayı "TEYİTSİZ · " başlığıyla push
    # edilir. Sessiz saatte ve boot grace'te çalışmaz; unified / kapalı modlar aday olmaz. 0 = kapalı.
    RADAR_NOTIFY_HEARTBEAT_MINUTES = max(0, int(os.getenv("RADAR_NOTIFY_HEARTBEAT_MINUTES", "").strip() or "15"))  # 2026-10-18: 30 → 15 (kullanıcı)
    # ------------------------------------------------------------------
    # KOMBİNE PAPER PORTFÖY (2026-10-11 kullanıcı kararı) — WhatsApp'a gönderilen
    # kombine liste adayları AYRI bir 5.000 TL sanal portföyde OTONOM paper
    # işlemle açılır. Mevcut otonom paper'dan BAĞIMSIZ (kendi cüzdanı, kendi
    # defteri). Kurallar:
    #   * Pozisyon büyüklüğü: her sembol için SERBEST TL bakiyesinin %10'u.
    #   * Komisyon: Binance TR ile aynı (maker/taker 0.0015 = %0,15/bacak;
    #     COMMISSION_PCT ile hizalı) + kayma (ESTIMATED_SLIPPAGE_PCT).
    #   * TP: adayın YÜKSELME POTANSİYELİNE göre belirlenir (potential_pct).
    #   * Kâra geçince trailing mantığıyla MAKSİMUM kâr alınmaya çalışılır.
    # ------------------------------------------------------------------
    COMBINED_PAPER_ENABLED = os.getenv("COMBINED_PAPER_ENABLED", "true").lower() == "true"
    COMBINED_PAPER_INITIAL_BALANCE_TRY = float(
        os.getenv("COMBINED_PAPER_INITIAL_BALANCE_TRY", "5000.0"))
    COMBINED_PAPER_POSITION_PCT = float(os.getenv("COMBINED_PAPER_POSITION_PCT", "10.0"))  # serbest bakiyenin %'si
    COMBINED_PAPER_MAX_OPEN = max(0, int(os.getenv("COMBINED_PAPER_MAX_OPEN", "5")))       # 0 = sınırsız
    # Trailing: kâr bu eşiği geçince kâr kilidi + trailing devreye girer.
    # 2026-10-11 GERİ BİLDİRİM DÜZELTMESİ: %0.4 tetik + %0.3 boşluk ÇOK SIKIYDI —
    # TRY coinlerinin gürültüsünde fiyat tepeden %0.3 geri çekilince anında
    # yakalanıyor ve pozisyon kârı büyütemeden kapanıyordu. Ayrıca trigger ≤ gap
    # iken stop girişin altına düşüp kârı zarara çevirebiliyordu. Kural: trigger
    # gap'ten BÜYÜK olmalı → trigger %2.0, gap %1.0 (aktifleşince stop en kötü
    # girişin +%1 üstünde kalır → kâr kilitli).
    COMBINED_PAPER_TRAIL_TRIGGER_PCT = float(os.getenv("COMBINED_PAPER_TRAIL_TRIGGER_PCT", "2.0"))
    COMBINED_PAPER_TRAIL_GAP_PCT = float(os.getenv("COMBINED_PAPER_TRAIL_GAP_PCT", "1.0"))
    # Trailing aktifken SABİT TP KALDIRILIR (kullanıcı kararı 2026-10-12): aksi
    # halde kazanan pozisyon TP'ye (ör. %4) takılıp erken kapanır; oysa sembol
    # %20 yükselebilir. Trailing devreye girince çıkış tamamen kâr kilidi/trailing
    # ile yönetilir (trend sürdükçe taşır).
    COMBINED_PAPER_TP_CANCEL_ON_TRAIL = os.getenv(
        "COMBINED_PAPER_TP_CANCEL_ON_TRAIL", "true").lower() == "true"
    COMBINED_PAPER_MAX_HOLD_MIN = float(os.getenv("COMBINED_PAPER_MAX_HOLD_MIN", "120"))
    # KÂRSIZ KAPANIŞ (kullanıcı kararı 2026-10-12): pozisyon bu süre içinde
    # KÂRA GEÇMEDİYSE otomatik kapat (ölü sermaye / fırsat maliyeti). Kâra
    # geçmişse (peak >= giriş) bu kural UYGULANMAZ; o zaman normal TP/trailing/
    # max-hold işler. 0 = kapalı.
    COMBINED_PAPER_NO_PROFIT_MIN = float(os.getenv("COMBINED_PAPER_NO_PROFIT_MIN", "30"))
    # İlk koruma stop'u (kâr kilidi öncesi zarar sınırı).
    #
    # KALİBRASYON (2026-10-12, `scripts/calibrate_combined_paper.py`): %3.0 → %1.0.
    # 5.909 GERÇEK velocity adayı (passes=true) + gerçek 5m/1m mumlar üzerinde
    # walk-forward (ilk %60 eğitim / son %40 sınav) SL/trailing/no-profit grid'i
    # tarandı. Bulgular:
    #   * Hiçbir çıkış geometrisi POZİTİF EV üretmiyor → edge GİRİŞ sinyalinde
    #     yok; bu ayar "kaybı azaltır", "kâra çevirmez" (dürüst çerçeve).
    #   * Dar stop MONOTON ve tutarlı biçimde daha iyi: %3→%1.0 kaybı 5m'de
    #     -0.83 → -0.42 puan/işlem, 1m'de -0.70 → -0.34'e indirir; eşleştirilmiş
    #     fark testi t≈6.6–7.8 (ANLAMLI), her slippage seviyesinde (0.025→0.30%)
    #     ve her iki zaman diliminde aynı yön.
    #   * Kazanan kısıtlı grid: sl=1.0, mevcut trailing (trig 2.0 / gap 1.0)
    #     KORUNUR — trail testleri ve kullanıcının "trailing çok sıkı olmasın"
    #     kararı (2026-10-11) ile çakışmasın diye trailing'e dokunulmadı.
    # NEDEN İŞE YARIYOR: kayıtlı medyan zirve (MFE) ~+%1.7 iken %3 stop, kazananın
    # zirvesini geri verip -%3'te kapanmasına izin veriyordu; %1 taban kaybı erken
    # kesiyor. `paper_sim.simulate_exit` aynı sabiti okur → sim ile canlı ayrışamaz.
    COMBINED_PAPER_SL_PCT = float(os.getenv("COMBINED_PAPER_SL_PCT", "1.0"))
    DAILY_MOMENTUM_RET_8H_MIN = float(os.getenv("DAILY_MOMENTUM_RET_8H_MIN", "2.0"))
    DAILY_MOMENTUM_ATR_MIN = float(os.getenv("DAILY_MOMENTUM_ATR_MIN", "0.5"))
    DAILY_MOMENTUM_ADX_MIN = float(os.getenv("DAILY_MOMENTUM_ADX_MIN", "25.0"))
    DAILY_MOMENTUM_SLOPE_MIN = float(os.getenv("DAILY_MOMENTUM_SLOPE_MIN", "0.3"))
    DAILY_MOMENTUM_SPREAD_MAX = float(os.getenv("DAILY_MOMENTUM_SPREAD_MAX", "0.20"))
    # Aynı sembol için yeniden öneri aralığı (churn koruması): bu süre içinde
    # zaten aday bildirilmiş bir sembol tekrar bildirilmez.
    DAILY_MOMENTUM_REPEAT_COOLDOWN_MIN = max(15, int(os.getenv("DAILY_MOMENTUM_REPEAT_COOLDOWN_MIN", "120")))
    # Hedef gerçekçiliği: düşük ML isabet olasılığındaki zayıf sinyallere agresif
    # üst-bant hedef (4%) verilmesin — 5dk içinde dokunulması nadirdir ve başarıyı
    # düşürür. Yalnızca güçlü MACD teyidi / yüksek ML olasılığı 4% üst bandını korur.
    VELOCITY_TARGET_REALISM_ENABLED = os.getenv("VELOCITY_TARGET_REALISM_ENABLED", "true").lower() == "true"
    VELOCITY_TARGET_REALISM_MAX_PCT = float(os.getenv("VELOCITY_TARGET_REALISM_MAX_PCT", "3.0"))
    VELOCITY_TARGET_REALISM_MIN_ML_PROB = float(os.getenv("VELOCITY_TARGET_REALISM_MIN_ML_PROB", "0.5"))
    # MACD dip-gate: histogram derin negatif + düşüşteki adayın skorunu
    # baskılamak için kullanılan ATR çarpanı. hist < -dip_gate_atr * atr_pct
    # ise fail-forward riski yüksek sayılır.
    VELOCITY_MACD_DIP_GATE_ATR = float(os.getenv("VELOCITY_MACD_DIP_GATE_ATR", "0.5"))
    # MACD-teyitli yeniden bildirim kapısı (histerezis): aynı sembol, ufuk dolduktan
    # sonra tekrar aday olursa; MACD teyidi zayıf VE skor yükselmediyse yeniden
    # bildirim basma (gürültü kesme). MACD MONITOR'ün isabet-histerezisi mantığı.
    # Varsayılan AÇIK (2026-09-14): hedef #1 "radar başarı oranını artırmak" —
    # aynı sinyalin tekrarı yeni bilgi taşımaz. Admin panelinden kapatılabilir
    # (`monitoring_notification_settings.macd_refire_gate`); bu anahtar settings
    # yolunda config'i ezer.
    MONITORING_MACD_REFIRE_GATE = os.getenv("MONITORING_MACD_REFIRE_GATE", "true").lower() == "true"
    # A4 (R/R kapisi): dusuk odul/risk adaylari bildirilmez.
    # Oran = TP mesafesi / SL mesafesi. SL dayanagi GERCEK cikis stop'udur:
    # `auto_paper._manage_single_trade` pozisyonu `stop_loss = fill_entry*(1-sl_pct)`
    # ile acar ve `sl_pct` = `AUTO_PAPER_SL_PCT_DEFAULT` (asagida, %5.0) / settings
    # `stop_loss_pct`. Ikisi ayrisirsa RR olcumu yalan olur → parite testi:
    # `test_monitoring.CalibrationTests.test_rr_sl_basis_matches_real_exit_stop`.
    MONITORING_RR_ENABLED = os.getenv("MONITORING_RR_ENABLED", "true").lower() == "true"
    # KALIBRASYON (2026-09-14, gercek DB dagilimi):
    #   velocity_candidates hedef bandi → dokunma (isabet) orani
    #     hedef %2.00 → n=13137, isabet %8.8
    #     hedef %3.00 → n=15889, isabet %11.5
    #     hedef %4.00 → n=204,   isabet %1.3   <-- YUKSEK hedef DAHA KOTU vuruyor
    # Yani "RR'yi yukselt" yonlu bir kapi, isabeti EN DUSUK bandi secer (eski
    # varsayilan RR_MIN=1.2 / SL=%3 → hedef>=%3.6, bildirimlerin yalniz ~%27'si
    # gecer ve secilen tek bant %1.3 isabetli olandi). Bu yuzden esik, odulu
    # riskine gore ANLAMSIZ olan adayi elemekle sinirli tutulur:
    # (2026-09-14, SL dayanagi %1.5 iken) RR_MIN=0.6 + SL=%1.5 → hedef >= %0.9.
    # Tipik hedefler (%2.0 → RR 1.33, %3.0 → 2.0) GECER; yalnizca hedefi
    # gidis-donus maliyetine yaklasan band (MONITORING_TARGET_PCT_MIN=%1.5 →
    # RR 1.0) elenir. Tek deger yeterli: 5dk (%2.0) ve 15dk (%3.0) profillerinin
    # ikisi de esigi asar, ufuk bazli ayrim gerekmez.
    # (2026-10-07, SL dayanagi %5.0) ayni EFEKTIF esik 0.18 x 5.0 = %0.90
    # hedefte tutulur → %2.0/%3.0 profilleri yine gecer, davranis degismez.
    #
    # 2026-10-07: SL dayanagi 1.5 → 5.0 (asagida). Eşik de eski EFEKTIF degerinde
    # (0.6 x 1.5 = %0.90 hedef) tutulur, yoksa 0.6 x 5.0 = %3.00 olur ve
    # bildirimlerin %37,7'si elenirdi. Elimizdeki kanit (30 gun, 3223 bildirim,
    # gercek mumlar) bu ek elemenin sonucu IYILESTIRMEDIGINI gosteriyor: ayni
    # cikis kurallariyla trend_devam dar havuzda +1,446%/islem (n=379) vs tum
    # havuzda +1,375% (n=540) — islem basi fark yok sayilir, hacim %30 azalir.
    # Eşiği kaydirmanin tek sebebi bu olurdu; olmadigi icin DAVRANIS DEGISMEZ.
    MONITORING_RR_MIN = float(os.getenv("MONITORING_RR_MIN", "0.18"))
    # R/R gate SL dayanağı: AUTO_PAPER_SL_PCT_DEFAULT ile AYNI olmalı; ayrışırsa
    # gatelettiğimiz adayla açılan pozisyon farklı risk taşır (panel/lejantta
    # gösterilen `rr` ve `sl_pct` yalan olur). Parite testi:
    # `test_monitoring.RrGateTests.test_sl_basis_matches_real_exit_stop`.
    # Varsayılan burada TEKRAR YAZILMAZ: `AUTO_PAPER_SL_PCT` env'i (yoksa 5.0,
    # aşağıdaki `AUTO_PAPER_SL_PCT_DEFAULT` ile aynı) okunur — iki sabit
    # tanımdan bağımsız olarak hizalı kalır.
    MONITORING_RR_SL_PCT = float(os.getenv(
        "MONITORING_RR_SL_PCT", os.getenv("AUTO_PAPER_SL_PCT", "5.0")))

    # ---------------------------------------------------------------------
    # YÜKSELİŞ SİNYALLERİ (R1, 2026-09-14): MACD MONITOR'ün kanıtlanmış
    # erken-öncü sensörü radara taşınır (`app/rising_signals.py`).
    #
    # KANIT (macd_monitor.py:152-167 + outputs/erken_oncu_replay_kanit.md):
    #   `approach`     → OOS lift −0.082 → kapıda YOK (yanlışlıkla aktive etme!)
    #   `m1_breakout`  → OOS lift −0.094 → kapıda YOK
    #   `dip` TEK BAŞINA → 0.76-0.86× (baseline ALTI, negatif EV)
    #   `dip` + 20-bar zirveye ≤1.5 ATR yakınlık → 1.47-1.67× lift (n≈16k)
    # Bu yüzden AKTİVE EDİLEN tek reçete BİRLEŞİK kapıdır (dip AND yakınlık).
    # ---------------------------------------------------------------------
    RISING_SIGNALS_ENABLED = os.getenv("RISING_SIGNALS_ENABLED", "true").lower() == "true"
    RISING_EARLY_ENABLED = os.getenv("RISING_EARLY_ENABLED", "true").lower() == "true"
    RISING_STRENGTH_ENABLED = os.getenv("RISING_STRENGTH_ENABLED", "true").lower() == "true"
    # Snapshot alanları (`strength` 0-10 evren içi min-max, `green` 0-6 yeşil TF).
    # Eşikler MACD MONITOR arayüzünün kullandığı değerlerle AYNI (monitoring/page.tsx
    # eski istemci sabitleri: RISING_MIN_STRENGTH=9.8, RISING_MIN_GREEN=5).
    RISING_MIN_STRENGTH = float(os.getenv("RISING_MIN_STRENGTH", "9.8"))
    RISING_MIN_GREEN = int(os.getenv("RISING_MIN_GREEN", "5"))
    # H-02: Min-max bağımlılığını kaldıran mutlak ham skor eşiği
    RISING_MIN_RAW_SCORE = float(os.getenv("RISING_MIN_RAW_SCORE", "25.0"))
    # Yakınlık kapısı. Varsayılan `DIP_APPROACH_GAP_ATR` (1.5) ile AYNI olmalı —
    # parite testi kilitler (`test_rising_signals.py`).
    RISING_DIP_GAP_ATR = float(os.getenv("RISING_DIP_GAP_ATR", "1.5"))
    # MACD snapshot'ı bu yaştan eskiyse tarama SESSİZCE atlanır (döngü kapalı/
    # çökmüşse radar sahte sinyal üretmesin).
    RISING_SNAPSHOT_MAX_AGE_SEC = float(os.getenv("RISING_SNAPSHOT_MAX_AGE_SEC", "120"))
    # Sembol bazlı yeniden-ateşleme cooldown'ı (MACD jump cooldown'ı 30 dk ile hizalı).
    RISING_COOLDOWN_SEC = float(os.getenv("RISING_COOLDOWN_SEC", "1800"))
    RISING_MAX_PER_SCAN = max(1, int(os.getenv("RISING_MAX_PER_SCAN", "3")))
    # Kullanıcıya push + uygulama-içi dialog (WS `rising_alert`).
    # 2026-09-21 Erkan kararı: Yükseliş Eğilimi bildirimleri KAPALI.
    # Sadece Ana Radar (Master Surge 4'lü Teyit) bildirim gönderir.
    # Yükseliş sinyalleri hâlâ tespit edilir ve DB'ye kaydedilir (MFE/self-learning için).
    RISING_NOTIFY_ENABLED = os.getenv("RISING_NOTIFY_ENABLED", "false").lower() == "true"
    # Otonom paper girişi (kullanıcı kararı 2026-09-14: AÇIK). Kapatma anahtarı:
    # kırılım ÖNCESİ girişin isabeti `rising_alerts` ile ölçülene kadar tek güvence.
    RISING_AUTONOMOUS_ENABLED = os.getenv("RISING_AUTONOMOUS_ENABLED", "true").lower() == "true"
    RISING_AUTO_MIN_SCORE = float(os.getenv("RISING_AUTO_MIN_SCORE", "70"))
    # Bildirim/otonom hedefi: profil taban hedefi (5dk → %1.5). Yükseliş sinyali
    # 2026-09-17'den beri dinamik hedeften GEÇER (öğrenilmiş sembol hedefiyle
    # harmanlanır) ama PANEL KADEME ESNETMESİ YAPILMAZ: `monitoring._run_rising_scan`
    # `dynamic_target_pct(..., panel_score=False)` çağırır. `strength` (0-10)
    # ölçeğini panel bantlarına/zayıf-skor kelepçesine sokmak A3'te kaldırılan
    # ölçek karışıklığını geri getirirdi (plan §4/R3).
    # Varsayılan 2.2 (Net %1.5 + komisyon ve spread maliyet tabanı)
    RISING_TARGET_PCT = float(os.getenv("RISING_TARGET_PCT", "2.2"))

    # ---------------------------------------------------------------------
    # BİRLEŞİK RADAR (2026-09-16) — Hız Avcısı + Yükseliş + Radar tespitleri
    #
    # Bulgu: monitoring._run_scan DOĞRUDAN velocity.detect_velocity_candidates
    # çağırır; yani "Radar Tespitleri" Velocity'nin bildirim koludur, ayrı bir
    # motor değildir. Gerçek birleşme Velocity ↔ Yükseliş arasındadır.
    # Bu blok o birleşimi yönetir: her kaynak KENDİ kalibre edilmiş kapısını
    # korur, sembol herhangi birini geçerse adaydır (recall kaybı yok); iki kaynak
    # da RADAR_CONFLUENCE_WINDOW_SEC içinde geçiyorsa `confluence=true` işaretlenir.
    # YENİ EŞİK İCAT EDİLMEZ — yalnızca iki kanıtlı kapının birleşimi alınır.
    #
    # Bu değerler config VARSAYILANLARIDIR; admin `PUT /api/monitoring/settings`
    # ile aynı anahtar adlarıyla üzerine yazabilir (ayar deposu tek: monitoring
    # notification settings JSON). Aşama 1'de hiçbir üretim yolu etkilenmez.
    # ---------------------------------------------------------------------
    # Birleşik motoru etkinleştir (Aşama 2'de teslimat bunu kullanır). Aşama 1'de
    # yalnız modül + replay vardır, bu yüzden varsayılan KAPALI.
    RADAR_COMBINED_ENABLED = os.getenv("RADAR_COMBINED_ENABLED", "false").lower() == "true"
    # İki kaynağın "aynı olay" sayılması için maksimum zaman aralığı (sn).
    RADAR_CONFLUENCE_WINDOW_SEC = max(60, int(os.getenv("RADAR_CONFLUENCE_WINDOW_SEC", "1800")))
    # Tek tip bildirim: tek zarf üreticisi + tek tag (`radar-{sym}`) + tek WS tipi;
    # yükseliş artık ayrı `rising_alert` yayınlamaz (kirli/çift push kaldırılır).
    # 2026-09-17: varsayılan AÇIK — kullanıcı kararı: uygulama farklı fonksiyonlardan
    # farklı bildirimler göndermez; tüm tespitler TEK birleşik bildirime iner.
    RADAR_UNIFIED_NOTIFY = os.getenv("RADAR_UNIFIED_NOTIFY", "true").lower() == "true"
    # Velocity'nin otonom döngüsünü auto_paper'a yönlendir: tüm paper pozisyonlar
    # tek defterde (auto_paper_trades), tek sembol-tek pozisyon, max-open kapısı ve
    # B1-B4 merdiveniyle kapanır. Kapalıysa eski doğrudan `analyzer.open_position`
    # yolu aynen çalışır (davranış değişikliği YOK).
    RADAR_ROUTE_VELOCITY_AUTO_THROUGH_AUTO_PAPER = (
        os.getenv("RADAR_ROUTE_VELOCITY_AUTO_THROUGH_AUTO_PAPER", "false").lower() == "true")

    # ---------------------------------------------------------------------
    # BİRLEŞİK SİNYAL MOTORU (2026-09-17) — app/unified_signals.py
    #
    # Radar velocity tespiti + MACD MONITOR'ün erken sıçrama (dip-turn) ve
    # yükseliş/sıçrama (jump) fonksiyonları TEK füzyon skorunda birleşir;
    # tüm kaynaklardan TEK bildirim gider (ayrı push/alert yağmuru yok).
    # MACD MONITOR sayfası gözlem amaçlı AYNEN çalışmaya devam eder; yalnızca
    # bildirim üretimi bu motora devredilir.
    # ---------------------------------------------------------------------
    # Motor ana anahtarı (kapalıysa eski ayrı-kaynak davranışı aynen sürer).
    UNIFIED_SIGNALS_ENABLED = os.getenv("UNIFIED_SIGNALS_ENABLED", "true").lower() == "true"
    # Füzyon skoru ağırlıkları (mevcut kaynaklar üzerinden normalize edilir;
    # MACD evreninde olmayan sembolün skoru velocity paneline eşit kalır).
    UNIFIED_W_VELOCITY = float(os.getenv("UNIFIED_W_VELOCITY", "0.50"))
    UNIFIED_W_JUMP = float(os.getenv("UNIFIED_W_JUMP", "0.25"))
    UNIFIED_W_EARLY = float(os.getenv("UNIFIED_W_EARLY", "0.25"))
    UNIFIED_W_RISING = float(os.getenv("UNIFIED_W_RISING", "0.25"))
    # 2+ bağımsız kaynak aynı sembolde teyitliyse skor çarpanı (sinerji).
    UNIFIED_SYNERGY_BONUS = float(os.getenv("UNIFIED_SYNERGY_BONUS", "1.15"))
    # MACD hızlı yol (jump/dip tetiği): bu füzyon skoru altında BİLDİRİM YOK.
    # 60 sn'lik radar turu ayrıca kendi kapısıyla değerlendirir; bu eşik yalnız
    # tur arası ERKEN bildirim içindir (erken sıçrama avantajı).
    UNIFIED_FAST_MIN_SCORE = float(os.getenv("UNIFIED_FAST_MIN_SCORE", "70.0"))
    # Hızlı yol sembol cooldown'ı (sn, monotonik) — aynı sembol için fırtına yok.
    UNIFIED_FAST_COOLDOWN_SEC = max(60, int(os.getenv("UNIFIED_FAST_COOLDOWN_SEC", "1800")))
    # Füzyon-tek adayları (velocity kapısını geçemeyip dip/jump ile öne çıkanlar)
    # radar listesine/bildirimine bu panel eşiğinden itibaren girer.
    UNIFIED_FUSION_MIN_SCORE = float(os.getenv("UNIFIED_FUSION_MIN_SCORE", "60"))

    # BİRLEŞİK YÜKSELİŞ HAVUZU (2026-10-13) — rising_pool.py.
    # Havuz tüm motorları tek aday listesinde birleştirir; "gerçekten yükselen"
    # kapısı (is_genuinely_rising) üç koşulu ister: fiyat yukarı + ortak karar
    # (master_surge composite) + motor mutabakatı (confluence). Aşama C'ye kadar
    # canlıya BAĞLANMAZ — önce replay/backtest (Aşama B).
    UNIFIED_POOL_ENABLED = os.getenv("UNIFIED_POOL_ENABLED", "false").lower() == "true"
    # Ortak karar eşiği: master_surge composite_index (0-100). 60 = katmanların
    # ağırlıklı ortalaması "orta-iyi" bandı; MASTER_SURGE_MIN_SCORE (70) sert kapı
    # olarak master_surge içinde ayrıca uygulanır.
    POOL_MIN_COMPOSITE = float(os.getenv("POOL_MIN_COMPOSITE", "60.0"))
    # Motor mutabakatı: en az kaç katman teyit etmeli (4 katmandan). 2 = yarı.
    POOL_MIN_CONFLUENCE = int(os.getenv("POOL_MIN_CONFLUENCE", "2"))
    # KATMANLI AĞIRLIKLI ADAY SKORU (rising_pool.score_candidate) ağırlıkları.
    # Dört katman: güç (velocity panel), mutabakat (kaynak+confluence), trend
    # (ret3 yukarı), likidite (ATR/hacim uyumu). Toplam 1.0'a normalize edilir.
    POOL_W_STRENGTH = float(os.getenv("POOL_W_STRENGTH", "0.35"))
    POOL_W_AGREEMENT = float(os.getenv("POOL_W_AGREEMENT", "0.30"))
    POOL_W_TREND = float(os.getenv("POOL_W_TREND", "0.20"))
    POOL_W_LIQUIDITY = float(os.getenv("POOL_W_LIQUIDITY", "0.15"))
    # Skor-top-N seçimi: havuzdan en iyi N aday. 0 = kapalı (tüm havuz).
    POOL_TOP_N = int(os.getenv("POOL_TOP_N", "0"))

    # Net Kâr Hedefi & Maliyet Güvencesi (Kullanıcı Kuralı 2026-09-19):
    # %2.0 hedeflenen scalping işleminde komisyon + spread maliyetleri (~%1.0)
    # düşüldükten SONRA net %2.0 kâr kalacak şekilde brüt hedef (TP) hesaplanır.
    SCALPING_NET_TARGET_PCT = float(os.getenv("SCALPING_NET_TARGET_PCT", "2.0"))
    DEFAULT_ESTIMATED_SPREAD_PCT = float(os.getenv("DEFAULT_ESTIMATED_SPREAD_PCT", "0.65"))
    MAX_ALLOWABLE_SPREAD_RATIO = float(os.getenv("MAX_ALLOWABLE_SPREAD_RATIO", "0.35"))
    ML_MIN_EXECUTION_PROB = float(os.getenv("ML_MIN_EXECUTION_PROB", "0.0"))
    # Sinyal terfisi (upgrade): yeni sinyal, son bildirim skorundan bu kadar
    # yüksekse cooldown bastırması aşılarak "sinyal güçlendi" push'u izinli olur.
    UNIFIED_UPGRADE_MIN_GAIN = float(os.getenv("UNIFIED_UPGRADE_MIN_GAIN", "10.0"))

    # ---------------------------------------------------------------------
    # MASTER SURGE ENGINE (Ana Yükselme Potansiyeli Algoritması — 2026-09-21)
    # 4 Katmanlı Hibrit Mimari + Dinamik Uyarlanabilir Hedefler (TP1/TP2)
    # ---------------------------------------------------------------------
    # ÖLÜ ANAHTAR UYARISI (2026-10-07 denetimi): bu bayrak hiçbir kod yolunda
    # OKUNMUYOR. Motor her zaman çalışır; kapatmak için `MASTER_SURGE_ENABLED`
    # yerine `MONITORING_MASTER_SURGE_GATE=false` kullanılmalıdır. SİLİNMEDİ:
    # env ile verilen değerin sessizce yok sayılmaması için (kablo hatası mı,
    # bilinçli mi ayrımı insan kararıdır) burada belgelenir. Bağlamak P0 bir
    # davranış değişikliği olurdu → ayrı değişiklik olarak ele alınmalı.
    MASTER_SURGE_ENABLED = os.getenv("MASTER_SURGE_ENABLED", "true").lower() == "true"
    BTC_REGIME_SHIELD_ENABLED = os.getenv("BTC_REGIME_SHIELD_ENABLED", "true").lower() == "true"
    # 2026-10-17 (docs/REJIM_KALKANI_ANALIZI_2026-10-17.md): 21 günlük rescan ölçümünde kalkanın
    # kestiği adaylar gidenlerden daha kötü değildi (hit60 %21,6 vs %19,8; Welch t +2,3) ve kalkan
    # tick'lerin %57'sinde açıktı → "badge": bildirim "⚠ BTC REJİM" rozetiyle GİDER, yalnız otonom
    # paper girişi engellenir (auto_paper kendi kontrolünü yapar). "block": eski davranış (bildirim
    # ve liste kesilir). Kalkanın kendisi (BTC_REGIME_SHIELD_ENABLED) dokunulmaz.
    RADAR_SHIELD_MODE = os.getenv("RADAR_SHIELD_MODE", "badge").strip().lower()
    # 2026-10-18 (kullanıcı kararı; 90 günlük doğrulama kalkanın faydasını göstermedi): BTC rejim rozeti otonom paper
    # girişini ENGELLEMEZ (bildirim rozeti aynen gider). 1 = eski davranış (rozet varsa otonom giriş engellenir).
    # 2026-10-18 (kullanıcı kararı): otonom Hız Avcısı girişi YALNIZ push bildirimi gerçekten gönderilmiş sinyallerde açılır
    # (JUVTRY/ERATRY bildirim gelmeden paper açılıyordu). 0 = eski davranış (hız avcısı kendi başına açar).
    AUTO_PAPER_ONLY_ON_PUSH = os.getenv("AUTO_PAPER_ONLY_ON_PUSH", "1").strip().lower() not in {"0", "false", "no", "off"}
    AUTO_PAPER_BLOCK_ON_REGIME_BADGE = os.getenv("AUTO_PAPER_BLOCK_ON_REGIME_BADGE", "0").strip().lower() in {"1", "true", "yes", "on"}
    # 2026-10-17 (aynı ölçüm, tablo 2/2b): kalkan kapalıyken MFI≥90/RSI≥80 ile elenen trend_devam
    # adayları geçenlerle aynı isabette (hit60 %19,0 vs %19,8, MAE daha küçük) → "penalty": eleme
    # yerine skor çarpanı (ceza) — yalnız trend_devam ve rejim kalkanı KAPALIYKEN; kalkan açıkken
    # kesişim hücresi zayıf (%16,6) olduğundan eleme kalır. "block": eski davranış.
    # 2026-10-17 (AYNI GÜN GERİ ALINDI → "block"): 90 günlük doğrulama (docs/DOGRULAMA_90G_2026-10-17.md)
    # 21 günlük sonucu TUTMADI: kalkan kapalıyken elenenler hit60 %15,3 vs geçen %23,3 (−8,0 pp, gün-küme
    # GA95 [−9,6; −6,5]), şansa göre +2,1 vs +5,2 pp; ×0,85 ceza adayların %99,7'sini top-10'da bıraktığı için
    # pratikte kapıyı kaldırıyordu. Fark son 14 günde eridi (−1,4 pp) → 14 gün sonra yeniden ölçülecek.
    VELOCITY_EXHAUSTION_MODE = os.getenv("VELOCITY_EXHAUSTION_MODE", "block").strip().lower()
    VELOCITY_EXHAUSTION_PENALTY_MULT = float(os.getenv("VELOCITY_EXHAUSTION_PENALTY_MULT", "0.85"))
    MASTER_SURGE_MIN_SCORE = float(os.getenv("MASTER_SURGE_MIN_SCORE", "70.0"))
    # 2026-10-07: true → false. KANIT (DENETIM_RAPORU_2026-10-07 §P0-1, çalıştırarak
    # doğrulandı): kapı AÇIKken `passed=True` yalnız 4 katmanın TAMAMI geçtiğinde;
    # `_notify` `passed is False` görünce adayı atlar ve `MONITORING_MASTER_SURGE_GATE`
    # zaten varsayılan AÇIK → radar adaylarının büyük çoğunluğu sessizce bastırılıyordu
    # ("insufficient confluence" bir SKORLAMA girdisi değil, sert ölüm oluyordu).
    # `false` ile 4'lü teyit artık sert kapı değil: skor `MASTER_SURGE_MIN_SCORE`'u
    # karşılıyorsa aday geçer (monitoring.py bu yönü puanlamaya çevirir). ALT
    # KATMAN (likidite) elemesi ve gerçek risk kapıları (EXTREME_LONG/BTC-panik)
    # bu bayraktan BAĞIMSIZ olarak yürür — gevşetilen yalnız 4'lü-teyit zorunluluğu.
    # Geri dönüş: `MASTER_SURGE_REQUIRE_4WAY=true` env'i.
    MASTER_SURGE_REQUIRE_4WAY = os.getenv("MASTER_SURGE_REQUIRE_4WAY", "false").lower() == "true"
    MASTER_SURGE_MAX_SPREAD_PCT = float(os.getenv("MASTER_SURGE_MAX_SPREAD_PCT", "0.45"))
    MASTER_SURGE_MIN_24H_VOLUME_TRY = float(os.getenv("MASTER_SURGE_MIN_24H_VOLUME_TRY", "150000.0"))
    MASTER_SURGE_MIN_DEPTH_TRY = float(os.getenv("MASTER_SURGE_MIN_DEPTH_TRY", "5000.0"))
    MASTER_SURGE_TP1_MIN_PCT = float(os.getenv("MASTER_SURGE_TP1_MIN_PCT", "1.2"))
    MASTER_SURGE_TP1_MAX_PCT = float(os.getenv("MASTER_SURGE_TP1_MAX_PCT", "1.8"))
    MASTER_SURGE_TP2_MIN_PCT = float(os.getenv("MASTER_SURGE_TP2_MIN_PCT", "3.0"))
    MASTER_SURGE_TP2_MAX_PCT = float(os.getenv("MASTER_SURGE_TP2_MAX_PCT", "6.5"))
    MASTER_SURGE_BE_GAP_PCT = float(os.getenv("MASTER_SURGE_BE_GAP_PCT", "0.40"))

    # ---------------------------------------------------------------------
    # RAPOR BAŞLANGICI (2026-10-07)
    # ---------------------------------------------------------------------
    # Raporlar (sinyal + otonom işlem) ve KPI'lar yalnızca bu andan SONRAKİ
    # veriyle hesaplanır; öncesi "arşiv" sayılır ve varsayılan olarak gizlenir.
    #
    # KAPSAM (2026-10-07, DENETIM_RAPORU §P0-3 düzeltmesiyle): bu sınır YALNIZCA
    # raporlama/KPI okuma yollarını etkiler. POZİSYON YÖNETİMİ sınırı YOK SAYAR:
    # açık pozisyon taraması (`list_auto_paper_trades(status="open")` →
    # `_check_open_positions`) `ignore_reports_baseline=True` okumak ZORUNDADIR,
    # aksi halde sınırdan eski açık pozisyonlar hiç yönetilmez (SL/TP/max_hold/
    # trailing çalışmaz) ve global açık-pozisyon tavanından muaf kalırdı.
    # Özet: RAPOR bu sınıra UYAR, YÖNETİM ondan BAĞIMSIZDIR.
    #
    # NEDEN SABİT VARSAYILAN: 2026-10-07'de otonom trade ayarları kanıta dayalı
    # değerlere çevrildi (bkz. docs/OTONOM_TRADE_TESHIS_2026-10-07.md §6). O
    # tarihten ÖNCEKİ işlemler eski (zarar eden) kurguyla açıldığı için yeni
    # kurgunun gerçek performansını kirletir. Sınır bu yüzden koda gömülüdür.
    #
    # DEĞİŞTİRME: /admin → "Rapor Başlangıcı" sekmesinden tarih+saat girilip
    # kaydedilir (llm_settings: 'reports_baseline_at'). DB'de değer varsa
    # BURADAKİ varsayılanı ezer. `REPORTS_BASELINE_AT` env'i ile de verilebilir
    # (epoch saniye, ya da YYYY-MM-DD / YYYY-MM-DD HH:MM — yerel saat UTC+3).
    #
    # 0 / boş = filtre KAPALI (eski davranış: tüm geçmiş görünür).
    REPORTS_BASELINE_DEFAULT = os.getenv("REPORTS_BASELINE_AT", "2026-10-07 11:30").strip()

    # RADAR RAPOR KESİMİ (2026-10-15): radar tarama algoritmaları bu tarihte
    # önemli ölçüde geliştirildi (aile lift, p_hit kalibrasyonu, bildirim
    # politikası…). Raporlar sayfasındaki RADAR BİLDİRİMİ bölümleri (başarı
    # oranı, teyit kademeleri, sinyal listesi, MACD MTF ölçümü) bu andan
    # ÖNCEKİ bildirimleri "arşiv" sayar; hesap yalnız sonrasına bakar.
    # Soft-arşiv: kayıt silinmez, "Arşivi göster" ile görünür. Paper/bakiye
    # raporları bu sınırdan ETKİLENMEZ (onlar REPORTS_BASELINE_DEFAULT'u kullanır).
    # Biçim REPORTS_BASELINE_AT ile aynı (yerel saat UTC+3). 0/boş = kapalı.
    # DB'de `radar_reports_baseline_at` varsa bunu ezer.
    RADAR_REPORTS_BASELINE_DEFAULT = os.getenv("RADAR_REPORTS_BASELINE_AT", "2026-10-15 22:30").strip()

    # ---------------------------------------------------------------------
    # SAKLAMA (RETENTION) PENCERELERİ — disk bütçesi (2026-09-16)
    #
    # Sunucu ölçümü: DB 21 GB ama CANLI veri ~1-2 GB; kalanı BUDANMIŞ ama
    # `VACUUM` edilmemiş ölü satırlar (microstructure_snapshots 12 GB / 2.4k
    # satır, decision_logs 1.7 GB / 34 satır). Tek seferlik VACUUM FULL ile
    # geri kazanılır; buradaki pencereler TEKRARINI engeller.
    # ---------------------------------------------------------------------
    RETENTION_DAYS = max(1, int(os.getenv("RETENTION_DAYS", "30")))
    # Mikro yapı: saniyede bir satır üretir; en kısa pencere.
    MICROSTRUCTURE_RETENTION_DAYS = max(1, int(os.getenv("MICROSTRUCTURE_RETENTION_DAYS", "7")))
    # Sohbet belleği anlamsal hafızadır (LLM bağlamı) — ürün kararı, bu yüzden
    # görece uzun. Disk baskısı varsa `MEMORY_RETENTION_DAYS=30` önerilir:
    # `memory_embeddings` indeksi ölçümde 5 GB (377k belge, ~13 KB indeks/belge).
    MEMORY_RETENTION_DAYS = max(1, int(os.getenv("MEMORY_RETENTION_DAYS", "180")))
    # ML eğitimi yalnız `ML_TRAIN_LOOKBACK_DAYS` (10) geriye bakar; mum/özellik
    # geçmişi bunun ÜSTÜNDE tutulur ki replay/parite kontrolü payı kalsın.
    # ÖNEMLİ: bu iki tablo daha önce HİÇ budanmıyordu (sınırsız büyüme).
    HISTORY_RETENTION_DAYS = max(1, int(os.getenv("HISTORY_RETENTION_DAYS", "21")))
    # Embedding işleri tam JSONB belge taşır; kuyruk telemetrisi.
    EMBEDDING_JOBS_RETENTION_DAYS = max(1, int(os.getenv("EMBEDDING_JOBS_RETENTION_DAYS", "14")))
    # Karar günlüğü: satır sayısı ~8.5k/gün ve `metadata` JSONB'si satır başına
    # ~2.4 KB (ölçüm: 637k satır → 1.46 GB TOAST). Budama listesinde HİÇ yoktu.
    # OTONOM satırlar (`strategy='AUTO_PAPER'`) HARİÇ tutulur: otonom paper karar
    # zinciri ve kalibrasyon onları okur; düşen yalnızca ham gözlem telemetrisidir.
    # Disk baskısında `DECISION_LOGS_RETENTION_DAYS=30` güvenli bir alt sınırdır.
    DECISION_LOGS_RETENTION_DAYS = max(1, int(os.getenv("DECISION_LOGS_RETENTION_DAYS", "90")))

    ORDER_PCT = float(os.getenv("ORDER_PCT", "0.10"))
    PYRAMIDING_LAYERS = max(1, int(os.getenv("PYRAMIDING_LAYERS", "2")))
    SYMBOL_ORDER_PCT = {}
    # Not: SYMBOL_PYRAMIDING_LAYERS (sembol bazlı katman sınırı) kaldırıldı
    # (Madde 21) — hiçbir kod yolu okumuyordu; pyramiding kararı
    # PYRAMIDING_LAYERS ile verilir.
    MIN_24H_QUOTE_VOLUME_TRY = 1_000_000.0
    HIGH_LIQUIDITY_BYPASS_VOLUME_TRY = 3_000_000.0
    # Global (USDT) karşılıkları — Global erken-tespit taramasında likidite tabanı.
    # Global daha likit olduğu için taban TR'den farklı ölçeklenir (ölçüldü:
    # 120K USDT tabanı Global'de ~10 kazanan/~8 hareketli sembol üretiyor).
    MIN_QUOTE_VOLUME_USDT = float(os.getenv("MIN_QUOTE_VOLUME_USDT", "120000"))
    WHALE_NOTIONAL_USDT = float(os.getenv("WHALE_NOTIONAL", "25000"))
    MIN_VOLUME_RATIO = 0.3
    MIN_ORDERBOOK_DEPTH_MULTIPLIER = 5.0
    LIQUIDITY_FILTER_ENABLED = True
    # Aktivite için hem likidite/hacim hem de fiyat hareketi gerekir. Hacim,
    # tek başına mean-reversion için işlem yapılabilir menzil anlamına gelmez.
    SYMBOL_ACTIVITY_FILTER_ENABLED = os.getenv("SYMBOL_ACTIVITY_FILTER_ENABLED", "true").lower() == "true"
    SYMBOL_ACTIVITY_REFRESH_SEC = max(60, int(os.getenv("SYMBOL_ACTIVITY_REFRESH_SEC", "3600")))
    SYMBOL_ACTIVITY_MIN_QUOTE_VOLUME_TRY = float(os.getenv("SYMBOL_ACTIVITY_MIN_QUOTE_VOLUME_TRY", "1000000"))
    SYMBOL_ACTIVITY_VOLUME_ONLY = os.getenv("SYMBOL_ACTIVITY_VOLUME_ONLY", "false").lower() == "true"
    SYMBOL_ACTIVITY_MIN_RANGE_15M_PCT = float(os.getenv(
        "SYMBOL_ACTIVITY_MIN_RANGE_15M_PCT",
        os.getenv("SYMBOL_ACTIVITY_MIN_RANGE_30M_PCT", "0.05"),
    ))
    SYMBOL_ACTIVITY_MIN_ATR_PCT = float(os.getenv("SYMBOL_ACTIVITY_MIN_ATR_PCT", "0.0012"))
    SYMBOL_ACTIVITY_MIN_VOLUME_RATIO = float(os.getenv("SYMBOL_ACTIVITY_MIN_VOLUME_RATIO", "0.50"))
    # A candle with high == low did not move during its whole minute. A dense
    # cluster of completed M1 candles blocks new paper entries only.
    SYMBOL_ACTIVITY_M1_FLAT_FILTER_ENABLED = os.getenv("SYMBOL_ACTIVITY_M1_FLAT_FILTER_ENABLED", "false").lower() == "true"
    SYMBOL_ACTIVITY_M1_FLAT_MAX_RANGE_PCT = max(0.0, float(os.getenv("SYMBOL_ACTIVITY_M1_FLAT_MAX_RANGE_PCT", "0")))
    SYMBOL_ACTIVITY_M1_FLAT_5M_MAX_COUNT = max(1, min(5, int(os.getenv("SYMBOL_ACTIVITY_M1_FLAT_5M_MAX_COUNT", "4"))))
    SYMBOL_ACTIVITY_M1_FLAT_30M_MAX_COUNT = max(1, min(30, int(os.getenv("SYMBOL_ACTIVITY_M1_FLAT_30M_MAX_COUNT", "18"))))
    # Pasife düşen sembolde açık paper pozisyon varsa PnL'den bağımsız kapat
    # (backtest --passive-direct-exit'in canlı karşılığı). Pasif sembolde giriş
    # filtresi yeni pozisyon açmayı zaten engeller; aksi halde pozisyon fiyatsız askıda kalır.
    SYMBOL_ACTIVITY_PASSIVE_EXIT = os.getenv("SYMBOL_ACTIVITY_PASSIVE_EXIT", "true").lower() == "true"
    PASSIVE_SYMBOLS = set()
    SYMBOL_ACTIVITY_STATUS = {}
    # Radar yalnızca gözlem/ranking yüzeyidir; otomatik pozisyon açmaz.
    GAINER_RADAR_AUTO_TRADE = False
    # LLM yalnızca kullanıcının açık "işlem aç" talebiyle çalışabilir.
    LLM_AUTO_OPEN_ENABLED = False
    GAINER_RADAR_MIN_SCORE = 65
    # MTF count is a soft radar-ranking bonus; it never blocks an entry.
    GAINER_RADAR_MTF_PRIORITY_MAX_BONUS = max(0.0, float(os.getenv("GAINER_RADAR_MTF_PRIORITY_MAX_BONUS", "6")))
    GAINER_RADAR_INTERVAL_SEC = max(15, int(os.getenv("GAINER_RADAR_INTERVAL_SEC", "60")))
    TOP_GAINERS_LIMIT = max(1, min(50, int(os.getenv("TOP_GAINERS_LIMIT", "10"))))
    TOP_GAINERS_REFRESH_SEC = max(60, int(os.getenv("TOP_GAINERS_REFRESH_SEC", str(10 * 60))))
    TOP_GAINERS_AUTO_ACTIVATE = os.getenv("TOP_GAINERS_AUTO_ACTIVATE", "true").lower() == "true"
    LLM_REENTRY_COOLDOWN_SEC = max(60, int(os.getenv("LLM_REENTRY_COOLDOWN_SEC", str(30 * 60))))
    LLM_PROFIT_REENTRY_COOLDOWN_SEC = max(60, int(os.getenv("LLM_PROFIT_REENTRY_COOLDOWN_SEC", str(5 * 60))))
    LLM_REENTRY_MIN_MOVE_PCT = max(0.001, float(os.getenv("LLM_REENTRY_MIN_MOVE_PCT", "0.005")))
    LLM_MARKET_SCAN_CACHE_SEC = max(0, int(os.getenv("LLM_MARKET_SCAN_CACHE_SEC", "5")))
    # HIZLI ŞERİT (2026-09-17): tek sembol + durum sorusu ağır yolu (7× snapshot,
    # embedding/pgvector, journal agregasyonu, araç döngüsü) ATLAR; tek provider
    # çağrısı yapar ve araçsız yolda sağlayıcı akışı jeton jeton akar. Kısa yanıt
    # için üst sınır: uzun cevap = daha yavaş ilk-jeton ve boşa maliyet.
    LLM_QUICK_LANE_MAX_TOKENS = max(128, int(os.getenv("LLM_QUICK_LANE_MAX_TOKENS", "4096")))
    LLM_QUICK_LANE_ENABLED = os.getenv("LLM_QUICK_LANE_ENABLED", "true").lower() == "true"
    # Bellek bağlamı OPSİYONEL bağlamdır; embedding sağlayıcısı yavaşsa yanıtı
    # bekletmemeli (embedding çağrısının kendi timeout'u 30 sn).
    LLM_MEMORY_EMBED_TIMEOUT_SEC = max(1.0, float(os.getenv("LLM_MEMORY_EMBED_TIMEOUT_SEC", "4")))
    # Sorgu embedding'i deterministik: aynı sorgu tekrar sorulursa ağ çağrısı yok.
    LLM_EMBED_CACHE_TTL_SEC = max(0.0, float(os.getenv("LLM_EMBED_CACHE_TTL_SEC", "900")))
    LLM_EMBED_CACHE_MAX = max(8, int(os.getenv("LLM_EMBED_CACHE_MAX", "128")))
    
    HARD_STOP_LOSS_PCT = 0.012
    COOLDOWN_BARS = 2
    VELOCITY_REENTRY_COOLDOWN_BARS = max(
        0, int(os.getenv("VELOCITY_REENTRY_COOLDOWN_BARS", "1"))
    )
    # Time-decay spot take-profit: accept the first cost-covered exit as the
    # position ages. Single stage by design; the multi-stage decay and the
    # legacy TAKE_PROFIT_PCT / TRAILING_* knobs were dead configuration and
    # were removed.
    SPOT_PROFIT_TARGET_PCT = 0.01

    # Klasik/sistem stratejileri için exit modeli. LLM_PAPER bu ayarları kullanmaz;
    # kendi planındaki stop, hedef ve max-hold değerleriyle yönetilir.
    SYSTEM_RISK_REWARD = 2.0 if float(os.getenv("SYSTEM_RISK_REWARD", "1.5")) >= 1.75 else 1.5
    SYSTEM_ATR_PERIOD = max(2, int(os.getenv("SYSTEM_ATR_PERIOD", "14")))
    SYSTEM_INITIAL_STOP_ATR_MULTIPLIER = max(0.1, float(os.getenv("SYSTEM_INITIAL_STOP_ATR_MULTIPLIER", "1.0")))
    SYSTEM_ATR_TRAILING_MULTIPLIER = max(0.5, float(os.getenv("SYSTEM_ATR_TRAILING_MULTIPLIER", "2.5")))
    SYSTEM_ATR_TRAILING_ACTIVATION_ATR = max(0.25, float(os.getenv("SYSTEM_ATR_TRAILING_ACTIVATION_ATR", "1.0")))

    # Binance TR spot komisyonu (Bronz/Standart taker %0.15) - işlem başına
    # TABAN oran (indirimsiz). Canlı paper motorları bu sabiti DOĞRUDAN değil,
    # `paper_ledger.commission_pct()` üzerinden (BNB indirimi / override uygulanmış
    # EFEKTİF oran) okur — bkz. aşağıdaki 2026-10-16 bloğu ve `effective_commission_pct`.
    COMMISSION_PCT = float(os.getenv("COMMISSION_PCT", "0.0015"))
    # 2026-10-16 (maliyet/çıkış): BNB ile komisyon modeli.
    # 60 günlük ölçüm (docs/BACKTEST_60G_RESCAN_2026-10-16.md) paper motorlarının
    # yaklaşık gidiş-dönüş maliyeti kadar (%0,35) kaybettiğini gösterdi; kullanıcı
    # Binance TR'de BNB ile komisyon ödemeyi AÇTI. Varsayılan "1" (açık).
    #   COMMISSION_BNB_MODE          : "1"/"true" → taban orana indirim uygulanır.
    #   COMMISSION_BNB_DISCOUNT_PCT  : indirim yüzdesi (25.0 = Binance'in standart
    #       BNB indirimi). Binance TR'nin GERÇEK BNB indirim oranı DOĞRULANMADI
    #       (hesap cevabında ayrı alan yok) — bu yüzden ayarlanabilir; hesap
    #       taker komisyonu ile paper varsayımı farkı /api/binance/fee-mode'da
    #       gösterilir (otomatik düzeltme YAPILMAZ).
    #   COMMISSION_PCT_OVERRIDE      : isteğe bağlı MUTLAK bacak başı kesir
    #       (ör. 0.00075); boş değilse her şeyi ezer (hesaptan okunan gerçek
    #       oranı elle sabitlemek için).
    # Öncelik: OVERRIDE > BNB indirimi (COMMISSION_PCT × (1 − indirim/100)) > COMMISSION_PCT.
    # Tek okuma noktası: `paper_ledger.commission_pct()` / `config.effective_commission_pct()`.
    COMMISSION_BNB_MODE = os.getenv("COMMISSION_BNB_MODE", "1").strip().lower() in ("1", "true", "yes", "on")
    COMMISSION_BNB_DISCOUNT_PCT = max(0.0, min(100.0, float(os.getenv("COMMISSION_BNB_DISCOUNT_PCT", "25.0"))))
    _commission_override_raw = os.getenv("COMMISSION_PCT_OVERRIDE", "").strip()
    COMMISSION_PCT_OVERRIDE: float | None = (
        float(_commission_override_raw) if _commission_override_raw.lower() not in ("", "none", "null") else None
    )
    # 2026-10-17 (kullanıcı hesabı doğrulandı — Binance TR ekranı, BNB açık): maker %0,0675,
    # taker %0,1125 → BNB indirimi %25 DOĞRU; maker tabanı %0,09. Piyasa emri (giriş, stop,
    # zaman/izleyen çıkışı) taker; canlıda kâr al bekleyen LIMIT emirdir (binance_tr_private
    # type=1) → maker. COMMISSION_MAKER_PCT_OVERRIDE boş değilse maker için mutlak kesir.
    COMMISSION_MAKER_PCT = float(os.getenv("COMMISSION_MAKER_PCT", "0.0009"))
    _maker_override_raw = os.getenv("COMMISSION_MAKER_PCT_OVERRIDE", "").strip()
    COMMISSION_MAKER_PCT_OVERRIDE: float | None = (
        float(_maker_override_raw) if _maker_override_raw.lower() not in ("", "none", "null") else None
    )
    # Paper defterlerinde kâr al kapanışı = bekleyen LIMIT dolumu: maker ücreti, satış kayması YOK.
    # Kapalıyken eski davranış (taker + kayma).
    PAPER_TP_MAKER_FILL = os.getenv("PAPER_TP_MAKER_FILL", "1").strip().lower() in ("1", "true", "yes", "on")
    ESTIMATED_SLIPPAGE_PCT = 0.00025
    # 2026-10-16 (backtest onarımı): scripts/run_portfolio_backtest.py tam (gidiş-dönüş
    # değil, tek seferlik) spread'i KESİR olarak okur; her dolumda spread/2 uygulanır.
    # Eski varsayım %0,1 (docs/AUDIT_FIX_REPORT_2026-08-25). Yalnız araştırma/backtest.
    BACKTEST_ASSUMED_SPREAD_PCT = float(os.getenv("BACKTEST_ASSUMED_SPREAD_PCT", "0.001"))
    MIN_EXPECTED_NET_PNL_TRY = 0.5
    # LLM paper-entry gate: an entry is blocked when the live top-of-book spread
    # exceeds this percent (thin-orderbook protection for low-price TRY pairs).
    LLM_MAX_ENTRY_SPREAD_PCT = float(os.getenv("LLM_MAX_ENTRY_SPREAD_PCT", "1.0"))
    # S6 volatility-based sizing: equal-risk scaling around this ATR% baseline.
    VOLATILITY_SIZING_ENABLED = os.getenv("VOLATILITY_SIZING_ENABLED", "true").lower() == "true"
    VOLATILITY_BASELINE_ATR_PCT = max(0.0005, float(os.getenv("VOLATILITY_BASELINE_ATR_PCT", "0.006")))
    VOLATILITY_SIZING_MIN_SCALE = max(0.25, float(os.getenv("VOLATILITY_SIZING_MIN_SCALE", "0.35")))
    # Quiet symbols (< baseline ATR%) may take a proportionally LARGER position;
    # capped here so equal-risk scaling stays bounded (A3 fix).
    VOLATILITY_SIZING_MAX_SCALE = min(2.0, max(1.0, float(os.getenv("VOLATILITY_SIZING_MAX_SCALE", "1.25"))))
    # Strategy circuit breaker (S2): rolling expectancy window and floor.
    STRATEGY_BREAKER_WINDOW = max(10, int(os.getenv("STRATEGY_BREAKER_WINDOW", "20")))
    STRATEGY_BREAKER_EXPECTANCY_FLOOR = float(os.getenv("STRATEGY_BREAKER_EXPECTANCY_FLOOR", "-0.5"))
    # S3 calibration sizing: scale entries by bucketed historical win rate.
    CALIBRATION_SIZING_ENABLED = os.getenv("CALIBRATION_SIZING_ENABLED", "true").lower() == "true"
    # S4 regime-gated sizing: mean-reversion shrinks in trends, continuation
    # shrinks in confirmed ranges.
    REGIME_SIZING_ENABLED = os.getenv("REGIME_SIZING_ENABLED", "true").lower() == "true"
    # S5 dynamic correlation cluster cap (BTC/ETH benchmark, % of equity).
    CORRELATION_CAP_ENABLED = os.getenv("CORRELATION_CAP_ENABLED", "true").lower() == "true"
    CORRELATION_REFRESH_SEC = max(300, int(os.getenv("CORRELATION_REFRESH_SEC", "1800")))
    MAX_CLUSTER_EXPOSURE_PCT = max(20.0, float(os.getenv("MAX_CLUSTER_EXPOSURE_PCT", "60.0")))

    # Otonom Paper Trade (monitoring bildiriminden tetiklenen, 2026-09-04)
    #
    # ÖNCELİK TUZAĞI (2026-10-07 denetimi) — DİKKAT: aşağıdaki `AUTO_PAPER_*`
    # sabitleri "env ile geri alınabilir" görünür ama DİKKAT: admin bir kez
    # `PUT /api/auto-paper/settings` ile kaydettiğinde DB `auto_paper_settings`
    # satırı oluşur ve çalışma anında env'i EZER. Yani geri alma sırası:
    #     DB auto_paper_settings  >  env (AUTO_PAPER_*)  >  bu koddaki varsayılan
    # Env rollback (ör. `AUTO_PAPER_SL_PCT=1.5`) admin kaydı varsa SESSİZCE
    # etkisizdir; önce DB satırı temizlenmeli/sıfırlanmalıdır. Bu, config.py
    # içinde çözülemez (önceliği DB okuma katmanı belirler) → yalnızca
    # belgelenir; env'i varsayılana sıfırlamak da aynı tuzağa düşer.
    #
    # A3 (2026-09-14) ANKRAJI: `auto_paper` bu eşiği `monitoring.normalize_score`
    # PANEL skoruyla karşılaştırır. Eski panel 50 = ham 1000 (lineer, cap 2000);
    # log haritada aynı ham nokta panel 68.2 → DEĞER KORUNARAK yeniden ankrajlandı.
    AUTO_PAPER_MIN_SCORE_DEFAULT = float(os.getenv("AUTO_PAPER_MIN_SCORE", "68.2"))
    AUTO_PAPER_BALANCE_PCT_DEFAULT = float(os.getenv("AUTO_PAPER_BALANCE_PCT", "35"))
    # 2026-10-07 OPTIMIZASYON: 1.5 -> 5.0. KANIT (30 gun, 256 sembol, gercek
    # Binance TR 5dk mumlari, 3214 bildirim, mum-ici replay, maliyet %0.325):
    # sig stop sinyalin 5 dk'lik gurultusu icinde islemlerin yarisini kesiyordu.
    # SL 1.5 -> -0.85%/islem, SL 4.0 -> +1.32%, SL 5.0 -> +1.38%, SL 6.0 -> +1.41%.
    # Canlida 4.0 -> 1.5 denemesi 7 KAT kotu sonuc vermisti (bkz. teshis §4).
    # Genis stop = felaket sigortasi; kazananlari kesme, kuyrugu -%28'den -%5'e indir.
    # Tek env kaynağı: `AUTO_PAPER_SL_PCT` — bilinçli olarak `MONITORING_RR_SL_PCT`
    # (yukarıda) ile AYNI anahtar. Eskiden burada `AUTO_PAPER_SL_PCT_DEFAULT`
    # okunurken RR dayanağı `AUTO_PAPER_SL_PCT` okuyordu; teşhis §6'daki geri-alma
    # komutu (`AUTO_PAPER_SL_PCT=1.5`) yalnız birini çekip RR ölçümünü / parite
    # testini bozuyordu. Artık tek isim, drift imkânsız. (Sabit ADI geriye dönük
    # uyum için `AUTO_PAPER_SL_PCT_DEFAULT` kalır — yalnız env anahtarı değişti.)
    AUTO_PAPER_SL_PCT_DEFAULT = float(os.getenv("AUTO_PAPER_SL_PCT", "5.0"))
    # 2026-10-15 (denetim düzeltmesi, madde 7): ATR nefes payı TAVANI (yüzde).
    # Otonom açılışta effective_sl = max(sl_pct, min(TAVAN, 1.2×ATR%)) — ATR
    # stop'u yalnız GENİŞLETİR (asla daraltmaz), genişletme bu tavanla sınırlı.
    # Eski kod tavan yerine sl_pct'nin kendisini kullanıyordu → ATR ölü koddu.
    AUTO_PAPER_ATR_SL_CAP_PCT = float(os.getenv("AUTO_PAPER_ATR_SL_CAP_PCT", "2.8"))
    AUTO_PAPER_DEFAULT_TARGET_PCT = float(os.getenv("AUTO_PAPER_DEFAULT_TARGET_PCT", "1.5"))  # Eski varsayılan 2.0 → 1.5 (2026-09-17, Erkan kararı: radar/velocity bildirimlerinin hedefi MFE tavanına otursun; replay geometrisi + canlı 50 işlem verisi).
    AUTO_PAPER_MIN_ORDER_TRY = float(os.getenv("AUTO_PAPER_MIN_ORDER_TRY", "50.0"))
    # Hedef tavanı (2026-10-07): bildirimin kendi `target_pct`'i bu değeri aşarsa
    # TP buraya çekilir. NEDEN VAR: `AUTO_PAPER_DEFAULT_TARGET_PCT` yalnızca
    # bildirimde hedef YOKSA kullanılır; canlıda hedef ort. +%3,90 geliyordu,
    # ulaşılan tepe medyanı +%1,62 — yani işlemlerin %87'si hedefe hiç değmiyordu.
    # 0 = sınırsız (eski davranış).
    AUTO_PAPER_MAX_TARGET_PCT = float(os.getenv("AUTO_PAPER_MAX_TARGET_PCT", "0"))
    # Başabaş (Breakeven) koruması: erken minik kârla çıkıp ralliyi kaçırmamak için
    # varsayılan KAPALI. 2026-10-07 incelemesi: breakeven'i ZORUNLU kılmanın kanıtı
    # yok — gerçekleşen kazanan ortalaması (+%1,51) zaten net_floor'un üzerinde,
    # yani "%0,325'e kilitlenip kalanı kaybetme" senaryosu veride yok (zarar
    # asimetrisi sig stop'tan geliyordu, breakeven eksikliğinden değil).
    AUTO_PAPER_BREAKEVEN_ENABLED = os.getenv("AUTO_PAPER_BREAKEVEN_ENABLED", "false").lower() == "true"
    # 2026-09-28 kârlılık düzeltmesi: erken breakeven kâr korumasını trailing'den
    # ÖNCE devreye sokar — trailing aktif olduğunda stop zaten maliyet üstünde olur
    # ve zarar riski sıfırlanır. Varsayılan %1.0.
    AUTO_PAPER_BREAKEVEN_TRIGGER_PCT = float(os.getenv("AUTO_PAPER_BREAKEVEN_TRIGGER_PCT", "1.0"))
    # Trailing stop modülü (kâr takibi): pozisyon trailing_trigger_pct kadar
    # kara geçince aktifleşir ve fiyatı trailing_gap_pct geriden takip eder.
    # Varsayılan AÇIK; trailing_enabled=false ile kapatılabilir.
    AUTO_PAPER_TRAILING_ENABLED = os.getenv("AUTO_PAPER_TRAILING_ENABLED", "true").lower() == "true"
    # 2026-10-11 KULLANICI DÜZELTMESİ: trailing %1 kârda aktive olup %1 geriden
    # takip ederse stop = tepe×(1−0.01) girişe çok yakın/altına düşebilir →
    # kâra geçmiş işlem ZARARLA kapanabilir. Kural: aktive eşiği (trigger) takip
    # boşluğundan (gap) BÜYÜK olmalı → trigger %2, gap %1. Böylece aktifleştiğinde
    # stop en kötü ihtimalle girişin +%1 üstünde kalır (kâr kilitli).
    AUTO_PAPER_TRAILING_TRIGGER_PCT = float(os.getenv("AUTO_PAPER_TRAILING_TRIGGER_PCT", "2.0"))
    # 2026-10-11 CANLI GERİ BİLDİRİM: gap 0.3 ÇOK DARDI — canlı 5 sn ticker
    # gürültüsünde fiyat tepeden %0.3 geri çekilince pozisyon ANINDA kapanıyor,
    # kâr büyüyemiyordu ("trailing çok yakın takip ediyor" — kullanıcı). Backtest
    # 1m barlarıyla yapıldığı için 0.3'ü "iyi" gösteriyordu; canlıda ticker daha
    # gürültülü. Canlıya uygun: 1.0 (tepeden anlamlı geri çekilme toleransı).
    # NOT: gap, trigger'dan KÜÇÜK olmalı (yukarıdaki kural) → %2 tetik / %1 gap.
    AUTO_PAPER_TRAILING_GAP_PCT = float(os.getenv("AUTO_PAPER_TRAILING_GAP_PCT", "1.0"))
    # Trailing/breakeven kapanışı sonrası aynı bildirimle yeniden açılış
    # (fiyat bildirim fiyatının üzerinde + ufuk süresi dolmadı + yükselme
    # eğilimi varsa). 2026-09-29 kârlılık analizi: koruma kapanışı sonrası
    # hemen yeniden açma 9 işlemde +79.40 TRY kârı geri vermişti — varsayılan
    # KAPALI; false ile kapatılabilir (zaten kapalı), true ile açılabilir.
    AUTO_PAPER_REOPEN_AFTER_PROTECT_CLOSE = os.getenv("AUTO_PAPER_REOPEN_AFTER_PROTECT_CLOSE", "false").lower() == "true"
    # 2026-09-29 kârlılık koruması: kârlı kapanış (TP/trailing/breakeven veya
    # pozitif PnL) sonrası aynı sembole 15 dakika yeni pozisyon açılmaz.
    # Kâr realizasyonunun hemen ardından tepeden yeniden girip kârı geri
    # verme tuzağını (post-win churn) engeller.
    AUTO_PAPER_POST_WIN_COOLDOWN_MINUTES = float(os.getenv("AUTO_PAPER_POST_WIN_COOLDOWN_MINUTES", "15.0"))
    # D-11 (2026-09-12): otonom paper için global maksimum açık pozisyon sayısı.
    # Eskiden varsayılan 0 (= sınırsız) idi; farklı sembollerden gelen bildirim
    # zinciri cüzdanı tek turda tüketebiliyordu. Güvenli varsayılan 3 idi;
    # Erkan kararı (2026-09-18) ile 8 — UI (Ayarlar > Otonom Paper Trade)
    # üzerinden de değiştirilebilir (DB `auto_paper_settings.max_open_positions`
    # önceliklidir; açıkça 0 verilirse sınırsız).
    AUTO_PAPER_MAX_OPEN_POSITIONS = max(0, int(os.getenv("AUTO_PAPER_MAX_OPEN_POSITIONS", "8")))
    # B1-B5: otonom paper dinamik çıkış ayarları.
    # Dinamik breakeven ve trailing kâr korumayı hedefin %70-%80'ine kadar geciktirerek
    # +%2.75 kârın stop-loss'a dönmesine neden oluyordu; varsayılan KAPALI ve tavan korumalı yapıldı.
    # 2026-10-07 OPTIMIZASYON: true -> false. KANIT (30 gun, gercek mumlar,
    # trend_devam + dedup, ayni diger ayarlarla):
    #     TP cikisi ACIK : +0.461%/islem  [train +0.716 / test -0.135]
    #     TP cikisi KAPALI: +1.375%/islem  [train +1.746 / test +0.508]
    # TP = bildirim hedefi (canlida ort +%4,30) sert bir tavan gibi calisiyordu;
    # tepe medyani +%1,62 oldugu icin cogu islem hedefe hic degmiyor, degince de
    # kazanan erken kesiliyordu. Kapatilinca cikisi trailing + genis SL belirler
    # ve test seti negatiften pozitife donuyor. (max_target_pct ile ayni sebep.)
    AUTO_PAPER_TP_PRIMARY_ENABLED = os.getenv("AUTO_PAPER_TP_PRIMARY_ENABLED", "false").lower() == "true"
    # 2026-10-16 (maliyet/çıkış): otonom paper ÇIKIŞ PROFİLİ.
    #   mevcut  : bugünkü varsayılanlar (SL 5.0 / tetik 2.0 / gap 1.0 / TP-primary
    #             kapalı — yukarıdaki sabitler neyse o). VARSAYILAN.
    #   kalibre : calibrate_combined_paper walk-forward'ında 7/30/60 günde en iyi
    #             hücre — SL 0.8 / trailing tetik 1.0 / trailing gap 0.8 /
    #             TP-primary kapalı. 60 günde test EV −0.157 (taban −0.250 %/işlem).
    # Öncelik (yüksekten düşüğe): DB'ye kaydedilmiş admin ayarı (auto_paper_settings)
    # > profil (kalibre) > env/config sabitleri. Profil yalnız VARSAYILANLARI
    # değiştirir; UI'dan kaydedilmiş bir değer varsa ona dokunmaz.
    # Varsayılan `mevcut` kalır: canlıda dar SL (4.0 → 1.5) bir kez 7 KAT kötü
    # sonuç vermişti (bkz. AUTO_PAPER_SL_PCT_DEFAULT yorumu); kalibre profil
    # önce gerçek dolumlarla ölçülmeli. Çözümleme: `config.auto_paper_exit_defaults()`.
    AUTO_PAPER_EXIT_PROFILE = os.getenv("AUTO_PAPER_EXIT_PROFILE", "mevcut").strip().lower() or "mevcut"
    AUTO_PAPER_EXIT_PROFILES = {
        "mevcut": {},
        "kalibre": {
            "stop_loss_pct": 0.8,
            "trailing_trigger_pct": 1.0,
            "trailing_gap_pct": 0.8,
            "tp_primary_exit_enabled": False,
        },
    }
    # TP-CANCEL-ON-TRAIL (2026-10-09, opsiyonel — varsayilan KAPALI, canlida
    # KAPALI BIRAKILDI: bkz. asagidaki canli-parametre bulgusu).
    # Trailing devreye girdigi AN sabit TP emri IPTAL edilir (take_profit=0 +
    # `tp_cancelled` bayragi); cikis tamamen trailing'e kalir. Forex
    # (scalperagent_global) kanitinda bu mekanizma 4/4 pencerede kazandi.
    # BU PROJEDE kanon parametrelerle A/B (work/ab_tp_cancel.py, 30 gun gercek
    # mum, 1231 islem, SL 5.0/trig 1.0/gap 0.3/120dk):
    #   A ratchet +0.299%  B cancel +0.436%  -> B-A +0.138%, p=2e-14, 5/6 pencere.
    # ANCAK canli DB `auto_paper_settings` satiri bu kanon grid'de DEGIL
    # (SL 1.5 / trig 1.8 / gap 0.6 / 60 dk). Canli degerlerle ayni A/B
    # (work/ab_tp_cancel_live.py, 1232 islem) SIRALAMAYI TERSINE CEVIRIYOR:
    #   A ratchet -0.073%/islem (0/6 pencere)   B cancel -0.034% (0/6, B-A yalniz
    #   +0.040%)   C tp_primary kapali +0.479% (6/6 pencere, 75/75 kombinasyon,
    #   train+test pozitif, maxDD 183->37).
    # Sebep: canlida TRIG (1.8) > TP (medyan 3.38) — sabit TP trailing devreye
    # GIRMEDEN doluyor, "iptal ani" olusmuyor. Bu yuzden canlida B degil C
    # (AUTO_PAPER_TP_PRIMARY_ENABLED=false) uygulandi; B kapali.
    # 2026-09-18'de ayni mekanizma basarisiz olmustu; o gunku basarisizlik TP
    # silininin BE/trailing tarafindan GERI DIRILTILMESINDEN geliyordu. Bu
    # uygulama tek-yol TP yazimi ile dirilmeyi engeller (bkz. auto_paper
    # `cancel_auto_paper_trade_tp` + `update_auto_paper_trade_tp` icindeki
    # `tp_cancelled` bekcisi).
    AUTO_PAPER_TP_CANCEL_ON_TRAIL = os.getenv("AUTO_PAPER_TP_CANCEL_ON_TRAIL", "false").lower() == "true"
    AUTO_PAPER_DYNAMIC_BREAKEVEN_ENABLED = os.getenv("AUTO_PAPER_DYNAMIC_BREAKEVEN_ENABLED", "false").lower() == "true"
    AUTO_PAPER_DYNAMIC_TRAILING_ENABLED = os.getenv("AUTO_PAPER_DYNAMIC_TRAILING_ENABLED", "false").lower() == "true"
    AUTO_PAPER_BREAKEVEN_BUFFER_PCT = float(os.getenv("AUTO_PAPER_BREAKEVEN_BUFFER_PCT", "0.02"))
    # Otonom Paper maksimum pozisyon açık kalma süresi (dakika).
    # 2026-10-07 OPTIMIZASYON: 60 -> 120. KANIT: 60/90/120/180/240 dk sirasiyla
    # +1.389/+1.383/+1.375/+1.364/+1.391%/islem — tavan sonuca duyarsiz (cikisi
    # trailing + SL belirliyor). 120 dk secildi: 30-60 dk bandinda max_duration
    # kapanislari ort -%1,08 uretiyordu (bkz. teshis §2); sinyalin gercek
    # yukselisine nefes payi birakmak zarari kesiyor, asiri tasima da yok.
    AUTO_PAPER_MAX_HOLD_MINUTES = float(os.getenv("AUTO_PAPER_MAX_HOLD_MINUTES", "120.0"))
    # 2026-10-16 (tarama güncellemesi): otonom paper MOD listesi env'den
    # (virgüllü). Eski gömülü varsayılan `trend_devam,unified` idi. 7 günlük
    # bildirim ölçümü (279 ölçülebilir bildirim, 5m mum): trend_devam n=150
    # hit60 %52.7 net 0.00; unified n=41 hit60 %19.5 (kayıtlı hedef isabeti
    # %3.7); notr net −1.09 (stop %18); v_donusu 0/10 → yalnız `trend_devam`.
    # Boş değer = TÜM modlar (eski davranış). DİKKAT: DB `auto_paper_settings`
    # kayıtlı listesi bu varsayılanı EZER (get_auto_paper_settings). Kayıt:
    # docs/DENEY_KAYDI.md.
    AUTO_PAPER_ALLOWED_MODES = os.getenv("AUTO_PAPER_ALLOWED_MODES", "trend_devam").strip()
    # 2026-10-15 (denetim düzeltmesi, madde 14): auto_paper içine gömülü sabitler
    # tek config kaynağına taşındı. Varsayılanlar ESKİ gömülü değerlerle aynı —
    # davranış değişmedi, yalnız env ile ayarlanabilir oldu.
    #   * SL/breakeven kapanışı sonrası yeniden giriş bekleme süresi (dk).
    AUTO_PAPER_SL_COOLDOWN_MINUTES = float(os.getenv("AUTO_PAPER_SL_COOLDOWN_MINUTES", "5.0"))
    #   * Yönetim döngüsünün açılıştaki ilk bekleme süresi (sn).
    AUTO_PAPER_LOOP_STARTUP_DELAY_SEC = float(os.getenv("AUTO_PAPER_LOOP_STARTUP_DELAY_SEC", "30"))
    #   * Koruma kapanışı sonrası yeniden açma saat kovası (sn; D-06 churn sınırı).
    AUTO_PAPER_REOPEN_HOUR_BUCKET_SEC = int(os.getenv("AUTO_PAPER_REOPEN_HOUR_BUCKET_SEC", "3600"))
    # 2026-10-15 (denetim düzeltmesi, madde 1): ticker bayat ve REST yedeği de
    # başarısızsa, tutma süresi max_hold×ÇARPAN'ı aşınca pozisyon son bilinen
    # fiyatla zorla kapatılır (exit_reason=stale_force_close). Eski kod bu
    # durumda pozisyonu süresiz "izleniyor"da bırakıyordu.
    AUTO_PAPER_STALE_FORCE_CLOSE_FACTOR = float(os.getenv("AUTO_PAPER_STALE_FORCE_CLOSE_FACTOR", "1.5"))
    # 2026-10-16 (giriş gecikmesi): bildirim `detected_at` ile paper dolum
    # (`entry_time`) arasındaki süre bu eşiği (sn) aşarsa `logger.warning`.
    # Yalnız GÖZLEM — davranış değişmez. Giriş TETİKLEMESİ olay güdümlüdür
    # (monitoring `_notify` → `try_open_from_notification`, anında); bu yüzden
    # ayrı bir "pickup aralığı" ayarı YOKTUR (yönetim döngüsünün 5 sn'si yalnız
    # SL/TP izleme içindir). Kayıt: docs/DENEY_KAYDI.md.
    AUTO_PAPER_ENTRY_LATENCY_WARN_SEC = float(os.getenv("AUTO_PAPER_ENTRY_LATENCY_WARN_SEC", "15"))
    # 2026-10-16 (giriş gecikmesi): otonom girişi LLM ikinci göz kararına kadar ERTELEME.
    # Ölçüm: ertelenen girişlerde gecikme medyanı 56.7 sn (ertelenmeyende 0.3 sn) ve LLM
    # kararı isabeti artırmıyor (FAKE %41 vs DEVAM %30). Varsayılan KAPALI: giriş anında
    # yapılır, LLM kararı yalnız sonradan RE-OPEN'i bastırır (eski davranış). "1" = ertele.
    AUTO_PAPER_LLM_SECOND_EYE_DEFER = os.getenv("AUTO_PAPER_LLM_SECOND_EYE_DEFER", "0").strip() == "1"
    # Radar & Sinyal başarı ölçüm penceresi (dakika, 2026-09-22 Erkan kararı).
    # 5dk'da erken kapatıp hedefe daha sonra ulaşan başarılı sinyalleri ıska saymamak için
    # otonom işlem maksimum ömrüyle (60 dk) tam senkronize çalışır.
    MONITORING_OUTCOME_WINDOW_MINUTES = int(os.getenv("MONITORING_OUTCOME_WINDOW_MINUTES", "60"))

    # MACD MONITOR / SIRÇRAMA ADAYI ayarları (DB üzerinden değiştirilebilir;
    # burada yalnızca varsayılanlar). Eşik ve alarm/push anahtarları.
    MACD_JUMP_MIN_SCORE_DEFAULT = max(0, min(100, int(os.getenv("MACD_JUMP_MIN_SCORE", "60"))))
    MACD_JUMP_ALERTS_ENABLED = os.getenv("MACD_JUMP_ALERTS_ENABLED", "true").lower() == "true"
    MACD_JUMP_PUSH_ENABLED = os.getenv("MACD_JUMP_PUSH_ENABLED", "true").lower() == "true"
    # Erken sinyal alarmları (YAKLAŞIYOR → KIRILIM aşamalı öncü sistem) —
    # varsayılan AÇIK: M5 zirveye yaklaşma, M1 öncü kırılım, MACD dip dönüşü.
    MACD_EARLY_ALERTS_ENABLED = os.getenv("MACD_EARLY_ALERTS_ENABLED", "true").lower() == "true"
    # C7 — erken cooldown'ı kanıta dayalı adapt yap (varsayılan KAPALI; davranışı
    # değiştirmez). Replay kanıtı §4-C7: dip yeniden-arme medyanı ~150 dk, sabit
    # 30 dk onu kesiyor. Açılınca dip için 30–150 dk aralığında ölçeklenir
    # (kanıt → replay → paper kuralı; aktive DEĞİL, yalnız gözlem).
    MACD_EARLY_ADAPTIVE_COOLDOWN = os.getenv("MACD_EARLY_ADAPTIVE_COOLDOWN", "false").lower() == "true"

    # ---- "Isınıyor" (warm) şeridi + keşif havuzu (2026-09-26) ----
    # Warm şeridi: eşiği kıl payı kaçıran adayların erken görünürlük listesi.
    # AUTO-ENTRY'YE BAĞLI DEĞİLDİR — yalnız panel/bildirim katmanı okur.
    MONITORING_WARM_LIST_LIMIT = max(1, int(os.getenv("MONITORING_WARM_LIST_LIMIT", "12")))
    # Keşif A (!miniTicker@arr): 1m momentum+hacim patlaması yakalayan erken
    # keşif akışının tarama havuzuna enjekte edilecek sembol limitleri/eşikleri.
    DISCOVERY_MIN_RETURN_1M_PCT = float(os.getenv("DISCOVERY_MIN_RETURN_1M_PCT", "0.4"))
    DISCOVERY_MIN_VOLUME_BURST = float(os.getenv("DISCOVERY_MIN_VOLUME_BURST", "2.0"))
    DISCOVERY_POOL_INJECT_LIMIT = max(1, int(os.getenv("DISCOVERY_POOL_INJECT_LIMIT", "8")))
    # Keşif nabzı (pulse) + olay güdümlü hızlı tarama (2026-09-26, "daha erken").
    # Pulse: GET /state ham keşif adaylarını (kapanmış mum/scan turu beklemeden)
    # yayınlar. Fast scan: keşif güçlü fiyat+hacim patlaması görürse 30 sn'lik
    # tarama turunu beklemeden _run_scan koşar → warm/teyit ve bildirim yolu
    # saniyeler içinde hızlanır. Kapılar: sembol cooldown'u + global min gap
    # (tarama frekansı sınırsız büyümesin) + running kilidi + ENABLE anahtarı.
    DISCOVERY_PULSE_LIMIT = max(1, int(os.getenv("DISCOVERY_PULSE_LIMIT", "15")))
    DISCOVERY_FAST_SCAN_RETURN_20S = float(os.getenv("DISCOVERY_FAST_SCAN_RETURN_20S", "0.5"))
    DISCOVERY_FAST_SCAN_BURST = float(os.getenv("DISCOVERY_FAST_SCAN_BURST", "3.0"))
    DISCOVERY_FAST_SCAN_COOLDOWN_SEC = max(30, int(os.getenv("DISCOVERY_FAST_SCAN_COOLDOWN_SEC", "90")))
    DISCOVERY_FAST_SCAN_MIN_GAP_SEC = max(10, int(os.getenv("DISCOVERY_FAST_SCAN_MIN_GAP_SEC", "15")))
    DISCOVERY_FAST_SCAN_ENABLED = os.getenv("DISCOVERY_FAST_SCAN_ENABLED", "true").lower() == "true"

    # NOT (2026-10-12): Harici Binance Global→TR "lead-lag sinyal köprüsü"
    # (`tr_bridge_receiver` + `/api/bridge/*`) KALDIRILDI. Karar: farklı bir
    # uygulamadan sinyal almak yerine Global verisini v4 İÇİNDE işleyip sinyal
    # üretmek (bkz. `global_radar.py` + `global_lead_lag.py`). Eski
    # `BINANCE_TR_BRIDGE_*` ortam değişkenleri artık okunmaz.

    # Global erken-tespit katmanının TR sembol tipi kapısı. True iken Global'de
    # yakalanan bir hareket YALNIZCA Binance TR'de listeli baz varlığa sahipse
    # (BTCUSDT→BTCTRY) TR bildirimi/otonom işlemine dönüşür. Kapatmak yalnız
    # hata ayıklama içindir — kapatılırsa TR'de işlem açılamayan semboller için
    # sinyal üretilir ve `map_to_tr_symbol` fiyat bulamaz.
    BINANCE_TR_FILTER_ENABLED = os.getenv("BINANCE_TR_FILTER_ENABLED", "true").lower() == "true"
    # Global kaynaklı işlemlerin öğrenme/kalite analizi için İÇ strateji işareti.
    # Arayüzde GÖSTERİLMEZ (plan aşama 4): kullanıcı yalnız TR sinyali görür.
    GLOBAL_SIGNAL_STRATEGY = os.getenv("GLOBAL_SIGNAL_STRATEGY", "GLOBAL_LEAD_LAG")

    @classmethod
    def effective_commission_pct(cls) -> float:
        """2026-10-16 (maliyet/çıkış): EFEKTİF bacak başı komisyon (KESİR).

        Öncelik: COMMISSION_PCT_OVERRIDE (mutlak) > BNB modu
        (COMMISSION_PCT × (1 − COMMISSION_BNB_DISCOUNT_PCT/100)) > COMMISSION_PCT.
        Varsayılanlarla: 0.0015 × 0.75 = 0.001125 (%0,1125/bacak).
        `paper_ledger.commission_pct()` bu fonksiyonu sarar; iki yerde formül yok.
        """
        override = cls._cfg_attr("COMMISSION_PCT_OVERRIDE", None)
        if override is not None:
            try:
                return max(0.0, float(override))
            except (TypeError, ValueError):
                pass
        base = float(cls._cfg_attr("COMMISSION_PCT", 0.0015))
        if cls._cfg_attr("COMMISSION_BNB_MODE", False):
            discount = float(cls._cfg_attr("COMMISSION_BNB_DISCOUNT_PCT", 0.0) or 0.0)
            discount = max(0.0, min(100.0, discount))
            return base * (1.0 - discount / 100.0)
        return base

    @classmethod
    def effective_maker_commission_pct(cls) -> float:
        """2026-10-17: EFEKTİF maker bacak komisyonu (KESİR).

        Öncelik: COMMISSION_MAKER_PCT_OVERRIDE > BNB modu (COMMISSION_MAKER_PCT × (1 − indirim/100))
        > COMMISSION_MAKER_PCT. Varsayılanlarla 0.0009 × 0.75 = 0.000675 (%0,0675/bacak).
        """
        override = cls._cfg_attr("COMMISSION_MAKER_PCT_OVERRIDE", None)
        if override is not None:
            try:
                return max(0.0, float(override))
            except (TypeError, ValueError):
                pass
        base = float(cls._cfg_attr("COMMISSION_MAKER_PCT", 0.0009))
        if cls._cfg_attr("COMMISSION_BNB_MODE", False):
            discount = float(cls._cfg_attr("COMMISSION_BNB_DISCOUNT_PCT", 0.0) or 0.0)
            discount = max(0.0, min(100.0, discount))
            return base * (1.0 - discount / 100.0)
        return base

    @classmethod
    def round_trip_cost_tp(cls) -> float:
        """2026-10-17: kâr al ile kapanan işlemin gidiş-dönüş maliyeti (KESİR).

        Giriş taker + giriş kayması; çıkış bekleyen LIMIT (maker, kayma yok).
        PAPER_TP_MAKER_FILL kapalıysa `round_trip_cost()` ile aynı.
        -> BNB açık: 0.001125 + 0.000675 + 0.00025 = 0.00205 (%0,205)
        """
        if not cls._cfg_attr("PAPER_TP_MAKER_FILL", False):
            return cls.round_trip_cost()
        return (cls.effective_commission_pct() + cls.effective_maker_commission_pct()
                + float(cls._cfg_attr("ESTIMATED_SLIPPAGE_PCT", 0.00025)))

    @classmethod
    def _cfg_attr(cls, name: str, default=None):
        """Bayrağı önce `config` ÖRNEĞİNDEN (testlerde patch.object edilen), yoksa sınıftan oku.

        Sınıf metotları `cls.X` okuduğunda örnek üzerindeki patch'ler görünmez;
        `Config.min_net_exit_pct(...)` sınıf çağrıları da çalışmaya devam etsin diye
        classmethod kalır, değerler örnekten çözülür.
        """
        inst = globals().get("config")
        if inst is not None and isinstance(inst, cls):
            return getattr(inst, name, default)
        return getattr(cls, name, default)

    @classmethod
    def round_trip_cost(cls) -> float:
        """Gidiş-dönüş maliyet: iki bacak komisyon + iki bacak slippage (KESİR).

        D-06 (2026-09-14) tek kaynak: `min_net_exit_pct` VE velocity gerçekleşen
        çıkış metriği aynı sayıyı kullanır; kopya formül üretilmez.
        2026-10-16 (maliyet/çıkış): komisyon bacağı EFEKTİF oran
        (`effective_commission_pct`, BNB indirimi/override dahil).
        -> BNB açık: (0.001125 + 0.00025) * 2 = 0.00275 (%0,275);
           BNB kapalı: (0.0015 + 0.00025) * 2 = 0.0035 (%0,35)
        """
        return cls.effective_commission_pct() * 2 + float(cls._cfg_attr("ESTIMATED_SLIPPAGE_PCT", 0.00025)) * 2

    @classmethod
    def auto_paper_exit_defaults(cls) -> dict:
        """2026-10-16 (maliyet/çıkış): otonom paper çıkış VARSAYILANLARI (profil uygulanmış).

        Döner: {stop_loss_pct, trailing_trigger_pct, trailing_gap_pct,
        tp_primary_exit_enabled, profile}. `mevcut` → config sabitleri;
        `kalibre` → AUTO_PAPER_EXIT_PROFILES["kalibre"] üstüne yazar. Bilinmeyen
        profil adı `mevcut` gibi davranır. DB'ye kaydedilmiş admin ayarı bu
        varsayılanların ÜSTÜNDEDİR (auto_paper.get_auto_paper_settings).
        """
        base = {
            "stop_loss_pct": float(cls._cfg_attr("AUTO_PAPER_SL_PCT_DEFAULT", 5.0)),
            "trailing_trigger_pct": float(cls._cfg_attr("AUTO_PAPER_TRAILING_TRIGGER_PCT", 2.0)),
            "trailing_gap_pct": float(cls._cfg_attr("AUTO_PAPER_TRAILING_GAP_PCT", 1.0)),
            "tp_primary_exit_enabled": bool(cls._cfg_attr("AUTO_PAPER_TP_PRIMARY_ENABLED", False)),
        }
        name = str(cls._cfg_attr("AUTO_PAPER_EXIT_PROFILE", "mevcut") or "mevcut").strip().lower()
        profiles = cls._cfg_attr("AUTO_PAPER_EXIT_PROFILES", {}) or {}
        overlay = profiles.get(name)
        if overlay is None:
            name = "mevcut"
            overlay = {}
        base.update({k: v for k, v in dict(overlay).items() if k in base})
        base["profile"] = name
        return base

    @classmethod
    def min_net_exit_pct(cls, order_value: float | None = None) -> float:
        """Gross move needed to cover round-trip costs plus minimum net PnL."""
        value = float(order_value or cls.DEFAULT_ORDER_TRY)
        if value <= 0:
            return cls.round_trip_cost()
        return (cls.round_trip_cost()
                + cls.MIN_EXPECTED_NET_PNL_TRY / value)

config = Config()

# Güvenlik: placeholder session secret ile başlatmayı reddet. Placeholder
# değer herkese açıktır; onunla imzalanan oturum çerezleri sahte üretilebilir.
# Secret'lar `_env_secret` ile okunur → Docker/Coolify dosya-secret desteği:
# `SCALPER_SESSION_SECRET_FILE`, `SCALPER_ADMIN_PASSWORD_FILE` (boş olmayan env
# değeri yine kazanır).
_PLACEHOLDER_SECRETS = {
    "replace-with-at-least-32-random-bytes",
    "changeme",
    "change-me",
}
_session_secret = _env_secret("SCALPER_SESSION_SECRET", "").strip()
if _session_secret and _session_secret in _PLACEHOLDER_SECRETS:
    raise RuntimeError(
        "SCALPER_SESSION_SECRET placeholder değeriyle başlatılamaz; "
        "en az 32 rastgele bayt üretip .env dosyasına yazın."
    )
if _session_secret and len(_session_secret) < 32:
    print("[config] UYARI: SCALPER_SESSION_SECRET 32 karakterden kısa; güçlü bir secret üretin.")
# G-17 (2026-09-12): zayıf yönetici şifresi artık yalnızca UYARI vermiyor —
# üretim modunda başlatmayı ENGELLİYOR. Geliştirme modunda (varsayılan) davranış
# korunur (yalnızca uyarı) ki yerel kurulumlar kırılmasın.
# Mod seçimi: SCALPER_ENV > ENVIRONMENT > "development". Yalnızca
# {"production","prod"} üretim sayılır.
_WEAK_ADMIN_PASSWORDS = {"admin", "password", "12345678", "1234567890"}


def admin_password_policy_message(password: str) -> str | None:
    """Zayıf yönetici şifresi için açıklama; güçlü/boş ise None.

    Politika: en az 10 karakter, tamamen rakam DEĞİL ve yaygın sözlük değeri
    DEĞİL. Bu, `main.py::_require_admin`in tek yetki kapısı olduğu bir sistemde
    savunma derinliğidir; parola hiçbir zaman loglanmaz (yalnızca politika
    ihlali loglanır).
    """
    if not password:
        return None
    if (len(password) < 10
            or password.isdigit()
            or password.lower() in _WEAK_ADMIN_PASSWORDS):
        return ("SCALPER_ADMIN_PASSWORD zayıf/öngörülebilir: en az 10 karakter, "
                "harf+rakam karışımı ve yaygın sözlük değeri dışında olmalı.")
    return None


def enforce_admin_password_policy(password: str, *, production: bool) -> None:
    """Politika ihlalinde üretimde RuntimeError, geliştirmede uyarı.

    Tek karar noktası: hem modül yüklemesi hem testler bu fonksiyonu kullanır,
    böylece "uyarıyı RuntimeError'a çevir" davranışı tek yerden doğrulanır.
    """
    # 2026-10-07: BOŞ parola da fail-closed'dır (üretimde). Eskiden boş parola
    # "politika ihlali değil" sayılıyordu → SCALPER_ADMIN_PASSWORD hiç
    # tanımlanmamış bir prod deploy'u, admin kapısı hiç kurulmadan açılıyordu.
    # `admin_password_policy_message("")` (zayıflık denetimi) geriye dönük
    # Nonesini korur; asıl ZORLAMA burada, boşluk ayrı ele alınır.
    if not str(password or "").strip():
        if production:
            raise RuntimeError(
                "[config] SCALPER_ADMIN_PASSWORD tanımlı değil (boş) ve "
                "SCALPER_ENV=production.\n"
                "[config] NEDEN: boş parola, admin/yetki kapısının hiç "
                "kurulmaması demektir; üretimde fail-closed zorunludur.\n"
                "[config] ÇÖZÜM: Coolify panelden güçlü bir SCALPER_ADMIN_PASSWORD "
                "tanımlayın (>=10 karakter, harf+rakam); değeri loglamayın."
            )
        print("[config] UYARI: SCALPER_ADMIN_PASSWORD boş; üretimde başlatma "
              "engellenir (geliştirme modunda yalnızca uyarı).")
        return
    message = admin_password_policy_message(password)
    if not message:
        return
    if production:
        # 2026-09-26: bu hata prod deploy'unu iki kez durdurdu ve Coolify
        # deploy logunda backend loglarını göstermediği için sebep
        # görünmüyordu. Bu yüzden mesaj artık KENDİ KENDİ YETERLİ:
        # ne olduğunu, neden olduğunu ve iki somut çözümü içerir.
        # Parola DEĞERİ hiçbir zaman loglanmaz — yalnızca politika ihlali.
        raise RuntimeError(
            "[config] " + message + "\n"
            "[config] NEDEN: SCALPER_ENV=production iken parola politikası ZORUNLU'dur;\n"
            "[config]   ihlal ederse backend başlamaz (bu bir hata değil, korumadır).\n"
            "[config]   Politika: >=10 karakter, tamamen rakam değil, ve şu değerlerden\n"
            "[config]   biri değil: " + ", ".join(sorted(_WEAK_ADMIN_PASSWORDS)) + ".\n"
            "[config] ÇÖZÜM 1 (önerilen, güvenli): Coolify panelden\n"
            "[config]   SCALPER_ADMIN_PASSWORD ortam değişkenini güçlendirin.\n"
            "[config]   Değeri hiçbir yere yazmayın/loglamayın.\n"
            "[config] ÇÖZÜM 2 (geçici, güvenlik AZALIR): docker-compose.yaml'da\n"
            "[config]   SCALPER_ENV: ${SCALPER_ENV:-development} kullanın; kod\n"
            "[config]   değişikliği gerekmez. Böylece politika üretimde kapanır."
        )
    print("[config] UYARI: " + message + " (geliştirme modunda yalnızca uyarı; "
          "üretimde başlatma engellenir)")


PRODUCTION_MODE = os.getenv(
    "SCALPER_ENV", os.getenv("ENVIRONMENT", "development")
).strip().lower() in {"production", "prod"}
_admin_password = _env_secret("SCALPER_ADMIN_PASSWORD", "")
enforce_admin_password_policy(_admin_password, production=PRODUCTION_MODE)
