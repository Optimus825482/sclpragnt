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

# G-24 (denetim): Aşağıdaki ayarların TAMAMI `class Config` gövdesinde, yani
# IMPORT anında okunur. Birkaç ayar (RETENTION_DAYS, microstructure retention,
# DATABASE_URL, SCALPER_SESSION_SECRET) ise çalışma zamanında okunur → iki
# farklı okuma rejimi vardır. Sonuç: çalışırken `os.environ` değiştirmek
# (test/reload senaryoları) bu sabitlere YANSIMAZ; süreci yeniden başlatmak
# gerekir. Davranışı kanıtlanmış bir dağıtım provası olmadan değiştirmemek için
# refactor yerine burada belgelenmiştir.


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
    # Spot paper işlemlerde varsayılan işlem tutarı (TRY cinsinden; adı tarihsel
    # olarak USDT kalmıştır, Binance TR tarafında bakiye TRY'dir).
    # Varsayılan paper işlem büyüklüğü (TRY). Arayüzden ayrıca değiştirilebilir.
    DEFAULT_ORDER_USDT = float(os.getenv("DEFAULT_ORDER_USDT", "1000.0"))
    # Aynı ayarın doğru adı; yeni kod bunu kullanmalı (eski ad geriye dönük uyum
    # için korunuyor, .env'deki DEFAULT_ORDER_USDT değişkeni hâlâ okunur).
    DEFAULT_ORDER_TRY = DEFAULT_ORDER_USDT
    MIN_PARTIAL_ORDER_TRY = 100.0
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
    VELOCITY_LEADING_MULTIPLIER = float(os.getenv("VELOCITY_LEADING_MULTIPLIER", "1.15"))
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
    # MACD teyidi (radar skorlaması) — MACD MONITOR'un kanıta dayalı çoklu-TF /
    # kapanmış-mum felsefesi radara taşınır. AÇIKKEN (varsayılan) aday skoru
    # kapanmış 1m/5m MACD histogramına göre hafif çarpılır; derin negatif + düşüşteki
    # aday geriye düşürülür (başarı odaklı ayıklama). Kapı değil, sıralama/skora
    # etki eden fitre çarpanıdır — yenilik keskin eşik yapılmaz.
    VELOCITY_MACD_CONFIRMATION_ENABLED = os.getenv("VELOCITY_MACD_CONFIRMATION_ENABLED", "true").lower() == "true"
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
    # ile acar ve `sl_pct` = `AUTO_PAPER_SL_PCT_DEFAULT` (asagida, %3.0) / settings
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
    #   RR_MIN=0.6 + SL=%3.0 → hedef >= %1.8 gerekir.
    # Tipik hedefler (%2.0 → RR 0.667, %3.0 → 1.0) GECER; yalnizca hedefi
    # gidis-donus maliyetine yaklasan band (MONITORING_TARGET_PCT_MIN=%1.5 →
    # RR 0.5) elenir. Tek deger yeterli: 5dk (%2.0) ve 15dk (%3.0) profillerinin
    # ikisi de esigi asar, ufuk bazli ayrim gerekmez.
    MONITORING_RR_MIN = float(os.getenv("MONITORING_RR_MIN", "0.6"))
    # R/R gate SL dayanağı: AUTO_PAPER_SL_PCT_DEFAULT ile AYNI olmalı; ayrışırsa
    # gatelettiğimiz adayla açılan pozisyon farklı risk taşır. Eski varsayılan 3.0
    # → 1.5 (2026-09-17, Erkan kararı: replay geometrisi + canlı 50 işlem verisi).
    MONITORING_RR_SL_PCT = float(os.getenv("MONITORING_RR_SL_PCT", "1.5"))

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

    # Net Kâr Hedefi & Maliyet Güvencesi (Kullanıcı Kuralı 2026-09-19):
    # %2.0 hedeflenen scalping işleminde komisyon + spread maliyetleri (~%1.0)
    # düşüldükten SONRA net %2.0 kâr kalacak şekilde brüt hedef (TP) hesaplanır.
    SCALPING_NET_TARGET_PCT = float(os.getenv("SCALPING_NET_TARGET_PCT", "2.0"))
    DEFAULT_ESTIMATED_SPREAD_PCT = float(os.getenv("DEFAULT_ESTIMATED_SPREAD_PCT", "0.65"))
    MAX_ALLOWABLE_SPREAD_RATIO = float(os.getenv("MAX_ALLOWABLE_SPREAD_RATIO", "0.35"))
    ML_MIN_EXECUTION_PROB = float(os.getenv("ML_MIN_EXECUTION_PROB", "0.35"))
    # Sinyal terfisi (upgrade): yeni sinyal, son bildirim skorundan bu kadar
    # yüksekse cooldown bastırması aşılarak "sinyal güçlendi" push'u izinli olur.
    UNIFIED_UPGRADE_MIN_GAIN = float(os.getenv("UNIFIED_UPGRADE_MIN_GAIN", "10.0"))

    # ---------------------------------------------------------------------
    # MASTER SURGE ENGINE (Ana Yükselme Potansiyeli Algoritması — 2026-09-21)
    # 4 Katmanlı Hibrit Mimari + Dinamik Uyarlanabilir Hedefler (TP1/TP2)
    # ---------------------------------------------------------------------
    MASTER_SURGE_ENABLED = os.getenv("MASTER_SURGE_ENABLED", "true").lower() == "true"
    MASTER_SURGE_MIN_SCORE = float(os.getenv("MASTER_SURGE_MIN_SCORE", "70.0"))
    MASTER_SURGE_REQUIRE_4WAY = os.getenv("MASTER_SURGE_REQUIRE_4WAY", "true").lower() == "true"
    MASTER_SURGE_MAX_SPREAD_PCT = float(os.getenv("MASTER_SURGE_MAX_SPREAD_PCT", "0.45"))
    MASTER_SURGE_MIN_24H_VOLUME_TRY = float(os.getenv("MASTER_SURGE_MIN_24H_VOLUME_TRY", "150000.0"))
    MASTER_SURGE_MIN_DEPTH_TRY = float(os.getenv("MASTER_SURGE_MIN_DEPTH_TRY", "5000.0"))
    MASTER_SURGE_TP1_MIN_PCT = float(os.getenv("MASTER_SURGE_TP1_MIN_PCT", "1.2"))
    MASTER_SURGE_TP1_MAX_PCT = float(os.getenv("MASTER_SURGE_TP1_MAX_PCT", "1.8"))
    MASTER_SURGE_TP2_MIN_PCT = float(os.getenv("MASTER_SURGE_TP2_MIN_PCT", "3.0"))
    MASTER_SURGE_TP2_MAX_PCT = float(os.getenv("MASTER_SURGE_TP2_MAX_PCT", "6.5"))
    MASTER_SURGE_BE_GAP_PCT = float(os.getenv("MASTER_SURGE_BE_GAP_PCT", "0.40"))

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
    LLM_QUICK_LANE_MAX_TOKENS = max(128, int(os.getenv("LLM_QUICK_LANE_MAX_TOKENS", "600")))
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
    # A3 (2026-09-14) ANKRAJI: `auto_paper` bu eşiği `monitoring.normalize_score`
    # PANEL skoruyla karşılaştırır. Eski panel 50 = ham 1000 (lineer, cap 2000);
    # log haritada aynı ham nokta panel 68.2 → DEĞER KORUNARAK yeniden ankrajlandı.
    AUTO_PAPER_MIN_SCORE_DEFAULT = float(os.getenv("AUTO_PAPER_MIN_SCORE", "68.2"))
    AUTO_PAPER_BALANCE_PCT_DEFAULT = float(os.getenv("AUTO_PAPER_BALANCE_PCT", "35"))
    AUTO_PAPER_SL_PCT_DEFAULT = float(os.getenv("AUTO_PAPER_SL_PCT", "1.5"))  # Eski varsayılan 3.0 → 1.5 (2026-09-17, Erkan kararı: replay geometrisi + canlı 50 işlem verisi).
    AUTO_PAPER_DEFAULT_TARGET_PCT = float(os.getenv("AUTO_PAPER_DEFAULT_TARGET_PCT", "1.5"))  # Eski varsayılan 2.0 → 1.5 (2026-09-17, Erkan kararı: radar/velocity bildirimlerinin hedefi MFE tavanına otursun; replay geometrisi + canlı 50 işlem verisi).
    AUTO_PAPER_MIN_ORDER_TRY = float(os.getenv("AUTO_PAPER_MIN_ORDER_TRY", "50.0"))
    AUTO_PAPER_BREAKEVEN_TRIGGER_PCT = float(os.getenv("AUTO_PAPER_BREAKEVEN_TRIGGER_PCT", "1.2"))
    # Trailing stop modülü (kâr takibi): pozisyon trailing_trigger_pct kadar
    # kara geçince aktifleşir ve fiyatı trailing_gap_pct geriden takip eder.
    # Varsayılan AÇIK; trailing_enabled=false ile kapatılabilir.
    AUTO_PAPER_TRAILING_ENABLED = os.getenv("AUTO_PAPER_TRAILING_ENABLED", "true").lower() == "true"
    AUTO_PAPER_TRAILING_TRIGGER_PCT = float(os.getenv("AUTO_PAPER_TRAILING_TRIGGER_PCT", "1.8"))
    # 2026-09-16: varsayılan 0.8 → 0.6. 0.8 HİÇ UYGULANMIYORDU: breakeven
    # ratchet'i (%0.60, aynı değer sabiti) hem daha sıkı hem önce kontrol edildiği
    # için trailing her zaman gölgeleniyordu (471 işlemlik gerçek replay'de
    # `trailing_stop` 0 kez). Etkin değer zaten 0.60'tı; varsayılan artık ekranda
    # yalan söylemiyor. Sıkılaştırmak (ör. 0.3) gerçekten etki eder.
    AUTO_PAPER_TRAILING_GAP_PCT = float(os.getenv("AUTO_PAPER_TRAILING_GAP_PCT", "0.6"))
    # Trailing/breakeven kapanışı sonrası aynı bildirimle yeniden açılış
    # (fiyat bildirim fiyatının üzerinde + ufuk süresi dolmadı + yükselme
    # eğilimi varsa). Varsayılan AÇIK; false ile kapatılabilir.
    AUTO_PAPER_REOPEN_AFTER_PROTECT_CLOSE = os.getenv("AUTO_PAPER_REOPEN_AFTER_PROTECT_CLOSE", "true").lower() == "true"
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
    AUTO_PAPER_TP_PRIMARY_ENABLED = os.getenv("AUTO_PAPER_TP_PRIMARY_ENABLED", "true").lower() == "true"
    AUTO_PAPER_DYNAMIC_BREAKEVEN_ENABLED = os.getenv("AUTO_PAPER_DYNAMIC_BREAKEVEN_ENABLED", "false").lower() == "true"
    AUTO_PAPER_DYNAMIC_TRAILING_ENABLED = os.getenv("AUTO_PAPER_DYNAMIC_TRAILING_ENABLED", "false").lower() == "true"
    AUTO_PAPER_BREAKEVEN_BUFFER_PCT = float(os.getenv("AUTO_PAPER_BREAKEVEN_BUFFER_PCT", "0.02"))
    # Otonom Paper maksimum pozisyon açık kalma süresi (dakika, 2026-09-21 Erkan kararı).
    # 60 dk sonunda kâr/zarar durumuna bakılmadan pozisyon piyasa fiyatından kapatılır (scalp bakiyesini kilitlemez).
    AUTO_PAPER_MAX_HOLD_MINUTES = float(os.getenv("AUTO_PAPER_MAX_HOLD_MINUTES", "60.0"))

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

    @classmethod
    def round_trip_cost(cls) -> float:
        """Gidiş-dönüş maliyet: iki bacak komisyon + iki bacak slippage (KESİR).

        D-06 (2026-09-14) tek kaynak: `min_net_exit_pct` VE velocity gerçekleşen
        çıkış metriği aynı sayıyı kullanır; kopya formül üretilmez.
        -> (0.0015 + 0.00025) * 2 = 0.0035 (%%0.35)
        """
        return cls.COMMISSION_PCT * 2 + cls.ESTIMATED_SLIPPAGE_PCT * 2

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
    message = admin_password_policy_message(password)
    if not message:
        return
    if production:
        raise RuntimeError(
            "[config] " + message + " (SCALPER_ENV=production; başlatma reddedildi)")
    print("[config] UYARI: " + message + " (geliştirme modunda yalnızca uyarı; "
          "üretimde başlatma engellenir)")


PRODUCTION_MODE = os.getenv(
    "SCALPER_ENV", os.getenv("ENVIRONMENT", "development")
).strip().lower() in {"production", "prod"}
_admin_password = os.getenv("SCALPER_ADMIN_PASSWORD", "")
enforce_admin_password_policy(_admin_password, production=PRODUCTION_MODE)
