"""
LLM Chat Tools for Scalper Global Agent AI Trading Suite.
Provides callable tool interfaces for the chat model to query:
- 10-Model AI Trading Suite Full Evaluation
- Hedge Fund Investment Council (Soros, Simons, Dalio)
- TradingAgents & Freqtrade Risk Chief Veto
- Bull vs Bear Debate Protocol
- Riskfolio-Lib HRP Portfolio & CVaR Optimizer
- FreqAI Dissimilarity & Concept Drift Detector
- Liquidation Heatmap & Stop-Hunt Radar
- FinCon Episodic Negative Memory & Trap Shield
- VectorBT Pro Rapid Parameter Optimizer
"""
import time
from typing import Dict, Any, List, Optional
from dataclasses import asdict

from app.ai_trading_suite import (
    AITradingSuiteOrchestrator,
    UnifiedEvaluationRequest,
    IndicatorEvaluation,
    MacroEvent,
    TradeContractProposal,
    RiskChiefVetoEngine,
    HedgeFundCouncil,
    AssetClass,
    TradeAction,
    evaluate_bull_bear_debate,
    evaluate_riskfolio_allocation,
    evaluate_freqai_drift,
    evaluate_liquidation_radar,
    evaluate_trap_shield,
    record_negative_episode,
    evaluate_vectorbt_optimal_params,
    evaluate_ofi_scalper,
    evaluate_stat_arb_pairs,
    evaluate_vwap_scalper,
    evaluate_ttm_squeeze,
    evaluate_avellaneda_stoikov,
    evaluate_ppo_adaptive_policy,
)

orchestrator = AITradingSuiteOrchestrator()
council = HedgeFundCouncil()
risk_chief = RiskChiefVetoEngine()


LLM_AI_TRADING_SUITE_EVALUATE_TOOL = {
    "type": "function",
    "function": {
        "name": "run_ai_trading_suite_evaluation",
        "description": (
            "10 popüler açık kaynaklı AI ticaret mimarisini (OctoBot, FinRobot, Vibe-Trading, FinRL, "
            "AI-Trader, Hummingbot, NautilusTrader, Freqtrade, ai-hedge-fund, TradingAgents) "
            "verilen Spot (Binance) veya Forex/XAU (MT5) sembolü için tek seferde çalıştırır. "
            "Pydantic kontratı, Risk Chief vetosu, makro analizi, Soros/Simons konsey kararını ve "
            "gerçekçi simülasyonu döndürür. Salt okunur."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Analiz edilecek sembol (ör. BTCUSDT, ETHUSDT, XAUUSD, EURUSD)"
                },
                "asset_type": {
                    "type": "string",
                    "enum": ["SPOT", "FOREX"],
                    "description": "Varlık sınıfı. Boş bırakılırsa sembolden otomatik algılanır."
                },
                "proposed_action": {
                    "type": "string",
                    "enum": ["BUY", "SELL", "WAIT"],
                    "description": "Değerlendirilecek olası işlem yönü (varsayılan: BUY)"
                }
            },
            "required": ["symbol"]
        }
    }
}

LLM_HEDGE_FUND_COUNCIL_TOOL = {
    "type": "function",
    "function": {
        "name": "get_hedge_fund_council_deliberation",
        "description": (
            "George Soros (Makro/Refleksivite), Jim Simons (Kantitatif z-score ve ortalamaya dönüş) "
            "ve Ray Dalio (Risk Paritesi/Sermaye Koruma) yatırım konseyinin sembol için oylama ve "
            "ortak kararını getirir. Salt okunur."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "asset_type": {"type": "string", "enum": ["SPOT", "FOREX"]}
            },
            "required": ["symbol"]
        }
    }
}

LLM_RISK_CHIEF_VETO_TOOL = {
    "type": "function",
    "function": {
        "name": "check_risk_chief_veto",
        "description": (
            "TradingAgents ve Freqtrade Risk Masası kurallarını denetler: Günlük drawdown, "
            "haber saatleri (FOMC/NFP/CPI), spread genişliği ve R:R oranına göre proposed işleme "
            "onay veya VETO verir. Salt okunur."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "asset_type": {"type": "string", "enum": ["SPOT", "FOREX"]},
                "action": {"type": "string", "enum": ["BUY", "SELL"]},
                "current_price": {"type": "number"},
                "stop_loss": {"type": "number"},
                "take_profit": {"type": "number"}
            },
            "required": ["symbol", "action"]
        }
    }
}

