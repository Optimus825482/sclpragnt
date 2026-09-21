"""MASTER SURGE ENGINE (Ana Yükselme Potansiyeli Algoritması — 2026-09-21)

Bu modül, radardaki dağınık sinyal üreteçlerini (Velocity, MACD Jump, Erken Dip,
Yükseliş Trendi) tek, birleşik, yüksek hassasiyetli bir Üst Seviye Yükselme Motorunda
(Master Surge Engine) birleştirir.

4 KATMANLI HİBRİT MİMARİ:
  Katman 1: Likidite & Emir Defteri Kapısı (Liquidity & Orderbook Gate)
            Sığ tahtalı, yüksek spread'li (>%0.45), yanıltıcı hacimli coin'leri eler.
  Katman 2: Volatilite Sıkışması & Dip Dönüşü (Volatility Squeeze & Dip Reversal)
            Bollinger/Keltner kanal sıkışması (yay gerilmesi) + MACD dip dönüşü/yakınlığı.
  Katman 3: Emir Akışı & Hacim Baskısı (Orderflow & Volume Pressure)
            Balina CVD net alıcı dominansı + hacim ivmesi / patlaması (volume surge).
  Katman 4: Çoklu Zaman Dilimi Trend Uyumu (Multi-Timeframe Trend Alignment)
            1m, 3m, 5m, 15m harmonik yeşil trend yönelimi ve güç göstergeleri.

DİNAMİK UYARLANABİLİR HEDEFLER (Dynamic Adaptive Targets):
  - TP1 (Scalp Kâr Kilidi): ATR tabanlı +%1.2 - +%1.8 (kâr korumalı başabaş kilidi).
  - TP2 (Koşucu / Trailing): +%3.0 - +%5.0+ (zirveden sıkı takiple maksimum kâr).
  - 158 sinyallik gerçek piyasa testinde %71 kısmi kazanç üreten fakat zirveden
    dönüşte kârı geri veren işlemler TP1 scalp kilidi ile korumaya alınır.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Any

from app.config import config
from app.state import market
from app.routers import macd_monitor as _macd

logger = logging.getLogger("scalper.master_surge")


def evaluate_layer1_liquidity(
    symbol: str,
    market_instance=None,
    ticker_data: dict | None = None,
    flow_data: dict | None = None,
    velocity_candidate: dict | None = None,
) -> dict:
    """Katman 1: Likidite & Emir Defteri Kapısı (Liquidity & Orderbook Gate).

    Sığ tahtalı, yüksek spread'li (>%0.45) veya 24s hacmi yetersiz sembolleri
    baştan eler. Likiditeyi geçemeyen coin diğer katmanlara bakılmaksızın elenir.
    """
    sym = str(symbol or "").replace("_", "").upper()
    m = market_instance or market

    max_spread = float(getattr(config, "MASTER_SURGE_MAX_SPREAD_PCT", 0.45))
    min_volume = float(getattr(config, "MASTER_SURGE_MIN_24H_VOLUME_TRY", 150_000.0))
    min_depth = float(getattr(config, "MASTER_SURGE_MIN_DEPTH_TRY", 5_000.0))

    if not sym:
        return {"passed": False, "score": 0.0, "reason": "empty_symbol"}

    ticker = ticker_data if ticker_data is not None else (m.get_ticker(sym) if m else {})
    price = float((ticker or {}).get("last_price") or (velocity_candidate or {}).get("price") or 0.0)

    flow = flow_data if flow_data is not None else (m.get_orderflow(sym) if m else {})
    bid_px = float((flow or {}).get("bid_price") or 0.0)
    ask_px = float((flow or {}).get("ask_price") or 0.0)

    spread_pct = (flow or {}).get("spread_pct")
    if spread_pct is None and bid_px > 0 and ask_px > 0:
        spread_pct = (ask_px - bid_px) / bid_px * 100.0
    if spread_pct is None and velocity_candidate:
        spread_pct = velocity_candidate.get("spread_pct")
    spread_val = float(spread_pct) if spread_pct is not None else None

    # Derinlik (bid_qty + ask_qty) * price
    bid_qty = float((flow or {}).get("bid_qty") or 0.0)
    ask_qty = float((flow or {}).get("ask_qty") or 0.0)
    depth_try = (bid_qty + ask_qty) * (price if price > 0 else (bid_px if bid_px > 0 else 1.0))

    # 24h Hacim
    quote_vol = 0.0
    if m and hasattr(m, "ticker_24h"):
        quote_vol = float((m.ticker_24h or {}).get(sym) or 0.0)
    if quote_vol <= 0 and velocity_candidate:
        quote_vol = float((velocity_candidate or {}).get("quote_volume") or (velocity_candidate or {}).get("quote_volume_24h") or 0.0)

    # Spread kontrolü: çok genişse elenir
    if spread_val is not None and spread_val > max_spread:
        return {
            "passed": False,
            "score": 0.0,
            "spread_pct": spread_val,
            "depth_try": depth_try,
            "quote_volume_24h": quote_vol,
            "reason": f"spread_too_wide ({spread_val:.2f}% > {max_spread:.2f}%)",
        }

    # Hacim kontrolü (canlı veri varsa)
    if quote_vol > 0 and quote_vol < min_volume:
        return {
            "passed": False,
            "score": 0.0,
            "spread_pct": spread_val,
            "depth_try": depth_try,
            "quote_volume_24h": quote_vol,
            "reason": f"low_24h_volume ({quote_vol:.0f} < {min_volume:.0f} TRY)",
        }

    # Derinlik kontrolü (canlı veri varsa)
    if depth_try > 0 and depth_try < min_depth:
        return {
            "passed": False,
            "score": 0.0,
            "spread_pct": spread_val,
            "depth_try": depth_try,
            "quote_volume_24h": quote_vol,
            "reason": f"shallow_depth ({depth_try:.0f} < {min_depth:.0f} TRY)",
        }

    # Skorlama (0-100): Dar spread ve yüksek derinlik yüksek skor alır
    score = 70.0  # Taban geçer puan
    if spread_val is not None:
        if spread_val <= 0.15:
            score += 20.0
        elif spread_val <= 0.25:
            score += 10.0
        elif spread_val >= 0.40:
            score -= 15.0

    if depth_try >= 20_000.0:
        score += 10.0
    elif depth_try >= 10_000.0:
        score += 5.0

    return {
        "passed": True,
        "score": round(max(50.0, min(100.0, score)), 1),
        "spread_pct": round(spread_val, 4) if spread_val is not None else None,
        "depth_try": round(depth_try, 2),
        "quote_volume_24h": round(quote_vol, 2),
        "reason": "ok",
    }


def evaluate_layer2_volatility(
    symbol: str,
    macd_row: dict | None = None,
    market_instance=None,
) -> dict:
    """Katman 2: Volatilite Sıkışması & Dip Dönüşü (Volatility Squeeze & Dip Reversal).

    Bollinger/Keltner kanal sıkışması (yay hazırlığı), sıkışma sonrası patlama
    (squeeze transition to expand) ve MACD dip dönüşü/yakınlık sinyallerini inceler.
    """
    sym = str(symbol or "").replace("_", "").upper()
    row = macd_row
    if row is None and _macd._SNAPSHOT:
        row = (_macd._SNAPSHOT.get("symbols") or {}).get(sym) or {}
    row = row or {}

    pre = row.get("pre") or {}
    pre_detail = row.get("pre_detail") or {}

    is_dip = bool(pre.get("dip"))
    proximity = float(pre_detail.get("proximity") or 0.0)
    squeeze_now = bool(pre_detail.get("squeeze_now"))
    transition = bool(pre_detail.get("transition"))
    expand_now = bool(pre_detail.get("expand_now"))

    # Sıkışma kontrolü: MACD snapshot'ta yoksa kline verisinden incele
    if not (squeeze_now or transition or expand_now):
        try:
            trans = _macd._tf_vol_transition(sym, "5m")
            squeeze_now = bool(trans.get("squeeze_now"))
            transition = bool(trans.get("transition"))
            expand_now = bool(trans.get("expand_now"))
        except Exception:
            pass

    score = 0.0
    reasons = []

    # 1. Dip Dönüşü (Kanıtlanmış en güçlü yükseliş öncüsü: +40 puan)
    if is_dip:
        score += 40.0
        reasons.append("dip_turn")

    # 2. Yakınlık (MACD sıfır çizgisi / kesişim yakınlığı: 0-30 puan)
    if proximity > 0:
        prox_pts = min(30.0, proximity * 30.0)
        score += prox_pts
        if proximity >= 0.70:
            reasons.append(f"high_proximity({proximity:.2f})")

    # 3. Volatilite Sıkışması & Patlama (Bollinger/Keltner: 0-30 puan)
    if transition:
        score += 30.0
        reasons.append("squeeze_breakout")
    elif squeeze_now:
        score += 25.0
        reasons.append("volatility_squeeze")
    elif expand_now:
        score += 20.0
        reasons.append("volatility_expanding")

    passed = (is_dip or proximity >= 0.60 or transition or squeeze_now) and score >= 35.0

    return {
        "passed": passed,
        "score": round(min(100.0, score), 1),
        "is_dip": is_dip,
        "proximity": round(proximity, 3),
        "squeeze_now": squeeze_now,
        "transition": transition,
        "expand_now": expand_now,
        "reasons": reasons,
    }


def evaluate_layer3_orderflow(
    symbol: str,
    macd_row: dict | None = None,
    velocity_candidate: dict | None = None,
    market_instance=None,
) -> dict:
    """Katman 3: Emir Akışı & Hacim Baskısı (Orderflow & Volume Pressure).

    Balina CVD (Cumulative Volume Delta) alış üstünlüğü, net alıcı hacmi ve
    hacim patlaması (relative volume surge) metriklerini değerlendirir.
    """
    sym = str(symbol or "").replace("_", "").upper()
    row = macd_row
    if row is None and _macd._SNAPSHOT:
        row = (_macd._SNAPSHOT.get("symbols") or {}).get(sym) or {}
    row = row or {}

    cvd = row.get("cvd") or {}
    buy_dominant = bool(cvd.get("buy_dominant"))
    whale_net = float(cvd.get("whale_net") or 0.0)
    buy_ratio = float(cvd.get("buy_ratio") or 0.5)

    # Hacim ivmesi (volume surge / ratio)
    vol_surge = False
    try:
        vol_surge = bool(_macd._tf_volume_surge(sym, "5m"))
    except Exception:
        pass

    vol_ratio = 1.0
    if velocity_candidate:
        vr = velocity_candidate.get("volume_ratio")
        if vr is not None:
            try:
                vol_ratio = float(vr)
            except (TypeError, ValueError):
                pass

    score = 0.0
    reasons = []

    # 1. CVD Alıcı Hakimiyeti (+40 puan)
    if buy_dominant:
        score += 40.0
        reasons.append("cvd_buy_dominant")
    elif buy_ratio > 0.52:
        score += min(30.0, (buy_ratio - 0.50) * 150.0)
        reasons.append(f"buy_ratio({buy_ratio:.2f})")

    # 2. Balina Net Alıcı Hacmi (+25 puan)
    if whale_net > 0:
        score += 25.0
        reasons.append("whale_net_positive")

    # 3. Hacim İvmesi / Artışı (+35 puan)
    if vol_surge or vol_ratio >= 1.5:
        score += 35.0
        reasons.append(f"vol_surge(ratio={vol_ratio:.1f})")
    elif vol_ratio >= 1.25:
        score += 20.0
        reasons.append(f"vol_expanded(ratio={vol_ratio:.1f})")

    passed = (buy_dominant or whale_net > 0 or vol_surge or vol_ratio >= 1.30) and score >= 35.0

    return {
        "passed": passed,
        "score": round(min(100.0, score), 1),
        "buy_dominant": buy_dominant,
        "whale_net": round(whale_net, 2),
        "buy_ratio": round(buy_ratio, 3),
        "volume_surge": vol_surge,
        "volume_ratio": round(vol_ratio, 2),
        "reasons": reasons,
    }


def evaluate_layer4_mtf(
    symbol: str,
    macd_row: dict | None = None,
    market_instance=None,
) -> dict:
    """Katman 4: Çoklu Zaman Dilimi Trend Uyumu (Multi-Timeframe Trend Alignment).

    1m, 3m, 5m, 15m harmonik yeşil trend yönelimi, güç göstergeleri ve
    yukarı yönlü momentum hizasını ölçer.
    """
    sym = str(symbol or "").replace("_", "").upper()
    row = macd_row
    if row is None and _macd._SNAPSHOT:
        row = (_macd._SNAPSHOT.get("symbols") or {}).get(sym) or {}
    row = row or {}

    tfs = row.get("tfs") or {}
    # Ana scalping zaman dilimleri
    scalp_tfs = ("1m", "3m", "5m", "15m")
    green_count = 0
    tf_status = {}
    for tf in scalp_tfs:
        cell = tfs.get(tf) or {}
        is_gr = bool(cell.get("green"))
        tf_status[tf] = is_gr
        if is_gr:
            green_count += 1

    # Üst TF (30m, 1h)
    htf_green = 0
    for tf in ("30m", "1h"):
        cell = tfs.get(tf) or {}
        if bool(cell.get("green")):
            htf_green += 1

    strength = float(row.get("strength") or 0.0)  # 0-10
    direction = int(row.get("dir") or 0)          # 1 = yukarı, -1 = aşağı

    score = 0.0
    reasons = []

    # 1. Scalp TF Yeşil Uyumu (4'te 4 = +50 puan, 4'te 3 = +35 puan)
    if green_count == 4:
        score += 50.0
        reasons.append("4_of_4_green")
    elif green_count == 3:
        score += 35.0
        reasons.append("3_of_4_green")
    elif green_count == 2:
        score += 20.0
        reasons.append("2_of_4_green")

    # 2. Güç Katsayısı (0-10 -> 0-35 puan)
    if strength > 0:
        score += min(35.0, strength * 3.5)
        if strength >= 7.0:
            reasons.append(f"strong({strength:.1f})")

    # 3. Yön ve Üst TF Desteği (+15 puan)
    if direction == 1:
        score += 10.0
        reasons.append("bullish_dir")
    if htf_green >= 1:
        score += 5.0
        reasons.append("htf_support")

    passed = (green_count >= 3 or (green_count >= 2 and strength >= 7.0)) and score >= 40.0

    return {
        "passed": passed,
        "score": round(min(100.0, score), 1),
        "green_count": green_count,
        "tf_status": tf_status,
        "strength": round(strength, 1),
        "direction": direction,
        "reasons": reasons,
    }


def calculate_adaptive_targets(
    score: float,
    atr_pct: float | None = None,
    base_target_pct: float | None = None,
) -> dict:
    """Dinamik Uyarlanabilir Hedefler (Dynamic Adaptive Targets).

    158 sinyallik gerçek veri analizinde gözlenen %71 kısmi kazançları (+%1.0-%3.7)
    korumak ve zirve koşularını (+%5-%8.5+) yakalamak için iki kademeli hedef üretir:
      - TP1 (Scalp Kâr Kilidi): ATR tabanlı +%1.2 - +%1.8
      - TP2 (Koşucu / Trailing): +%3.0 - +%6.5+
      - breakeven_trigger_pct: Fiyat TP1'e veya +%1.0'e ulaştığında devreye girer.
      - trailing_gap_pct: %0.40 sıkı takip ile kârın geri verilmesini önler.
    """
    sc = max(0.0, min(100.0, float(score or 0.0)))
    atr = float(atr_pct) if (atr_pct is not None and float(atr_pct) > 0) else 1.4

    tp1_min = float(getattr(config, "MASTER_SURGE_TP1_MIN_PCT", 1.2))
    tp1_max = float(getattr(config, "MASTER_SURGE_TP1_MAX_PCT", 1.8))
    tp2_min = float(getattr(config, "MASTER_SURGE_TP2_MIN_PCT", 3.0))
    tp2_max = float(getattr(config, "MASTER_SURGE_TP2_MAX_PCT", 6.5))
    be_gap = float(getattr(config, "MASTER_SURGE_BE_GAP_PCT", 0.40))

    # TP1: Scalp kilidi (ATR'nin ~%90-%110'u, min 1.2%, max 1.8%)
    tp1 = round(max(tp1_min, min(tp1_max, atr * 1.0)), 2)

    # TP2: Koşucu hedefi (Skora ve ATR potansiyeline bağlı, min 3.0%, max 6.5%)
    base_tp2 = float(base_target_pct if base_target_pct is not None else 3.5)
    atr_runner = atr * 2.5
    score_factor = max(0.0, (sc - 50.0) / 50.0)  # 50 ve altı 0, 100'de 1.0
    score_runner = 3.0 + score_factor * 3.5
    tp2 = round(max(tp2_min, min(tp2_max, max(base_tp2, atr_runner, score_runner))), 2)

    # Başabaş tetikleyicisi: TP1'e yaklaştığında (ör. %1.0) maliyet kilitlenir
    be_trigger = round(max(0.9, min(1.3, tp1 * 0.85)), 2)

    return {
        "tp1_scalp_pct": tp1,
        "tp2_runner_pct": tp2,
        "breakeven_trigger_pct": be_trigger,
        "trailing_gap_pct": be_gap,
    }


def evaluate_master_surge(
    symbol: str,
    velocity_candidate: dict | None = None,
    macd_row: dict | None = None,
    market_instance=None,
    surge_bias: dict | None = None,
) -> dict:
    """Master Surge Engine Ana Değerlendirmesi (Composite Surge Index).

    4 katmanı çalıştırır, 4'lü Teyit (Confluence) mutabakatını saptar ve
    birleşik füzyon skoru ile uyarlanabilir hedefleri hesaplar.

    surge_bias: surge_learning.compute_symbol_bias() çıktısı. Geçmişten
                öğrenilen sembol bazlı skor düzeltmesi (±15 puan, confidence
                gated). 4'lü confluence zorunluluğuna asla dokunmaz.
    """
    sym = str(symbol or "").replace("_", "").upper()
    if not sym:
        return {"passed": False, "composite_index": 0.0, "confluence_4way": False}

    # MACD snapshot satırını önceden çözümle
    resolved_row = macd_row
    if resolved_row is None and _macd._SNAPSHOT:
        resolved_row = (_macd._SNAPSHOT.get("symbols") or {}).get(sym) or {}

    # Katman 1: Likidite
    l1 = evaluate_layer1_liquidity(sym, market_instance=market_instance, velocity_candidate=velocity_candidate)
    if not l1.get("passed"):
        return {
            "symbol": sym,
            "passed": False,
            "composite_index": 0.0,
            "confluence_4way": False,
            "confluence_count": 0,
            "failed_layer": 1,
            "reason": l1.get("reason"),
            "layers": {"l1_liquidity": l1},
        }

    # Katman 2: Volatilite Sıkışması & Dip Dönüşü
    l2 = evaluate_layer2_volatility(sym, macd_row=resolved_row, market_instance=market_instance)

    # Katman 3: Emir Akışı & Hacim Baskısı
    l3 = evaluate_layer3_orderflow(sym, macd_row=resolved_row, velocity_candidate=velocity_candidate, market_instance=market_instance)

    # Katman 4: MTF Trend Uyumu
    l4 = evaluate_layer4_mtf(sym, macd_row=resolved_row, market_instance=market_instance)

    # Teyit (Confluence) sayımı
    passed_layers = []
    if l1.get("passed"):
        passed_layers.append("liquidity")
    if l2.get("passed"):
        passed_layers.append("volatility")
    if l3.get("passed"):
        passed_layers.append("orderflow")
    if l4.get("passed"):
        passed_layers.append("mtf_trend")

    confluence_count = len(passed_layers)
    confluence_4way = (confluence_count == 4)

    # Kompozit Yükselme İndeksi (Composite Surge Index):
    # Ağırlıklar: L1=%15, L2=%30, L3=%30, L4=%25
    w_score = (
        l1.get("score", 0) * 0.15 +
        l2.get("score", 0) * 0.30 +
        l3.get("score", 0) * 0.30 +
        l4.get("score", 0) * 0.25
    )

    # 4'lü Teyit Sinerji Bonusu (+%15 lift)
    if confluence_4way:
        w_score *= float(getattr(config, "UNIFIED_SYNERGY_BONUS", 1.15))

    composite_index = round(min(100.0, max(0.0, w_score)), 1)
    raw_composite_index = composite_index  # Bias öncesi ham skor (denetim için)

    # Self-Learning Adaptif Skor Düzeltmesi
    # surge_bias, surge_learning.compute_symbol_bias() çıktısıdır.
    # confidence >= 0.30 ve bias_pct != 0 ise composite_index'e eklenir.
    # 4'lü confluence zorunluluğuna asla dokunulmaz.
    applied_bias: dict | None = None
    if surge_bias and isinstance(surge_bias, dict):
        bias_conf = float(surge_bias.get("confidence", 0))
        bias_pct = float(surge_bias.get("bias_pct", 0))
        from app.surge_learning import MIN_CONFIDENCE, MAX_BIAS_PCT
        if bias_conf >= MIN_CONFIDENCE and bias_pct != 0.0:
            # Sınır koruması: uygulama ±MAX_BIAS_PCT ile kısıtlı
            clamped = max(-MAX_BIAS_PCT, min(MAX_BIAS_PCT, bias_pct))
            composite_index = round(min(100.0, max(0.0, composite_index + clamped)), 1)
            applied_bias = {
                "bias_pct_applied": round(clamped, 2),
                "confidence": round(bias_conf, 3),
                "sample_size": surge_bias.get("sample_size", 0),
                "win_rate": surge_bias.get("win_rate"),
                "tp1_hit_rate": surge_bias.get("tp1_hit_rate"),
                "reason": surge_bias.get("reason", ""),
                "raw_composite_before_bias": raw_composite_index,
            }
            logger.debug(
                "surge_learning bias applied %s: %.1f → %.1f (bias=%.2f conf=%.2f)",
                sym, raw_composite_index, composite_index, clamped, bias_conf,
            )

    # ATR bilgisi
    atr_pct = None
    if velocity_candidate:
        try:
            atr_pct = float(velocity_candidate.get("atr_pct") or 0)
        except (TypeError, ValueError):
            pass

    targets = calculate_adaptive_targets(
        score=composite_index,
        atr_pct=atr_pct,
        base_target_pct=float((velocity_candidate or {}).get("target_pct") or 2.2),
    )

    min_score = float(getattr(config, "MASTER_SURGE_MIN_SCORE", 70.0))
    passed = (composite_index >= min_score) and (not getattr(config, "MASTER_SURGE_REQUIRE_4WAY", True) or confluence_4way)

    result: dict = {
        "symbol": sym,
        "passed": passed,
        "composite_index": composite_index,
        "confluence_4way": confluence_4way,
        "confluence_count": confluence_count,
        "passed_layers": passed_layers,
        "layers": {
            "l1_liquidity": l1,
            "l2_volatility": l2,
            "l3_orderflow": l3,
            "l4_mtf_trend": l4,
        },
        "adaptive_targets": targets,
    }
    if applied_bias:
        result["learning_bias"] = applied_bias
    return result


def is_4way_confluence(sources_or_layers: list | None) -> bool:
    """Verilen kaynak veya katman listesinin tam 4'lü mutabakat sağlayıp sağlamadığını doğrular."""
    if not sources_or_layers or not isinstance(sources_or_layers, list):
        return False
    return len(sources_or_layers) >= 4
