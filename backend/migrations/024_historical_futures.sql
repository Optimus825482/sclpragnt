-- 024: TARİHSEL USDⓈ-M FUTURES BAĞLAMI (2026-10-17).
-- Binance TR TRY spot defteri için ücretsiz GEÇMİŞ yok; aynı BASE varlığın Binance USDⓈ-M perpetual'ının
-- public arşivleri (data.binance.vision) küresel likidite / türev bağlamı vekili olarak backtest'lerde kullanılır.
-- Doldurma: backend/scripts/backfill_futures_hist.py (90 gün, sha256 doğrulamalı, devam edilebilir).
-- Idempotent; yalnız tablo/index ekler, mevcut tablolara dokunmaz.

-- TRY sembolü -> perp eşlemesi. multiplier: perp 1 sözleşme = multiplier x BASE (1000PEPE -> 1000, LUNA2 -> 1).
CREATE TABLE IF NOT EXISTS futures_symbol_map (
    try_symbol   TEXT PRIMARY KEY,
    base         TEXT NOT NULL,
    perp_symbol  TEXT NOT NULL,
    multiplier   DOUBLE PRECISION NOT NULL DEFAULT 1,
    perp_status  TEXT,
    updated_at   DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_futures_symbol_map_perp ON futures_symbol_map (perp_symbol);

-- metrics (günlük arşiv, ~5 dk): açık pozisyon ve long/short oranları. ts_ms = create_time (UTC) ms.
CREATE TABLE IF NOT EXISTS hist_futures_metrics (
    perp_symbol                       TEXT NOT NULL,
    ts_ms                             BIGINT NOT NULL,
    sum_open_interest                 DOUBLE PRECISION,
    sum_open_interest_value           DOUBLE PRECISION,
    count_toptrader_long_short_ratio  DOUBLE PRECISION,
    sum_toptrader_long_short_ratio    DOUBLE PRECISION,
    count_long_short_ratio            DOUBLE PRECISION,
    sum_taker_long_short_vol_ratio    DOUBLE PRECISION,
    PRIMARY KEY (perp_symbol, ts_ms)
);

-- bookDepth (günlük arşiv, ham ~25 sn x 10 seviye): +-1..5 % derinlik. Ham uzun biçim ~780M satır olurdu;
-- bu yüzden GENİŞ biçim + her 5 dk dilimin SON anlık görüntüsü saklanır (ts_ms = anlık görüntünün gerçek zamanı,
-- dilim kapanışında bilinen veri -> bakış-ileri yok). bid_* = negatif yüzde (alış), ask_* = pozitif yüzde (satış).
-- *_n{k}: k % içindeki toplam notional (USDT), *_d{k}: k % içindeki toplam derinlik (BASE miktarı).
CREATE TABLE IF NOT EXISTS hist_futures_bookdepth (
    perp_symbol  TEXT NOT NULL,
    ts_ms        BIGINT NOT NULL,
    bid_n1 DOUBLE PRECISION, bid_n2 DOUBLE PRECISION, bid_n3 DOUBLE PRECISION, bid_n4 DOUBLE PRECISION, bid_n5 DOUBLE PRECISION,
    ask_n1 DOUBLE PRECISION, ask_n2 DOUBLE PRECISION, ask_n3 DOUBLE PRECISION, ask_n4 DOUBLE PRECISION, ask_n5 DOUBLE PRECISION,
    bid_d1 DOUBLE PRECISION, bid_d2 DOUBLE PRECISION, bid_d3 DOUBLE PRECISION, bid_d4 DOUBLE PRECISION, bid_d5 DOUBLE PRECISION,
    ask_d1 DOUBLE PRECISION, ask_d2 DOUBLE PRECISION, ask_d3 DOUBLE PRECISION, ask_d4 DOUBLE PRECISION, ask_d5 DOUBLE PRECISION,
    PRIMARY KEY (perp_symbol, ts_ms)
);

-- fonlama oranı (aylık arşiv: calc_time, last_funding_rate; mark_price yalnız REST'ten gelir, aksi halde NULL).
CREATE TABLE IF NOT EXISTS hist_funding_rate (
    perp_symbol             TEXT NOT NULL,
    funding_time_ms         BIGINT NOT NULL,
    funding_rate            DOUBLE PRECISION,
    mark_price              DOUBLE PRECISION,
    funding_interval_hours  SMALLINT,
    PRIMARY KEY (perp_symbol, funding_time_ms)
);