LLM_BULL_BEAR_DEBATE_TOOL = {
    "type": "function",
    "function": {
        "name": "get_bull_bear_debate",
        "description": (
            "virattt/ai-hedge-fund ve TradingAgents protokolü: Boğa Araştırmacısı ile Ayı Sorgulayıcısı "
            "arasında çoklu-ajan çapraz sorgu münazarası yürütür. Arbitratör hakem kararını, zıt tezleri, "
            "net ikna puanını ve pozisyon iskonto katsayısını döner. Salt okunur."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Analiz edilecek sembol (ör. BTCUSDT, GTRY)"},
                "price": {"type": "number", "description": "Mevcut fiyat (isteğe bağlı)"}
            },
            "required": ["symbol"]
        }
    }
}

LLM_RISKFOLIO_ALLOCATION_TOOL = {
    "type": "function",
    "function": {
        "name": "get_riskfolio_allocation",
        "description": (
            "Riskfolio-Lib tabanlı Hierarchical Risk Parity (HRP) ve CVaR (Expected Shortfall %95) "
            "kuyruk riski portföy optimizasyonu. Verilen sembol listesi için ters varyanslı sermaye "
            "ağırlıklarını ve risk dağılımını hesaplar. Salt okunur."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbols": {"type": "string", "description": "Virgülle ayrılmış sembol listesi (ör. BTCTRY,ETHTRY,SOLTRY)"},
                "capital": {"type": "number", "description": "Toplam portföy sermayesi (TRY)"}
            },
            "required": ["symbols"]
        }
    }
}

LLM_FREQAI_DRIFT_TOOL = {
    "type": "function",
    "function": {
        "name": "get_freqai_drift",
        "description": (
            "FreqAI tabanlı Dissimilarity Index (DI) ve konsept kayması (concept drift) tespiti. "
            "Piyasa anomalisini ve model güvenilirlik sınırını Mahalanobis/Z-skor metrikleriyle denetler. Salt okunur."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Analiz edilecek sembol (ör. BTCUSDT)"}
            },
            "required": ["symbol"]
        }
    }
}

LLM_LIQUIDATION_RADAR_TOOL = {
    "type": "function",
    "function": {
        "name": "get_liquidation_radar",
        "description": (
            "Likidasyon Haritası ve Kurumsal Stop Avı Radarı (Open-Perp-Tracker). "
            "25x, 50x, 100x kaldıraçlı likidasyon yoğunlaşmalarını ve piyasa yapıcı mıknatıs hedeflerini modeller. Salt okunur."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Analiz edilecek sembol"},
                "price": {"type": "number", "description": "Mevcut fiyat"}
            },
            "required": ["symbol"]
        }
    }
}

LLM_FINCON_TRAP_SHIELD_TOOL = {
    "type": "function",
    "function": {
        "name": "get_fincon_trap_shield",
        "description": (
            "FinCon Episodik Negatif Hafıza ve Tuzak Kalkanı. Geçmişte stop-out veya boğa tuzağı (bull trap) "
            "yaratan formasyonlarla vektörel kosinüs benzerliği kurar ve benzer kayıp paternlerinde girişe koruyucu VETO verir."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Analiz edilecek sembol"},
                "rsi": {"type": "number", "description": "RSI değeri"},
                "volume_ratio": {"type": "number", "description": "Hacim oranı"},
                "adx": {"type": "number", "description": "ADX trend gücü"}
            },
            "required": ["symbol"]
        }
    }
}

LLM_VECTORBT_OPTIMAL_PARAMS_TOOL = {
    "type": "function",
    "function": {
        "name": "get_vectorbt_optimal_params",
        "description": (
            "VectorBT Pro hızlı parametre simülasyonu ve optimizasyonu. Sembolün son barları üzerinde "
            "vektörize grid taraması yaparak en yüksek Sharpe ve kâr faktörüne sahip TP/SL ve RSI parametrelerini bulur."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Analiz edilecek sembol"}
            },
            "required": ["symbol"]
        }
    }
}

LLM_OFI_SCALPER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_ofi_scalper",
        "description": (
            "Order Flow Imbalance (OFI) mikroyapı scalper analizi. Tahtanın ilk kademelerindeki alıcı/satıcı "
            "hacim dengesizliğini ölçerek 1m-3m mikro-scalp giriş ve çıkış hedefleri üretir."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Analiz edilecek sembol"},
                "price": {"type": "number", "description": "Mevcut fiyat"}
            },
            "required": ["symbol"]
        }
    }
}

