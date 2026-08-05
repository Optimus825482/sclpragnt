import os
from dotenv import load_dotenv
load_dotenv()

class Config:
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
    DEFAULT_ORDER_USDT = 500.0
    MAX_OPEN_POSITIONS = 3
    MAX_TICKER_AGE_SEC = 15
    MAX_POSITION_HOLD_SEC = 2 * 60 * 60
    TIMEOUT_REENTRY_BLOCK_SEC = 24 * 60 * 60
    HARD_STOP_REENTRY_BLOCK_SEC = 2 * 60 * 60
    MAX_POSITION_LAYERS = 1
    MIN_24H_QUOTE_VOLUME_TRY = 1_000_000.0
    HIGH_LIQUIDITY_BYPASS_VOLUME_TRY = 3_000_000.0
    MIN_VOLUME_RATIO = 0.3
    MAX_SPREAD_PCT = 0.30
    MIN_ORDERBOOK_DEPTH_MULTIPLIER = 5.0
    LIQUIDITY_FILTER_ENABLED = True
    GAINER_RADAR_AUTO_TRADE = True
    GAINER_RADAR_MIN_SCORE = 50
    
    HARD_STOP_LOSS_PCT = 0.02
    COOLDOWN_BARS = 2
    TAKE_PROFIT_PCT = 0.02
    SPOT_PROFIT_TARGET_PCT = 0.005
    TRAILING_STOP_PCT = 0.005

    # Binance TR spot komisyonu (Bronz/Standart taker %0.15) - işlem başına
    COMMISSION_PCT = float(os.getenv("COMMISSION_PCT", "0.0015"))
    ESTIMATED_SLIPPAGE_PCT = 0.00025
    MIN_EXPECTED_NET_PNL_TRY = 0.5

    # UT Bot stratejisi — tek aktif strateji
    UT_ENABLED = os.getenv("UT_ENABLED", "false").lower() == "true"
    UT_SYMBOLS = os.getenv("UT_SYMBOLS", "").split(",") if os.getenv("UT_SYMBOLS") else SYMBOLS
    UT_KEY_VALUE = 1.0
    UT_ATR_PERIOD = 11
    UT_HEIKIN_ASHI = True
    UT_TIMEFRAME = os.getenv("UT_TIMEFRAME", "5m")

    # Ek stratejiler (ayrı ayrı aç/kapat)
    BB_SQUEEZE_ENABLED = os.getenv("BB_SQUEEZE_ENABLED", "true").lower() == "true"
    EMA_PULLBACK_ENABLED = os.getenv("EMA_PULLBACK_ENABLED", "false").lower() == "true"
    VWAP_MACD_ENABLED = os.getenv("VWAP_MACD_ENABLED", "false").lower() == "true"
    CMO_CRSI_ENABLED = os.getenv("CMO_CRSI_ENABLED", "false").lower() == "true"
    EMA_VWAP_ENABLED = os.getenv("EMA_VWAP_ENABLED", "true").lower() == "true"
    BREAKOUT_ENABLED = os.getenv("BREAKOUT_ENABLED", "false").lower() == "true"
    ORDERFLOW_ENABLED = os.getenv("ORDERFLOW_ENABLED", "true").lower() == "true"
    MOMENTUM_ENABLED = os.getenv("MOMENTUM_ENABLED", "true").lower() == "true"
    MEAN_REVERSION_ENABLED = os.getenv("MEAN_REVERSION_ENABLED", "true").lower() == "true"
    KELTNER_ENABLED = os.getenv("KELTNER_ENABLED", "true").lower() == "true"
    CHOP_ENABLED = os.getenv("CHOP_ENABLED", "true").lower() == "true"
    DONCHIAN_ENABLED = os.getenv("DONCHIAN_ENABLED", "true").lower() == "true"

    # Canlı strateji eşikleri (Ayarlar > Stratejiler üzerinden güncellenebilir)
    ORDERFLOW_MIN_IMBALANCE = 0.10
    MOMENTUM_SHORT_LOOKBACK = 5
    MOMENTUM_LONG_LOOKBACK = 21
    MOMENTUM_MIN_RETURN_PCT = 0.003
    # MTF Momentum için volatilite kapasitesi filtresi (ADR).
    ADR_FILTER_ENABLED = True
    ADR_PERIOD = 14
    ADR_MIN_PCT = 0.02
    ADR_MAX_UTILIZATION_PCT = 0.80
    ADR_MIN_REMAINING_PCT = 0.01
    KELTNER_EMA_PERIOD = 20
    KELTNER_ATR_PERIOD = 20
    KELTNER_ATR_MULTIPLIER = 1.5
    KELTNER_VOLUME_MULTIPLIER = 1.2
    CHOP_PERIOD = 14
    CHOP_MAX_VALUE = 50.0
    CHOP_MIN_RSI = 50.0
    DONCHIAN_LOOKBACK = 20
    DONCHIAN_VOLUME_MULTIPLIER = 1.15

    # Her stratejinin kendi timeframe'i
    BB_SQUEEZE_TIMEFRAME = os.getenv("BB_SQUEEZE_TIMEFRAME", "5m")
    EMA_PULLBACK_TIMEFRAME = os.getenv("EMA_PULLBACK_TIMEFRAME", "15m")
    VWAP_MACD_TIMEFRAME = os.getenv("VWAP_MACD_TIMEFRAME", "5m")
    CMO_CRSI_TIMEFRAME = os.getenv("CMO_CRSI_TIMEFRAME", "5m")
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
