"""Binance TR Spot Symbol Registry & Filter.

Global erken-tespit entegrasyonu (2026-10-07) için `D:\\scalperagent_global`
repolarından port edildi. v4 tek borsa (Binance TR) çalıştırır ama Global
taraması aynı çatı altındadır: Global'de (USDT) yakalanan bir hareket YALNIZCA
Binance TR'de listeli baz varlığa sahipse (BTCUSDT→BTCTRY) TR bildirimi ve
otonom işlemine dönüşür. Aksi hâlde TR'de o sembol için fiyat/işlem yoktur.

Bu modül tarama/bildirim/otonom-işlem kapılarında TEK yetkili kaynaktır:
çevrimdışı/başlangıç için tam bootstrap setine sahiptir ve periyodik olarak
Binance TR'den tazelenir.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from typing import Iterable, Set
import urllib.request

from app.config import config, base_asset_of

logger = logging.getLogger("scalper.tr_symbols")

# Binance TR'de listeli ve işlem gören 310 spot baz varlık (çevrimdışı ve başlangıç güvenliği)
BOOTSTRAP_BINANCE_TR_BASE_ASSETS: Set[str] = {
    "0G", "1000CAT", "1000SATS", "1MBABYDOGE", "2Z", "A", "AAVE", "ACE", "ACH", "ACM",
    "ACT", "ADA", "AERO", "AEVO", "AI", "AIGENSYN", "AIXBT", "ALGO", "ALICE", "ALLO",
    "ALPINE", "ALT", "AMP", "ANIME", "ANKR", "APE", "API3", "APT", "AR", "ARB",
    "ARK", "ARKM", "ARPA", "ASR", "ASTER", "AT", "ATM", "ATOM", "AUCTION", "AUDIO",
    "AVAX", "AVNT", "AXL", "AXS", "BABY", "BANANA", "BANK", "BAR", "BARD", "BB",
    "BCH", "BEAMX", "BEL", "BERA", "BIO", "BLUR", "BMT", "BNB", "BOME", "BONK",
    "BREV", "BTC", "C", "CAKE", "CATI", "CELO", "CETUS", "CFG", "CFX", "CHIP",
    "CHZ", "CITY", "CKB", "COMP", "COTI", "COW", "CRV", "CYBER", "DASH", "DODO",
    "DOGE", "DOGS", "DOLO", "DOT", "DYDX", "DYM", "EDEN", "EDU", "EGLD", "EIGEN",
    "ENA", "ENJ", "ENS", "ENSO", "ERA", "ESP", "ETC", "ETH", "ETHFI", "EUL",
    "F", "FDUSD", "FET", "FF", "FIDA", "FIL", "FLOKI", "FOGO", "FORM", "G",
    "GALA", "GAS", "GENIUS", "GIGGLE", "GMT", "GPS", "GRAM", "GRT", "GUN", "HAEDAL",
    "HBAR", "HEI", "HEMI", "HIVE", "HMSTR", "HOLO", "HOME", "HOT", "HUMA", "HYPE",
    "HYPER", "ICP", "ID", "INIT", "INJ", "IO", "IOTA", "JASMY", "JTO", "JUP",
    "JUV", "KAITO", "KAT", "KERNEL", "KITE", "KSM", "LA", "LAYER", "LAZIO", "LDO",
    "LINEA", "LINK", "LISTA", "LPT", "LTC", "LUMIA", "LUNA", "LUNC", "MAGIC", "MANA",
    "MANTA", "MANTRA", "MARSCOIN", "MASK", "MAV", "ME", "MEGA", "MEME", "MET", "METIS",
    "MINA", "MIRA", "MITO", "MMT", "MORPHO", "MOVR", "MUBARAK", "NEAR", "NEIRO", "NEO",
    "NEWT", "NIGHT", "NIL", "NMR", "NOM", "NOT", "NXPC", "OG", "OGN", "ONDO",
    "ONE", "ONT", "OP", "OPEN", "OPG", "OPN", "ORCA", "ORDI", "PARTI", "PAXG",
    "PENDLE", "PENGU", "PEOPLE", "PEPE", "PHA", "PIXEL", "PLUME", "PNUT", "POL", "POLYX",
    "PORTAL", "PORTO", "PROVE", "PSG", "PUMP", "PYTH", "QTUM", "RAD", "RARE", "RAY",
    "RE", "RED", "RENDER", "RESOLV", "REZ", "ROBO", "RONIN", "ROSE", "RSR", "RVN",
    "S", "SAGA", "SAHARA", "SAND", "SANTOS", "SAPIEN", "SCR", "SEI", "SENT", "SHELL",
    "SHIB", "SIGN", "SKL", "SKY", "SLP", "SNX", "SOL", "SOLV", "SOMI", "SOPH",
    "SPELL", "SPK", "STO", "STRAX", "STRK", "STX", "SUI", "SUN", "SUPER", "SUSHI",
    "SXT", "SYRUP", "TAO", "THE", "THETA", "TIA", "TLM", "TNSR", "TOWNS", "TRB",
    "TREE", "TRUMP", "TRX", "TST", "TURBO", "TURTLE", "TWT", "U", "UMA", "UNI",
    "USD1", "USDC", "USDT", "USTC", "USUAL", "VANA", "VET", "VIRTUAL", "W", "WAL",
    "WCT", "WIF", "WLD", "WLFI", "XAI", "XAUT", "XEC", "XLM", "XPL", "XRP",
    "XTZ", "XVG", "YB", "ZAMA", "ZBT", "ZIL", "ZK", "ZKC", "ZKP", "ZRO"
}

_TR_BASE_ASSETS: Set[str] = set(BOOTSTRAP_BINANCE_TR_BASE_ASSETS)
_TR_SYMBOLS: Set[str] = {f"{base}TRY" for base in _TR_BASE_ASSETS} | {f"{base}_TRY" for base in _TR_BASE_ASSETS}

_CACHE_LOCK = threading.Lock()
_CACHE_EXPIRES: float = 0.0
_CACHE_TTL_SEC: float = 3600.0  # 1 saat


def get_binance_tr_base_assets() -> Set[str]:
    """Binance TR'de listeli ve işlem gören baz varlıklar kümesi."""
    with _CACHE_LOCK:
        return set(_TR_BASE_ASSETS)


