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
    API_KEY = os.getenv("BINANCE_API_KEY", "")
    API_SECRET = os.getenv("BINANCE_API_SECRET", "")
    
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
    STRATEGY_MAX_HOLD_SEC = {
        "KELTNER_BREAKOUT": int(os.getenv("KELTNER_MAX_HOLD_SEC", str(60 * 60))),
        "MOMENTUM": int(os.getenv("MOMENTUM_MAX_HOLD_SEC", str(90 * 60))),
        "EMA_VWAP_PULLBACK": int(os.getenv("EMA_VWAP_MAX_HOLD_SEC", str(90 * 60))),
        "CHOP_TREND_FILTER": int(os.getenv("CHOP_MAX_HOLD_SEC", str(120 * 60))),
    }
    TIMEOUT_REENTRY_BLOCK_SEC = 24 * 60 * 60
    HARD_STOP_REENTRY_BLOCK_SEC = 2 * 60 * 60
    MAX_POSITION_LAYERS = 1
    ACTIVE_STRATEGY = os.getenv("ACTIVE_STRATEGY", "BB_MFI_MEAN_REVERSION")
    ACTIVE_STRATEGY_TIMEFRAME = os.getenv("ACTIVE_STRATEGY_TIMEFRAME", "5m")
    # Yeni giriş/piramitleme sinyalleri tüm aktif sembollerde 5 dakikada bir
    # değerlendirilir; açık pozisyonların stop/TP yönetimi ayrı hızlı döngüdedir.
    STRATEGY_ENTRY_SCAN_INTERVAL_SEC = max(60, int(os.getenv("STRATEGY_ENTRY_SCAN_INTERVAL_SEC", "300")))
    # Research-only monitor for the user-defined 1m SMA(7/25/99) cascade.
    # It records observations only and is intentionally not an entry strategy.
    SMA_CASCADE_SHADOW_ENABLED = os.getenv("SMA_CASCADE_SHADOW_ENABLED", "true").lower() == "true"
    SMA_CASCADE_MAX_SEQUENCE_MINUTES = max(1, int(os.getenv("SMA_CASCADE_MAX_SEQUENCE_MINUTES", "10")))
    SMA_CASCADE_BREAKOUT_WINDOW_MINUTES = max(1, int(os.getenv("SMA_CASCADE_BREAKOUT_WINDOW_MINUTES", "30")))
    SMA_CASCADE_OUTCOME_WINDOW_MINUTES = max(1, int(os.getenv("SMA_CASCADE_OUTCOME_WINDOW_MINUTES", "30")))
    # Source-aligned M3 Fisher / M5 Kernel observer.  It records candidates
    # for active symbols on closed M1 bars and deliberately cannot trade.
    # User-authorized forward paper strategy. It shares the virtual wallet and
    # portfolio history, while retaining only the supplied Fisher/Kernel exit.
    # Fisher stratejisi sistemden kaldırıldı; eski açık pozisyonlar için
    # katastrofik düşüş stop'u korumaya devam eder.
    FISHER_EMERGENCY_STOP_PCT = max(0.5, float(os.getenv("FISHER_EMERGENCY_STOP_PCT", "3.0")))
    # Saat bazlı replay'de bu bantlar ortalama -%1.4..-%2.8 PnL üretti
    # (likidite ölü / gürültü yüksek). Varsayılan: 03-06 ve 18-20 kapalı.
    # Virgülle ayrılmış saat listesi; boş = filtre yok.
    FISHER_ENTRY_BLOCKED_HOURS = [int(h) for h in os.getenv("FISHER_ENTRY_BLOCKED_HOURS", "3,4,5,18,19").split(",") if h.strip().isdigit()]
    # LLM market commentary is a journaled, paper-only forecast.  These
    # horizons never authorize an order or mutate strategy parameters.
    LLM_FORECAST_HORIZONS_MINUTES = (5, 15, 60, 240)
    LLM_FORECAST_EVALUATION_INTERVAL_SEC = max(30, int(os.getenv("LLM_FORECAST_EVALUATION_INTERVAL_SEC", "60")))
    LLM_FORECAST_MIN_MOVE_PCT = max(0.0001, float(os.getenv("LLM_FORECAST_MIN_MOVE_PCT", "0.0015")))
    LLM_FORECAST_LESSON_MIN_SAMPLES = max(8, int(os.getenv("LLM_FORECAST_LESSON_MIN_SAMPLES", "12")))
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
    # Otonom hız avcısı: 15 dk'da bir tarama, en iyi adaya (GEÇTİ veya İZLEME)
    # serbest TL'nin %50'si ile pozisyon. Çıkış merdiveni analyzer'da:
    # +%1 kâr → stop maliyet+%0,01'e çekilir (kâr garantisi), sonrasında
    # %0,5 dinamik trailing, sert stop %2.5, plan TP %2.
    VELOCITY_AUTO_ENABLED = os.getenv("VELOCITY_AUTO_ENABLED", "false").lower() == "true"
    VELOCITY_AUTO_INTERVAL_SEC = max(300, int(os.getenv("VELOCITY_AUTO_INTERVAL_SEC", "300")))
    VELOCITY_AUTO_BALANCE_PCT = 50.0
    VELOCITY_AUTO_SL_PCT = float(os.getenv("VELOCITY_AUTO_SL_PCT", "2.5"))  # Hız Avcısı sert stop %2.5
    VELOCITY_POOL_SIZE = max(5, min(50, int(os.getenv("VELOCITY_POOL_SIZE", "30"))))  # Hız Avcısı aday havuzu (top gainer)
    VELOCITY_TRAIL_TRIGGER_PCT = 1.0  # Trailing/kâr kilidi bu kâr yüzdesinde devreye girer
    VELOCITY_TRAIL_GAP_PCT = 0.5  # Dinamik trailing: stop = tepe - tepe*%0.5
    VELOCITY_PROFIT_LOCK_PCT = 0.01  # +%1'de kilitlenen net kâr (girişin %0.01 üstü + komisyon)
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
    # The live BB-MFI contract defaults to the supplied Flawless Victory v3.
    # Earlier profiles remain selectable only for reproducible comparisons.
    BB_MFI_PINE_VERSION = os.getenv("BB_MFI_PINE_VERSION", "v3").strip().lower()
    BB_MFI_BB_PERIOD = max(5, int(os.getenv("BB_MFI_BB_PERIOD", "21")))
    BB_MFI_BB_STD_DEV = max(0.1, float(os.getenv("BB_MFI_BB_STD_DEV", "2.0")))
    BB_MFI_MFI_PERIOD = max(2, int(os.getenv("BB_MFI_MFI_PERIOD", "16")))
    BB_MFI_RSI_PERIOD = max(2, int(os.getenv("BB_MFI_RSI_PERIOD", "13")))
    BB_MFI_V1_RSI_LOWER_LEVEL = float(os.getenv("BB_MFI_V1_RSI_LOWER_LEVEL", "30"))
    BB_MFI_V1_RSI_UPPER_LEVEL = float(os.getenv("BB_MFI_V1_RSI_UPPER_LEVEL", "70"))
    BB_MFI_V2_RSI_LOWER_LEVEL = float(os.getenv("BB_MFI_V2_RSI_LOWER_LEVEL", "42"))
    BB_MFI_V2_RSI_UPPER_LEVEL = float(os.getenv("BB_MFI_V2_RSI_UPPER_LEVEL", "76"))
    BB_MFI_ENTRY_MFI_MAX = float(os.getenv("BB_MFI_ENTRY_MFI_MAX", "59")) # MFILowerLevel3
    BB_MFI_EXIT_RSI_MIN = float(os.getenv("BB_MFI_EXIT_RSI_MIN", "69")) # RSIUpperLevel3
    BB_MFI_EXIT_MFI_MIN = float(os.getenv("BB_MFI_EXIT_MFI_MIN", "69")) # MFIUpperLevel3
    # Paper candidate: ignore a single noisy exit signal and require this many
    # consecutive completed M5 SELL signals before closing a BB-MFI position.
    BB_MFI_SELL_SIGNAL_CONFIRM_BARS = min(5, max(1, int(os.getenv("BB_MFI_SELL_SIGNAL_CONFIRM_BARS", "2"))))
    BB_MFI_ENTRY_VOLUME_RATIO_MIN = float(os.getenv("BB_MFI_ENTRY_VOLUME_RATIO_MIN", "0.0"))
    # Paper replay candidate: require the completed BB/MFI signal candle to
    # recover from its low before entering. The tested threshold remains 55%;
    # it can still be disabled or tuned from Settings for further paper OOS.
    BB_MFI_DIP_CONFIRMATION_ENABLED = os.getenv("BB_MFI_DIP_CONFIRMATION_ENABLED", "true").lower() == "true"
    BB_MFI_DIP_MIN_CLOSE_POSITION = float(os.getenv("BB_MFI_DIP_MIN_CLOSE_POSITION", "0.55"))
    BB_MFI_ENTRY_MFI_REVERSAL_ENABLED = os.getenv("BB_MFI_ENTRY_MFI_REVERSAL_ENABLED", "false").lower() == "true"
    BB_MFI_ENTRY_MFI_REVERSAL_MIN_DELTA = float(os.getenv("BB_MFI_ENTRY_MFI_REVERSAL_MIN_DELTA", "0.0"))
    BB_MFI_ENTRY_MFI_SLOWDOWN_MAX_DROP = float(os.getenv("BB_MFI_ENTRY_MFI_SLOWDOWN_MAX_DROP", "-1"))
    # Do not buy a BB/MFI dip while a fast, directional selloff is still in force.
    BB_MFI_BEAR_PRESSURE_FILTER_ENABLED = os.getenv("BB_MFI_BEAR_PRESSURE_FILTER_ENABLED", "true").lower() == "true"
    BB_MFI_BEAR_PRESSURE_MIN_ADX = float(os.getenv("BB_MFI_BEAR_PRESSURE_MIN_ADX", "50"))
    BB_MFI_BEAR_PRESSURE_MIN_DI_GAP = float(os.getenv("BB_MFI_BEAR_PRESSURE_MIN_DI_GAP", "25"))
    BB_MFI_BEAR_PRESSURE_MIN_RETURN_1H_PCT = float(os.getenv("BB_MFI_BEAR_PRESSURE_MIN_RETURN_1H_PCT", "0.50"))
    BB_MFI_BEAR_PRESSURE_MIN_RETURN_15M_PCT = float(os.getenv("BB_MFI_BEAR_PRESSURE_MIN_RETURN_15M_PCT", "0.50"))
    # A usable technical snapshot is mandatory for BB/MFI paper entries. In a
    # bearish EMA stack, require a confirmed intrabar recovery and MFI reversal
    # before buying a dip; bullish and mixed stacks retain the base setup.
    BB_MFI_REQUIRE_DATA_READY = os.getenv("BB_MFI_REQUIRE_DATA_READY", "true").lower() == "true"
    BB_MFI_BEARISH_REQUIRE_REVERSAL_CONFIRMATION = os.getenv("BB_MFI_BEARISH_REQUIRE_REVERSAL_CONFIRMATION", "true").lower() == "true"
    BB_MFI_BEARISH_MIN_CLOSE_POSITION = float(os.getenv("BB_MFI_BEARISH_MIN_CLOSE_POSITION", "0.60"))
    BB_MFI_BEARISH_MIN_MFI_REVERSAL_DELTA = float(os.getenv("BB_MFI_BEARISH_MIN_MFI_REVERSAL_DELTA", "1.0"))
    # Pyramid only into a net winner. A third layer is allowed only when each
    # of the first two independently remains net profitable.
    BB_MFI_PYRAMID_REQUIRE_NET_PROFIT = os.getenv("BB_MFI_PYRAMID_REQUIRE_NET_PROFIT", "true").lower() == "true"
    BB_MFI_PYRAMID_PROFIT_EXTENSION_LAYERS = max(0, int(os.getenv("BB_MFI_PYRAMID_PROFIT_EXTENSION_LAYERS", "1")))
    SYMBOL_ORDER_PCT = {}
    SYMBOL_PYRAMIDING_LAYERS = {}
    BB_MFI_STOP_LOSS_PCT = float(os.getenv("BB_MFI_STOP_LOSS_PCT", "0.08882"))
    BB_MFI_TAKE_PROFIT_PCT = float(os.getenv("BB_MFI_TAKE_PROFIT_PCT", "0.02317"))
    MIN_24H_QUOTE_VOLUME_TRY = 1_000_000.0
    HIGH_LIQUIDITY_BYPASS_VOLUME_TRY = 3_000_000.0
    MIN_VOLUME_RATIO = 0.3
    MAX_SPREAD_PCT = 0.5  # geniş spread toleransı: %0.5 (düşük fiyatlı coinler için)
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
    SYMBOL_ACTIVITY_MAX_SPREAD_PCT = 0.5
    SYMBOL_ACTIVITY_SPREAD_FILTER_ENABLED = os.getenv("SYMBOL_ACTIVITY_SPREAD_FILTER_ENABLED", "false").lower() == "true"
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
    # Pump Monitor is a separate, paper-only continuation strategy.  It never
    # changes the active BB-MFI strategy and is capped independently.
    PUMP_MONITOR_ENABLED = os.getenv("PUMP_MONITOR_ENABLED", "true").lower() == "true"
    PUMP_MONITOR_AUTO_TRADE = os.getenv("PUMP_MONITOR_AUTO_TRADE", "true").lower() == "true"
    PUMP_MONITOR_MAX_OPEN_POSITIONS = max(1, int(os.getenv("PUMP_MONITOR_MAX_OPEN_POSITIONS", "3")))
    PUMP_MONITOR_MIN_SCORE = max(3, min(4, int(os.getenv("PUMP_MONITOR_MIN_SCORE", "3"))))
    PUMP_MONITOR_REQUIRE_M15_BULLISH = os.getenv("PUMP_MONITOR_REQUIRE_M15_BULLISH", "true").lower() == "true"
    PUMP_MONITOR_HIGH_CONFIDENCE_VOLUME_RATIO = max(0.0, float(os.getenv("PUMP_MONITOR_HIGH_CONFIDENCE_VOLUME_RATIO", "1.0")))
    # 2026-08-25 trade-history analysis (292 trades, -1680 TRY net):
    # volume_ratio > 2.0 entries alone lost -1029 TRY (chasing an already-
    # detonated pump); 56 stops had seen >= +0.5% MFE first (-1536 TRY); and
    # 48% of stops never saw +0.3% at all (failed pump confirmations). These
    # knobs are derived from that dataset and stay paper-only.
    PUMP_MONITOR_MAX_ENTRY_VOLUME_RATIO = max(0.0, float(os.getenv("PUMP_MONITOR_MAX_ENTRY_VOLUME_RATIO", "2.0")))
    PUMP_MONITOR_BREAK_EVEN_ENABLED = os.getenv("PUMP_MONITOR_BREAK_EVEN_ENABLED", "true").lower() == "true"
    # 0.3% beat 0.5% in the 48h real-kline replay (work/pump_replay_engine.py):
    # -1353 vs -1690 TRY with VR<=2.0. Keep the tighter trigger.
    PUMP_MONITOR_BREAK_EVEN_TRIGGER_PCT = max(0.05, float(os.getenv("PUMP_MONITOR_BREAK_EVEN_TRIGGER_PCT", "0.3"))) / 100.0
    # Fast-fail did NOT earn its keep in the 48h replay (early exits cut
    # trades that later hit ATR trailing). Disabled by default; enable via
    # env only after a longer-window replay supports it.
    PUMP_MONITOR_FAST_FAIL_ENABLED = os.getenv("PUMP_MONITOR_FAST_FAIL_ENABLED", "false").lower() == "true"
    PUMP_MONITOR_FAST_FAIL_SEC = max(60, int(os.getenv("PUMP_MONITOR_FAST_FAIL_SEC", "900")))
    PUMP_MONITOR_FAST_FAIL_MIN_PROGRESS_PCT = max(0.05, float(os.getenv("PUMP_MONITOR_FAST_FAIL_MIN_PROGRESS_PCT", "0.3"))) / 100.0
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
    TAKE_PROFIT_PCT = 0.02
    # Time-decay spot take-profit: start ambitious, then accept the first
    # cost-covered exit as the position ages.
    SPOT_PROFIT_TARGET_PCT = 0.01
    TIME_DECAY_TP_1_PCT = 0.012
    TIME_DECAY_TP_2_PCT = 0.0075
    TIME_DECAY_TP_3_PCT = 0.005
    TIME_DECAY_TP_STAGE_2_SEC = 20 * 60
    TIME_DECAY_TP_STAGE_3_SEC = 40 * 60
    TIME_DECAY_BREAKEVEN_SEC = 60 * 60
    # Kâr koruma: hedefe ulaşmadan önce yeterli ilerleme oluştuğunda
    # maksimum fiyatın gerisinden takip eden stop devreye girer.
    TRAILING_STOP_ENABLED = os.getenv("TRAILING_STOP_ENABLED", "true").lower() == "true"
    TRAILING_ACTIVATION_PCT = float(os.getenv("TRAILING_ACTIVATION_PCT", "0.0075"))
    TRAILING_STOP_PCT = float(os.getenv("TRAILING_STOP_PCT", "0.005"))

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
    BACKTEST_ASSUMED_SPREAD_PCT = float(os.getenv("BACKTEST_ASSUMED_SPREAD_PCT", "0.001"))
    MIN_EXPECTED_NET_PNL_TRY = 0.5
    # Target distance must be at least this multiple of recent ATR noise for
    # an entry to be worth taking (S1 cost-aware quality gates).
    MIN_TARGET_ATR_CAPACITY_RATIO = max(0.1, float(os.getenv("MIN_TARGET_ATR_CAPACITY_RATIO", "1.0")))
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

    @classmethod
    def min_net_exit_pct(cls, order_value: float | None = None) -> float:
        """Gross move needed to cover round-trip costs plus minimum net PnL."""
        value = float(order_value or cls.DEFAULT_ORDER_USDT)
        if value <= 0:
            return cls.COMMISSION_PCT * 2 + cls.ESTIMATED_SLIPPAGE_PCT * 2
        return (cls.COMMISSION_PCT * 2
                + cls.ESTIMATED_SLIPPAGE_PCT * 2
                + cls.MIN_EXPECTED_NET_PNL_TRY / value)

    # Live giriş evreni: BB-MFI stratejisi ve açıkça etkinleştirilen LLM paper akışı.
    # Gainer Radar yalnızca tarama/sıralama yüzeyidir ve pozisyon açmaz.
    UT_ENABLED = False
    UT_SYMBOLS = os.getenv("UT_SYMBOLS", "").split(",") if os.getenv("UT_SYMBOLS") else SYMBOLS
    UT_KEY_VALUE = 1.0
    UT_ATR_PERIOD = 11
    UT_HEIKIN_ASHI = True
    UT_TIMEFRAME = os.getenv("UT_TIMEFRAME", "5m")

    # Ek stratejiler (ayrı ayrı aç/kapat)
    BB_SQUEEZE_ENABLED = False
    EMA_PULLBACK_ENABLED = False
    VWAP_MACD_ENABLED = False
    CMO_CRSI_ENABLED = False
    OVERSOLD_TREND_REENTRY_ENABLED = False
    ADAPTIVE_VOLATILITY_TREND_ENABLED = False
    REGIME_GATE_LOW_TURNOVER_ENABLED = False
    OVERSOLD_TREND_REENTRY_RSI_MAX = float(os.getenv("OVERSOLD_TREND_REENTRY_RSI_MAX", "40"))
    EMA_VWAP_ENABLED = False
    BREAKOUT_ENABLED = False
    ORDERFLOW_ENABLED = False
    MOMENTUM_ENABLED = False
    MOMENTUM_COST_AWARE_ENABLED = False
    MEAN_REVERSION_ENABLED = True
    KELTNER_ENABLED = False
    CHOP_ENABLED = False
    DONCHIAN_ENABLED = False

    # Canlı strateji eşikleri (Ayarlar > Stratejiler üzerinden güncellenebilir)
    ORDERFLOW_MIN_IMBALANCE = 0.10
    MOMENTUM_SHORT_LOOKBACK = 5
    MOMENTUM_LONG_LOOKBACK = 21
    MOMENTUM_MIN_RETURN_PCT = 0.003
    MOMENTUM_MIN_VOLUME_RATIO = 1.0
    MOMENTUM_REQUIRE_MTF_ALIGNMENT = True
    MOMENTUM_MIN_ADX = float(os.getenv("MOMENTUM_MIN_ADX", "18"))
    MOMENTUM_COST_AWARE_MIN_RETURN_PCT = float(os.getenv("MOMENTUM_COST_AWARE_MIN_RETURN_PCT", "0.004"))
    MOMENTUM_COST_AWARE_MIN_VOLUME_RATIO = float(os.getenv("MOMENTUM_COST_AWARE_MIN_VOLUME_RATIO", "1.2"))
    MOMENTUM_COST_AWARE_MIN_ADX = float(os.getenv("MOMENTUM_COST_AWARE_MIN_ADX", "22"))
    # MTF Momentum için volatilite kapasitesi filtresi (ADR).
    ADR_FILTER_ENABLED = True
    ADR_PERIOD = 14
    ADR_MIN_PCT = 0.02
    ADR_MAX_UTILIZATION_PCT = 0.80
    ADR_MIN_REMAINING_PCT = 0.01
    KELTNER_EMA_PERIOD = 20
    KELTNER_ATR_PERIOD = 20
    KELTNER_ATR_MULTIPLIER = 1.8
    KELTNER_VOLUME_MULTIPLIER = 1.5
    KELTNER_REQUIRE_MTF_ALIGNMENT = True
    KELTNER_REQUIRE_RETEST = True
    # VWAP + EMA trend/pullback stratejisi: maliyet sonrası daha seçici giriş.
    EMA_VWAP_MIN_VOLUME_RATIO = float(os.getenv("EMA_VWAP_MIN_VOLUME_RATIO", "1.0"))
    EMA_VWAP_MIN_ADX = float(os.getenv("EMA_VWAP_MIN_ADX", "18"))
    EMA_VWAP_REQUIRE_MTF_ALIGNMENT = True
    CHOP_PERIOD = 14
    CHOP_MAX_VALUE = float(os.getenv("CHOP_MAX_VALUE", "45"))
    CHOP_MIN_RSI = float(os.getenv("CHOP_MIN_RSI", "52"))
    DONCHIAN_LOOKBACK = 20
    DONCHIAN_VOLUME_MULTIPLIER = 1.15

    # Her stratejinin kendi timeframe'i
    BB_SQUEEZE_TIMEFRAME = os.getenv("BB_SQUEEZE_TIMEFRAME", "5m")
    EMA_PULLBACK_TIMEFRAME = os.getenv("EMA_PULLBACK_TIMEFRAME", "15m")
    VWAP_MACD_TIMEFRAME = os.getenv("VWAP_MACD_TIMEFRAME", "5m")
    CMO_CRSI_TIMEFRAME = os.getenv("CMO_CRSI_TIMEFRAME", "5m")
    OVERSOLD_TREND_REENTRY_TIMEFRAME = os.getenv("OVERSOLD_TREND_REENTRY_TIMEFRAME", "5m")
    ADAPTIVE_VOLATILITY_TREND_TIMEFRAME = os.getenv("ADAPTIVE_VOLATILITY_TREND_TIMEFRAME", "15m")
    ADAPTIVE_VOLATILITY_MIN_ATR_PCT = float(os.getenv("ADAPTIVE_VOLATILITY_MIN_ATR_PCT", "0.0015"))
    ADAPTIVE_VOLATILITY_MAX_ATR_PCT = float(os.getenv("ADAPTIVE_VOLATILITY_MAX_ATR_PCT", "0.012"))
    ADAPTIVE_VOLATILITY_MIN_ADX = float(os.getenv("ADAPTIVE_VOLATILITY_MIN_ADX", "20"))
    REGIME_GATE_LOW_TURNOVER_TIMEFRAME = os.getenv("REGIME_GATE_LOW_TURNOVER_TIMEFRAME", "1h")
    REGIME_GATE_MIN_ADX = float(os.getenv("REGIME_GATE_MIN_ADX", "25"))
    REGIME_GATE_MIN_RETURN_PCT = float(os.getenv("REGIME_GATE_MIN_RETURN_PCT", "0.01"))
    REGIME_GATE_MIN_VOLUME_RATIO = float(os.getenv("REGIME_GATE_MIN_VOLUME_RATIO", "1.1"))
    EMA_VWAP_TIMEFRAME = os.getenv("EMA_VWAP_TIMEFRAME", "5m")
    BREAKOUT_TIMEFRAME = os.getenv("BREAKOUT_TIMEFRAME", "5m")
    ORDERFLOW_TIMEFRAME = os.getenv("ORDERFLOW_TIMEFRAME", "1m")
    MOMENTUM_TIMEFRAME = os.getenv("MOMENTUM_TIMEFRAME", "5m")
    ADR_TIMEFRAME = "1d"
    MEAN_REVERSION_TIMEFRAME = os.getenv("MEAN_REVERSION_TIMEFRAME", "5m")
    KELTNER_TIMEFRAME = os.getenv("KELTNER_TIMEFRAME", "5m")
    CHOP_TIMEFRAME = os.getenv("CHOP_TIMEFRAME", "5m")
    DONCHIAN_TIMEFRAME = os.getenv("DONCHIAN_TIMEFRAME", "5m")

    # BB Squeeze parametreleri
    SQUEEZE_LOOKBACK = 20
    BB_PERIOD = 20
    BB_STD_DEV = 2.0

    # EMA Pullback parametreleri
    EMA_SHORT = 9
    EMA_MID = 21
    EMA_TREND = 50
    RSI_PERIOD = 14

    # VWAP + MACD parametreleri
    VWAP_PERIOD = 20
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9

config = Config()