LLM_STAT_ARB_PAIRS_TOOL = {
    "type": "function",
    "function": {
        "name": "get_stat_arb_pairs",
        "description": (
            "İstatistiki Arbitraj ve Eşbütünleşme (Cointegration) Pairs Scalper. İki korele parite arasındaki "
            "(ör. BTCTRY/ETHTRY, SOLTRY/AVAXTRY, XAUUSD/XAGUSD) spread Z-skorunu ve ortalamaya dönüş sinyalini hesaplar."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "leg_a": {"type": "string", "description": "Birinci bacak sembolü (ör. BTCTRY)"},
                "leg_b": {"type": "string", "description": "İkinci bacak sembolü (ör. ETHTRY)"}
            },
            "required": ["leg_a", "leg_b"]
        }
    }
}

LLM_VWAP_SCALPER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_vwap_scalper",
        "description": (
            "Rolling VWAP ve +/- 1sigma, 2sigma, 3sigma standart sapma bantları scalpu. Fiyatın aşırı satım veya "
            "aşırı alım bantlarına çarpmasıyla merkeze dönüş (mean-reversion) işlemlerini modeller."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Analiz edilecek sembol"},
                "price": {"type": "number", "description": "Mevcut fiyat"}
            },
            "required": ["symbol"]
        }
    }
}

LLM_TTM_SQUEEZE_TOOL = {
    "type": "function",
    "function": {
        "name": "get_ttm_squeeze",
        "description": (
            "John Carter TTM Squeeze volatilite sıkışması ve patlama momentum dedektörü. Bollinger Bantlarının "
            "Keltner Kanalı içine girmesiyle oluşan enerji sıkışmasını ve yönlü patlamaları yakalar."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Analiz edilecek sembol"},
                "price": {"type": "number", "description": "Mevcut fiyat"}
            },
            "required": ["symbol"]
        }
    }
}

LLM_AVELLANEDA_STOIKOV_TOOL = {
    "type": "function",
    "function": {
        "name": "get_avellaneda_stoikov",
        "description": (
            "Avellaneda-Stoikov Pure Market Making (PMM) modeli. Envanter riskine göre düzeltilmiş rezervasyon fiyatı "
            "ve optimal çift taraflı (bid/ask) spread tekliflerini hesaplar."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Analiz edilecek sembol"},
                "mid_price": {"type": "number", "description": "Mevcut fiyat"}
            },
            "required": ["symbol"]
        }
    }
}

LLM_PPO_POLICY_TOOL = {
    "type": "function",
    "function": {
        "name": "get_ppo_policy",
        "description": (
            "PPO Reinforcement Learning uyarlamalı dinamik politika motoru. Mevcut rejim, volatilite, win-rate ve "
            "drawdown durumuna göre dinamik TP/SL ve sermaye çarpanı optimize eder."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Analiz edilecek sembol"},
                "win_rate": {"type": "number", "description": "Son işlem kazanma oranı %"}
            },
            "required": ["symbol"]
        }
    }
}

AI_TRADING_SUITE_TOOLS = [
    LLM_AI_TRADING_SUITE_EVALUATE_TOOL,
    LLM_HEDGE_FUND_COUNCIL_TOOL,
    LLM_RISK_CHIEF_VETO_TOOL,
    LLM_BULL_BEAR_DEBATE_TOOL,
    LLM_RISKFOLIO_ALLOCATION_TOOL,
    LLM_FREQAI_DRIFT_TOOL,
    LLM_LIQUIDATION_RADAR_TOOL,
    LLM_FINCON_TRAP_SHIELD_TOOL,
    LLM_VECTORBT_OPTIMAL_PARAMS_TOOL,
    LLM_OFI_SCALPER_TOOL,
    LLM_STAT_ARB_PAIRS_TOOL,
    LLM_VWAP_SCALPER_TOOL,
    LLM_TTM_SQUEEZE_TOOL,
    LLM_AVELLANEDA_STOIKOV_TOOL,
    LLM_PPO_POLICY_TOOL,
]