def get_binance_tr_symbols() -> Set[str]:
    """Binance TR'de geçerli işlem çiftleri kümesi (BTCTRY, BTC_TRY vb.)."""
    with _CACHE_LOCK:
        return set(_TR_SYMBOLS)


def is_binance_tr_symbol(symbol: str | None) -> bool:
    """Verilen sembol veya varlığın Binance TR'de listeli olup olmadığını doğrular.

    Küresel piyasadaki semboller (örn. 'SOLUSDT') için baz varlık ('SOL') kontrol edilir.
    Binance TR'deki semboller (örn. 'SOLTRY', 'SOL_TRY') için doğrudan çift ve baz varlık kontrol edilir.
    """
    if not getattr(config, "BINANCE_TR_FILTER_ENABLED", True):
        return True

    if not symbol:
        return False

    sym_str = str(symbol).strip().upper().replace("_", "")
    base = base_asset_of(sym_str)

    with _CACHE_LOCK:
        if base in _TR_BASE_ASSETS:
            return True
        if sym_str in _TR_SYMBOLS or f"{sym_str}TRY" in _TR_SYMBOLS:
            return True
        if sym_str.endswith("TRY") and sym_str[:-3] in _TR_BASE_ASSETS:
            return True

    return False


def filter_binance_tr_symbols(symbols: Iterable[str]) -> list[str]:
    """Sembol listesini sadece Binance TR'de mevcut olanlarla filtreler."""
    if not getattr(config, "BINANCE_TR_FILTER_ENABLED", True):
        return list(symbols)
    return [s for s in symbols if is_binance_tr_symbol(s)]


def map_to_tr_symbol(symbol: str) -> str:
    """Global sembolü TR karşılığına eşle: `SOLUSDT` → `SOLTRY`.

    Baz varlık korunur; TR'de işlem çifti daima `<base>TRY`'dir. Zaten TR
    sembolü verilirse (`SOLTRY`) yine `SOLTRY` döner.
    """
    sym = str(symbol or "").strip().upper().replace("_", "")
    base = base_asset_of(sym)
    return f"{base}TRY" if base else sym


def sync_fetch_tr_symbols() -> Set[str] | None:
    """Binance TR HTTP endpoint'inden aktif sembolleri çeker."""
    endpoints = [
        "https://www.binance.tr/open/v1/common/symbols",
        "https://api.binance.me/api/v3/exchangeInfo",
    ]
    for url in endpoints:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "scalperagent-v4/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                new_bases = set()
                if "data" in data and isinstance(data["data"], dict) and "list" in data["data"]:
                    # www.binance.tr formatı
                    for item in data["data"]["list"]:
                        b = str(item.get("baseAsset") or "").strip().upper()
                        if b:
                            new_bases.add(b)
                elif "symbols" in data and isinstance(data["symbols"], list):
                    # api.binance.me formatı
                    for item in data["symbols"]:
                        if item.get("status") == "TRADING" and item.get("quoteAsset") == "TRY":
                            b = str(item.get("baseAsset") or "").strip().upper()
                            if b:
                                new_bases.add(b)
                if len(new_bases) >= 50:
                    return new_bases
        except Exception as exc:
            logger.debug("Binance TR sembol listesi çekilemedi (%s): %s", url, exc)

    return None


async def refresh_binance_tr_symbols(force: bool = False) -> Set[str]:
    """Binance TR sembol listesini asenkron günceller."""
    global _CACHE_EXPIRES
    now = time.monotonic()
    if not force and now < _CACHE_EXPIRES and len(_TR_BASE_ASSETS) > 0:
        return get_binance_tr_base_assets()

    fetched = await asyncio.to_thread(sync_fetch_tr_symbols)
    if fetched and len(fetched) > 0:
        with _CACHE_LOCK:
            _TR_BASE_ASSETS.clear()
            _TR_BASE_ASSETS.update(fetched)
            _TR_SYMBOLS.clear()
            _TR_SYMBOLS.update({f"{b}TRY" for b in fetched} | {f"{b}_TRY" for b in fetched})
            _CACHE_EXPIRES = now + _CACHE_TTL_SEC
        logger.info("Binance TR sembol evreni başarıyla güncellendi: %d baz varlık", len(fetched))
    else:
        logger.debug("Binance TR sembol listesi tazeleyemedi, mevcut %d varlık korunuyor", len(_TR_BASE_ASSETS))

    return get_binance_tr_base_assets()
