import os
from dotenv import load_dotenv
load_dotenv()

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
    MAX_OPEN_POSITIONS = 36
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
    ORDER_PCT = float(os.getenv("ORDER_PCT", "0.10"))
    PYRAMIDING_LAYERS = max(1, int(os.getenv("PYRAMIDING_LAYERS", "2")))
    SYMBOL_ORDER_PCT = {}
    SYMBOL_PYRAMIDING_LAYERS = {}
    BB_MFI_STOP_LOSS_PCT = float(os.getenv("BB_MFI_STOP_LOSS_PCT", "0.08882"))
    BB_MFI_TAKE_PROFIT_PCT = float(os.getenv("BB_MFI_TAKE_PROFIT_PCT", "0.02317"))
    MIN_24H_QUOTE_VOLUME_TRY = 1_000_000.0
    HIGH_LIQUIDITY_BYPASS_VOLUME_TRY = 3_000_000.0
    MIN_VOLUME_RATIO = 0.3
    MAX_SPREAD_PCT = 0.30
    MIN_ORDERBOOK_DEPTH_MULTIPLIER = 5.0
    LIQUIDITY_FILTER_ENABLED = True
    # 30 dakikalık sembol aktivitesi: düşük hacim veya tamamen yatay piyasa
    # yeni strateji girişlerinden çıkarılır, açık pozisyonlar korunur.
    SYMBOL_ACTIVITY_REFRESH_SEC = max(300, int(os.getenv("SYMBOL_ACTIVITY_REFRESH_SEC", str(30 * 60))))
    SYMBOL_ACTIVITY_MIN_QUOTE_VOLUME_TRY = float(os.getenv("SYMBOL_ACTIVITY_MIN_QUOTE_VOLUME_TRY", "1000000"))
    SYMBOL_ACTIVITY_MIN_RANGE_30M_PCT = float(os.getenv("SYMBOL_ACTIVITY_MIN_RANGE_30M_PCT", "0.10"))
    PASSIVE_SYMBOLS = set()
    # Radar yalnızca gözlem/ranking yüzeyidir; otomatik pozisyon açmaz.
    GAINER_RADAR_AUTO_TRADE = False
    # LLM yalnızca kullanıcının açık "işlem aç" talebiyle çalışabilir.
    LLM_AUTO_OPEN_ENABLED = False
    GAINER_RADAR_MIN_SCORE = 65
    GAINER_RADAR_INTERVAL_SEC = max(15, int(os.getenv("GAINER_RADAR_INTERVAL_SEC", "60")))
    TOP_GAINERS_LIMIT = max(1, min(70, int(os.getenv("TOP_GAINERS_LIMIT", "70"))))
    TOP_GAINERS_REFRESH_SEC = max(300, int(os.getenv("TOP_GAINERS_REFRESH_SEC", str(6 * 60 * 60))))
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