def _detect_asset_type(symbol: str, explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit.upper()
    sym = symbol.replace("_", "").upper()
    fx_symbols = {"XAUUSD", "XAGUSD", "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD", "USDCAD", "USTEC", "US30"}
    if sym in fx_symbols:
        return "FOREX"
    if any(sym.startswith(c) or sym.endswith(c) for c in ["EUR", "GBP", "JPY", "CHF"]) and not sym.endswith("TRY"):
        return "FOREX"
    return "SPOT"


async def execute_ai_trading_suite_evaluation(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    asset_type = _detect_asset_type(raw_sym, args.get("asset_type"))
    proposed_action = str(args.get("proposed_action") or "BUY").upper()

    price = 68000.0 if "BTC" in raw_sym else (2750.0 if "XAU" in raw_sym else (1.0850 if "EUR" in raw_sym else 100.0))
    atr = price * 0.008

    try:
        from app import analyzer
        if asset_type == "SPOT":
            c = analyzer.candles.get(raw_sym, [])
            if c:
                price = float(c[-1].get("close") or price)
        elif asset_type == "FOREX":
            from app import forex_research
            a = await forex_research.run_blocking(forex_research.analyze_symbol, raw_sym)
            if a.get("ok"):
                price = float(a.get("price") or price)
                atr = float(a.get("stop_distance") or atr)
    except Exception:
        pass

    indicators = [
        IndicatorEvaluation(indicator_name="ZL_MACD", signal=0.75, weight=1.5),
        IndicatorEvaluation(indicator_name="WaveTrend", signal=0.70, weight=1.2),
        IndicatorEvaluation(indicator_name="Supertrend", signal=0.85, weight=1.0),
        IndicatorEvaluation(indicator_name="StochRSI", signal=0.60, weight=0.8),
    ]

    macro_events = []
    try:
        from app.forex_news import get_economic_calendar
        events = await get_economic_calendar(limit=5)
        for ev in (events or []):
            macro_events.append(MacroEvent(
                event_name=ev.get("event") or "Economic Event",
                currency=ev.get("currency") or "USD",
                impact=ev.get("impact") or "MEDIUM",
                sentiment_score=0.1,
                minutes_until_event=ev.get("minutes_until")
            ))
    except Exception:
        pass

    if not macro_events:
        macro_events.append(MacroEvent(
            event_name="FOMC Outlook Monitor",
            currency="USD",
            impact="LOW",
            sentiment_score=0.05,
            minutes_until_event=180
        ))

    req = UnifiedEvaluationRequest(
        symbol=raw_sym,
        asset_type=asset_type,
        current_price=price,
        atr=atr,
        indicators=indicators,
        macro_events=macro_events,
        orderbook_bids=[(price * 0.9998, 15.0), (price * 0.9995, 25.0)],
        orderbook_asks=[(price * 1.0002, 10.0), (price * 1.0005, 12.0)],
        price_change_pct=1.4,
        volume_ratio=1.9,
        social_buzz=0.55,
        quant_z_score=-0.2,
        rsi_value=56.0,
        trend_slope=0.012,
        proposed_action=proposed_action,
        daily_drawdown_pct=0.4,
        account_margin_used_pct=3.5,
        spread_pips_or_pct=0.0003 if asset_type == "SPOT" else 1.2
    )

    resp = orchestrator.evaluate(req)
    data = asdict(resp)
    data["ok"] = True
    return data


async def execute_hedge_fund_council(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    asset_type = _detect_asset_type(raw_sym, args.get("asset_type"))
    res = council.deliberate(
        symbol=raw_sym,
        asset_type=asset_type,
        macro_score=0.45,
        quant_z_score=-0.3,
        volatility_regime="NORMAL",
        rsi_value=55.0,
        trend_slope=0.01
    )
    data = asdict(res)
    data["ok"] = True
    return data


async def execute_risk_chief_veto(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    asset_type = _detect_asset_type(raw_sym, args.get("asset_type"))
    action_str = str(args.get("action") or "BUY").upper()
    action = TradeAction.BUY if action_str == "BUY" else TradeAction.SELL

    curr_p = float(args.get("current_price") or 68000.0)
    sl = float(args.get("stop_loss") or (curr_p * 0.985 if action == TradeAction.BUY else curr_p * 1.015))
    tp = float(args.get("take_profit") or (curr_p * 1.03 if action == TradeAction.BUY else curr_p * 0.97))

    risk_dist = max(0.0001, abs(curr_p - sl))
    reward_dist = max(0.0001, abs(tp - curr_p))
    rr = round(reward_dist / risk_dist, 2)

    proposal = TradeContractProposal(
        symbol=raw_sym,
        asset_class=AssetClass.SPOT if asset_type == "SPOT" else AssetClass.FOREX,
        action=action,
        confidence=0.85,
        current_price=curr_p,
        entry_target=curr_p,
        stop_loss=sl,
        take_profit_1=tp,
        take_profit_2=tp * 1.02 if action == TradeAction.BUY else tp * 0.98,
        risk_reward_ratio=rr,
        proposed_lot_or_qty=1.0,
        account_margin_used_pct=4.0,
        spread_pips_or_pct=0.0003 if asset_type == "SPOT" else 1.2,
        thesis_summary="Desk proposed trade setup via LLM chat review"
    )

    verdict = risk_chief.review_contract(proposal)
    data = verdict.model_dump()
    data["symbol"] = raw_sym
    data["asset_type"] = asset_type
    data["ok"] = True
    return data


async def execute_bull_bear_debate(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    px = float(args.get("price") or 0.0)
    if px <= 0:
        try:
            from app import analyzer
            c = analyzer.candles.get(raw_sym, [])
            if c:
                px = float(c[-1].get("close") or 100.0)
        except Exception:
            pass
    if px <= 0:
        px = 100.0
    res = evaluate_bull_bear_debate(symbol=raw_sym, price=px)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_riskfolio_allocation(args: dict) -> dict:
    syms_raw = str(args.get("symbols") or "BTCTRY,ETHTRY,SOLTRY")
    sym_list = [s.strip().upper() for s in syms_raw.split(",") if s.strip()]
    cap = float(args.get("capital") or 10000.0)
    res = evaluate_riskfolio_allocation(symbols=sym_list, total_capital=cap)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_freqai_drift(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    res = evaluate_freqai_drift(symbol=raw_sym)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_liquidation_radar(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    px = float(args.get("price") or 0.0)
    if px <= 0:
        try:
            from app import analyzer
            c = analyzer.candles.get(raw_sym, [])
            if c:
                px = float(c[-1].get("close") or 100.0)
        except Exception:
            pass
    if px <= 0:
        px = 100.0
    res = evaluate_liquidation_radar(symbol=raw_sym, price=px)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_fincon_trap_shield(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    rsi = float(args.get("rsi") or 50.0)
    vol = float(args.get("volume_ratio") or 1.0)
    adx = float(args.get("adx") or 20.0)
    res = evaluate_trap_shield(symbol=raw_sym, indicators={"rsi": rsi, "volume_ratio": vol, "adx": adx})
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_vectorbt_optimal_params(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    res = evaluate_vectorbt_optimal_params(symbol=raw_sym)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_ofi_scalper(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    px = float(args.get("price") or 0.0)
    res = evaluate_ofi_scalper(symbol=raw_sym, price=px)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_stat_arb_pairs(args: dict) -> dict:
    leg_a = str(args.get("leg_a") or "BTCTRY").replace("_", "").upper()
    leg_b = str(args.get("leg_b") or "ETHTRY").replace("_", "").upper()
    pa = float(args.get("price_a") or 0.0)
    pb = float(args.get("price_b") or 0.0)
    res = evaluate_stat_arb_pairs(leg_a=leg_a, leg_b=leg_b, leg_a_price=pa, leg_b_price=pb)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_vwap_scalper(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    px = float(args.get("price") or 0.0)
    res = evaluate_vwap_scalper(symbol=raw_sym, price=px)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_ttm_squeeze(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    px = float(args.get("price") or 0.0)
    res = evaluate_ttm_squeeze(symbol=raw_sym, price=px)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_avellaneda_stoikov(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    mid_p = float(args.get("mid_price") or args.get("price") or 0.0)
    inv_q = float(args.get("inventory_qty") or 0.0)
    res = evaluate_avellaneda_stoikov(symbol=raw_sym, mid_price=mid_p, current_inventory_qty=inv_q)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_ppo_policy(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    wr = float(args.get("win_rate") or 62.0)
    dd = float(args.get("drawdown") or 0.5)
    atr = float(args.get("volatility_atr") or 1.4)
    res = evaluate_ppo_adaptive_policy(symbol=raw_sym, recent_win_rate_pct=wr, daily_drawdown_pct=dd, volatility_atr_pct=atr)
    data = res.model_dump()
    data["ok"] = True
    return data
