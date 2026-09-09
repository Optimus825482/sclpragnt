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

class Config:
    STRATEGY_REVISION = os.getenv("STRATEGY_REVISION", "filters-2026-08-06-adx18-keltner-retest-chop45")
    # Startup and top-gainer hydration use only the timeframes that active
    # paper paths consume. Other chart/research timeframes are hydrated on
    # demand and do not need to block process startup.
    PRIORITY_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")

    SYMBOLS = [
    "BTCTRY", "ETHTRY", "SOLTRY",   # Ana Hacimliler (Balinalar)
    "XRPTRY", "ADATRY", "AVAXTRY",  # Orta Hacimliler (Trend Takipçileri)
    "LINKTRY", "NEARTRY", "APTTRY", # Güçlü Projeler (Kırılım avcıları)
    "ARBTRY", "OPTRY", "SUITRY",    # Yeni Nesil L2'ler (Hızlı Hareket)
    "DOGETRY", "LTCTRY","BNBTRY",         # Memecoinler (Hacim Patlaması Kralları)
    "INJTRY", "WLDTRY", "DOTTRY"               # Yüksek Volatilite (Agresif Skalp)
]
    MIN_NOTIONAL = 10.0
    INITIAL_BALANCE_TRY = 10000.0
    # Spot paper işlemlerde varsayılan işlem tutarı (TRY).
    # Varsayılan paper işlem büyüklüğü (TRY). Arayüzden ayrıca değiştirilebilir.
    DEFAULT_ORDER_USDT = float(os.getenv("DEFAULT_ORDER_USDT", "1000.0"))
    MIN_PARTIAL_ORDER_TRY = 100.0
    # Normal yüzde tutarı minimumun altına düştüğünde boş bakiyeyi eritmek
    # için kullanılacak kademeli paper işlem tutarı.
    FALLBACK_ORDER_TRY = float(os.getenv("FALLBACK_ORDER_TRY", "250.0"))
    # 0 means unlimited; cash, liquidity and per-symbol pyramid limits still apply.
    MAX_OPEN_POSITIONS = 0
    MAX_TICKER_AGE_SEC = 15
    MAX_POSITION_HOLD_SEC = 4 * 60 * 60
    EARLY_FAILURE_SEC = int(os.getenv("EARLY_FAILURE_SEC", str(45 * 60)))
    EARLY_FAILURE_MIN_PROGRESS_PCT = float(os.getenv("EARLY_FAILURE_MIN_PROGRESS_PCT", "0.0015"))
    STALE_POSITION_SEC = int(os.getenv("STALE_POSITION_SEC", str(90 * 60)))
    STALE_POSITION_MIN_PROGRESS_PCT = float(os.getenv("STALE_POSITION_MIN_PROGRESS_PCT", "0.004"))
    STALE_POSITION_EXIT_BELOW_COST = os.getenv("STALE_POSITION_EXIT_BELOW_COST", "false").lower() == "true"
    EXIT_ON_OPPOSITE_SIGNAL = os.getenv("EXIT_ON_OPPOSITE_SIGNAL", "false").lower() == "true"
    TIMEOUT_REENTRY_BLOCK_SEC = 24 * 60 * 60
    HARD_STOP_REENTRY_BLOCK_SEC = 2 * 60 * 60
    # Short-horizon velocity paper entries get a shorter, still non-zero
    # hard-stop lock. Classic strategy protection remains unchanged.
    VELOCITY_HARD_STOP_REENTRY_BLOCK_SEC = max(
        60, int(os.getenv("VELOCITY_HARD_STOP_REENTRY_BLOCK_SEC", str(15 * 60)))
    )
    MAX_POSITION_LAYERS = 1
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
    # Kâr kilidi tetiklenmeden ÖNCE güvenlik stopu: fiyat +%0.5'i hiç görmeden
    # bu kadar düşerse kapat. Stopsuz açılış, fiyat hiç yükselmezse sınırsız
    # zarar demek (canlıda -%7.5 görüldü); -%3 stop EV'yi korur, max kaybı
    # sınırlar. Kâr kilidi devreye girince bu stop zaten anlamsızlaşır (kâr
    # kilidi stop'u daha yukarıdadır).
    VELOCITY_EMERGENCY_STOP_PCT = float(os.getenv("VELOCITY_EMERGENCY_STOP_PCT", "3.0"))
    # Otonom açılış için minimum velocity skoru. Journal analizi (2026-08-31):
    # skor <10 geçen adaylarda dokunuş %16.7 (n=12), 10-30 arası %47.6 (n=21),
    # 30+ %50.0 (n=14) — 10 altı adaylarda açılış yapmak EV'yi düşürüyor.
    # 0 = filtre kapalı. Eşik ham velocity_score'a bakar; kalite çarpanı uygulanmaz.
    VELOCITY_AUTO_MIN_SCORE = float(os.getenv("VELOCITY_AUTO_MIN_SCORE", "10"))
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
    MONITORING_MIN_SCORE_DEFAULT = float(os.getenv("MONITORING_MIN_SCORE_DEFAULT", "70"))
    # velocity_score 0-100 bandında üretilir (formül: atr_ratio × bb_ratio × yapı × momentum).
    # Tipik orta-kuvvetli sinyal 20-60 arasıdır. Varsayılan eşik 70: yalnızca yüksek
    # güvenli adaylar bildirilir; admin PUT /api/monitoring/settings ile düşürebilir.
    MONITORING_SCORE_NORM_CAP = float(os.getenv("MONITORING_SCORE_NORM_CAP", "2000"))  # 2026-09-07: saturation kaldirma sonrasi tipik skor 50-2000
    # Hızlı şerit: bu skor üstü adaylar debounce beklemeden anında bildirilir
    # (yüksek skor hızlı pump'larda gelir; bekleme fırsatı kaçırır).
    MONITORING_FAST_LANE_SCORE = float(os.getenv("MONITORING_FAST_LANE_SCORE", "70"))
    # Debounce: fast-lane altı aday N ardışık taramada aday kalırsa bildirilir.
    MONITORING_DEBOUNCE_SCANS = max(1, int(os.getenv("MONITORING_DEBOUNCE_SCANS", "2")))
    # Bu andan itibaren monitoring bildirim skoru panel (0-100) ölçeğinde yazılır
    # (06d6a4d, 2026-09-04 18:11 +03). Öncesindeki kayıtlar ham velocity_score'tur;
    # rapor filtresi eski kayıtları tek kez normalize eder. Çift normalize uygulamak
    # eşiği fiilen 2.5× gevşetiyordu (panel 50 -> etkin 20), 2026-09-04 teşhis.
    MONITORING_SCORE_NORM_SINCE = float(os.getenv("MONITORING_SCORE_NORM_SINCE", "1788534693"))
    # Skor-bantlı dinamik hedef: "skor_esigi:hedef_pct" çiftleri virgülle; yüksekten
    # düşüğe ilk eşleşen bant hedefi belirler (0 dönerse profil baz hedefi kalır).
    MONITORING_TARGET_SCORE_TIERS = os.getenv("MONITORING_TARGET_SCORE_TIERS", "90:4.0,70:2.5,50:2.0")
    # Dinamik hedef sınırları ve adaptif esnetme: sembolün journal'dan öğrenilmiş
    # (get_symbol_target_state) hedefi daha yüksekse hedef buraya kadar yükseltilir.
    MONITORING_TARGET_ADAPTIVE = os.getenv("MONITORING_TARGET_ADAPTIVE", "true").lower() == "true"
    MONITORING_TARGET_PCT_MIN = float(os.getenv("MONITORING_TARGET_PCT_MIN", "1.5"))
    MONITORING_TARGET_PCT_MAX = float(os.getenv("MONITORING_TARGET_PCT_MAX", "6.0"))
    # Mikro-yapı sıralama çarpanları (kapı değil, yalnızca aday sıralaması).
    # 2026-09-05 journal analizi (n≈52k evaluated): whale dağıtım/mixed sinyalli
    # GEÇEN adayların dokunuş oranı (%21.9/%20.7) accumulation'dan (%20.7) düşük
    # DEĞİL; no_whale en düşük (%14.8). Bu yüzden dağıtım cezası kaldırıldı —
    # whale aktivitesi OLAN semboller nötr/bonus, hiç whale olmayan hafif ceza alır.
    MONITORING_MICRO_WHALE_MULT = float(os.getenv("MONITORING_MICRO_WHALE_MULT", "1.05"))
    MONITORING_MICRO_NO_WHALE_MULT = float(os.getenv("MONITORING_MICRO_NO_WHALE_MULT", "0.9"))
    # CVD işareti dokunuşu anlamlı ayırmıyor (negatif %14.4 vs pozitif %15.0) → nötr.
    MONITORING_MICRO_CVD_POSITIVE_MULT = float(os.getenv("MONITORING_MICRO_CVD_POSITIVE_MULT", "1.0"))
    # Mikro-yapı giriş filtreleri (2026-08-31, microflow verisiyle):
    # 1) Whale dağıtım filtresi: son whale'ler dağıtım ağırlıklıysa (fiyat etkisi
    #    analizi) girişi engelle — "sahte kırılım" elemesi. Varsayılan OFF:
    #    canlı istatistik (kaç açılışın dağıtım sinyaliyle engellendiği) toplanmadan
    #    giriş kalitesini bozabilecek bir filtreyi zorunlu kılma.
    VELOCITY_WHALE_DISTRIBUTION_FILTER = os.getenv("VELOCITY_WHALE_DISTRIBUTION_FILTER", "false").lower() == "true"
    # 2) Agresif akış onayı: giriş yönüne (long) aykırı net agresif satış akışı
    #    (CVD) varsa girişi reddet. Varsayılan OFF (aynı gerekçe).
    VELOCITY_FLOW_CONFIRMATION_FILTER = os.getenv("VELOCITY_FLOW_CONFIRMATION_FILTER", "false").lower() == "true"
    VELOCITY_PROFIT_LOCK_PCT = 0.01  # +%0.5'te kilitlenen net kâr (girişin %0.01 üstü + komisyon)
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
    ORDER_PCT = float(os.getenv("ORDER_PCT", "0.10"))
    PYRAMIDING_LAYERS = max(1, int(os.getenv("PYRAMIDING_LAYERS", "2")))
    SYMBOL_ORDER_PCT = {}
    SYMBOL_PYRAMIDING_LAYERS = {}
    MIN_24H_QUOTE_VOLUME_TRY = 1_000_000.0
    HIGH_LIQUIDITY_BYPASS_VOLUME_TRY = 3_000_000.0
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
    COMMISSION_PCT = float(os.getenv("COMMISSION_PCT", "0.0015"))
    ESTIMATED_SLIPPAGE_PCT = 0.00025
    MIN_EXPECTED_NET_PNL_TRY = 0.5
    # LLM paper-entry gate: an entry is blocked when the live top-of-book spread
    # exceeds this percent (thin-orderbook protection for low-price TRY pairs).
    LLM_MAX_ENTRY_SPREAD_PCT = float(os.getenv("LLM_MAX_ENTRY_SPREAD_PCT", "1.0"))
    # S6 volatility-based sizing: equal-risk scaling around this ATR% baseline.
    VOLATILITY_SIZING_ENABLED = os.getenv("VOLATILITY_SIZING_ENABLED", "true").lower() == "true"
    VOLATILITY_BASELINE_ATR_PCT = max(0.0005, float(os.getenv("VOLATILITY_BASELINE_ATR_PCT", "0.006")))
    VOLATILITY_SIZING_MIN_SCALE = max(0.25, float(os.getenv("VOLATILITY_SIZING_MIN_SCALE", "0.35")))
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
    AUTO_PAPER_MIN_SCORE_DEFAULT = float(os.getenv("AUTO_PAPER_MIN_SCORE", "50"))
    AUTO_PAPER_BALANCE_PCT_DEFAULT = float(os.getenv("AUTO_PAPER_BALANCE_PCT", "35"))
    AUTO_PAPER_SL_PCT_DEFAULT = float(os.getenv("AUTO_PAPER_SL_PCT", "3.0"))
    AUTO_PAPER_DEFAULT_TARGET_PCT = float(os.getenv("AUTO_PAPER_DEFAULT_TARGET_PCT", "2.0"))
    AUTO_PAPER_MIN_ORDER_TRY = float(os.getenv("AUTO_PAPER_MIN_ORDER_TRY", "50.0"))
    AUTO_PAPER_BREAKEVEN_TRIGGER_PCT = float(os.getenv("AUTO_PAPER_BREAKEVEN_TRIGGER_PCT", "1.5"))
    # Trailing stop modülü (kâr takibi): pozisyon trailing_trigger_pct kadar
    # kara geçince aktifleşir ve fiyatı trailing_gap_pct geriden takip eder.
    # Varsayılan AÇIK; trailing_enabled=false ile kapatılabilir.
    AUTO_PAPER_TRAILING_ENABLED = os.getenv("AUTO_PAPER_TRAILING_ENABLED", "true").lower() == "true"
    AUTO_PAPER_TRAILING_TRIGGER_PCT = float(os.getenv("AUTO_PAPER_TRAILING_TRIGGER_PCT", "2.0"))
    AUTO_PAPER_TRAILING_GAP_PCT = float(os.getenv("AUTO_PAPER_TRAILING_GAP_PCT", "0.8"))
    # Trailing/breakeven kapanışı sonrası aynı bildirimle yeniden açılış
    # (fiyat bildirim fiyatının üzerinde + ufuk süresi dolmadı + yükselme
    # eğilimi varsa). Varsayılan AÇIK; false ile kapatılabilir.
    AUTO_PAPER_REOPEN_AFTER_PROTECT_CLOSE = os.getenv("AUTO_PAPER_REOPEN_AFTER_PROTECT_CLOSE", "true").lower() == "true"
    # Otonom paper için global maksimum açık pozisyon sayısı (0 = sınırsız).
    # Farklı sembollerden gelen bildirim zinciri cüzdanı tüketmesin.
    AUTO_PAPER_MAX_OPEN_POSITIONS = max(0, int(os.getenv("AUTO_PAPER_MAX_OPEN_POSITIONS", "0")))

    # MACD MONITOR / SIRÇRAMA ADAYI ayarları (DB üzerinden değiştirilebilir;
    # burada yalnızca varsayılanlar). Eşik ve alarm/push anahtarları.
    MACD_JUMP_MIN_SCORE_DEFAULT = max(0, min(100, int(os.getenv("MACD_JUMP_MIN_SCORE", "60"))))
    MACD_JUMP_ALERTS_ENABLED = os.getenv("MACD_JUMP_ALERTS_ENABLED", "true").lower() == "true"
    MACD_JUMP_PUSH_ENABLED = os.getenv("MACD_JUMP_PUSH_ENABLED", "true").lower() == "true"
    # Erken sinyal alarmları (YAKLAŞIYOR → KIRILIM aşamalı öncü sistem) —
    # varsayılan AÇIK: M5 zirveye yaklaşma, M1 öncü kırılım, MACD dip dönüşü.
    MACD_EARLY_ALERTS_ENABLED = os.getenv("MACD_EARLY_ALERTS_ENABLED", "true").lower() == "true"

    @classmethod
    def min_net_exit_pct(cls, order_value: float | None = None) -> float:
        """Gross move needed to cover round-trip costs plus minimum net PnL."""
        value = float(order_value or cls.DEFAULT_ORDER_USDT)
        if value <= 0:
            return cls.COMMISSION_PCT * 2 + cls.ESTIMATED_SLIPPAGE_PCT * 2
        return (cls.COMMISSION_PCT * 2
                + cls.ESTIMATED_SLIPPAGE_PCT * 2
                + cls.MIN_EXPECTED_NET_PNL_TRY / value)

config = Config()

# Güvenlik: placeholder session secret ile başlatmayı reddet. Placeholder
# değer herkese açıktır; onunla imzalanan oturum çerezleri sahte üretilebilir.
_PLACEHOLDER_SECRETS = {
    "replace-with-at-least-32-random-bytes",
    "changeme",
    "change-me",
}
_session_secret = os.getenv("SCALPER_SESSION_SECRET", "").strip()
if _session_secret and _session_secret in _PLACEHOLDER_SECRETS:
    raise RuntimeError(
        "SCALPER_SESSION_SECRET placeholder değeriyle başlatılamaz; "
        "en az 32 rastgele bayt üretip .env dosyasına yazın."
    )
if _session_secret and len(_session_secret) < 32:
    print("[config] UYARI: SCALPER_SESSION_SECRET 32 karakterden kısa; güçlü bir secret üretin.")
_admin_password = os.getenv("SCALPER_ADMIN_PASSWORD", "")
if _admin_password and (
    len(_admin_password) < 10
    or _admin_password.isdigit()
    or _admin_password.lower() in {"admin", "password", "12345678", "1234567890"}
):
    print("[config] UYARI: SCALPER_ADMIN_PASSWORD zayıf görünüyor; rotasyon önerilir.")
