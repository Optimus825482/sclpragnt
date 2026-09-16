"""Yükseliş sinyalleri (R1, 2026-09-14) — MACD MONITOR'ün kanıtlanmış öncüleri
radara taşınır.

NEDEN: `monitoring/page.tsx` "YÜKSELİŞ EĞİLİMİ ADAYLARI" panelini istemci
tarafında `/api/macd-monitor` yanıtından türetiyordu → sunucuda tespit yok,
bildirim yok, kanıt/ölçüm yok. Bu modül tespiti sunucuya taşır.

KANIT (macd_monitor.py:152-167; outputs/erken_oncu_replay_kanit.md):
  * `approach`      → OOS lift −0.082 (isabet 0.33) → kapıda YOK, tanımlayıcı.
  * `m1_breakout`   → OOS lift −0.094 (isabet 0.40) → kapıda YOK, tanımlayıcı.
  * `dip` tek başına→ 0.76-0.86× (baseline ALTI) → negatif EV.
  * `dip` + 20-bar zirveye ≤1.5 ATR yakınlık → **1.47-1.67× lift (n≈16k)**.
Bu yüzden AKTİVE EDİLEN tek reçete BİRLEŞİK kapıdır: `pre.dip` (snapshot'ta
`_dip_gate(turn, gap)` uygulanmış halde gelir → dip-turn AND yakınlık).

MİMARİ: `macd_monitor.py` DEĞİŞTİRİLMEZ (referans implementasyon). Tek doğruluk
kaynağı onun snapshot'ıdır; formül KOPYALANMAZ, okunur. `macd_monitor` bu modülü
import etmez → döngü (cycle) yok.
"""
from __future__ import annotations

import logging
import time

from app.config import config
from app.routers import macd_monitor as _macd

logger = logging.getLogger("scalper.rising")

KIND_EARLY = "erken"          # dip + yakınlık (kırılım ÖNCESİ, asıl MACD gücü)
KIND_STRENGTH = "yukselis"    # güç + yeşil TF uyumu (mevcut panelin sunucuya taşınmış hali)

# --- Histerezis durumu (MACD'nin `_early_alerted_at` / `pre_key` deseni) -----
# symbol → son ateşlenen öncü kümesi. Yalnız 0→1 KENARINDA veya kümeye YENİ
# öncü eklendiğinde yeniden ateşlenir; aynı kümenin sürmesi alarm yorgunluğu yapar.
_rising_last_key: dict[str, tuple] = {}
# symbol → son ateşleme zamanı (monotonik saat; duvar saati adımlarına dayanıklı).
_rising_alerted_at: dict[str, float] = {}
_stale_warned = False


def reset_state_for_tests() -> None:
    """Test izolasyonu: modül durumunu sıfırla (üretimde çağrılmaz)."""
    global _stale_warned
    _rising_last_key.clear()
    _rising_alerted_at.clear()
    _stale_warned = False


# ---------------------------------------------------------------------------
# Snapshot sağlığı
# ---------------------------------------------------------------------------
def snapshot_age_sec(now: float | None = None) -> float | None:
    """MACD snapshot'ının yaşı (sn). `generated_at` yoksa None."""
    generated = float((_macd._SNAPSHOT or {}).get("generated_at") or 0.0)
    if generated <= 0:
        return None
    return max(0.0, (now if now is not None else time.time()) - generated)


def rising_is_stale(now: float | None = None) -> bool:
    """Snapshot bayat/bomboş mu? True → tarama SESSİZCE atlanır.

    MACD döngüsü kapalı ya da çökmüşse `_SNAPSHOT` boş/eski kalır; bu durumda
    yükseliş sinyali ÜRETMEMEK gerekir (uydurma sinyal = yanlış bildirim).
    """
    global _stale_warned
    age = snapshot_age_sec(now)
    limit = float(getattr(config, "RISING_SNAPSHOT_MAX_AGE_SEC", 120) or 120)
    stale = age is None or age > limit
    if stale and not _stale_warned:
        _stale_warned = True
        logger.warning(
            "Yükseliş taraması atlandı: MACD snapshot yok/bayat (yaş=%s sn, limit=%.0f sn). "
            "MACD MONITOR döngüsü çalışıyor mu?", "—" if age is None else f"{age:.0f}", limit)
    elif not stale and _stale_warned:
        _stale_warned = False  # snapshot geri geldi → sonraki bayatlıkta yeniden uyar
    return stale


def green_count(row: dict) -> int:
    """Yeşil (hist>0) zaman dilimi sayısı — snapshot `tfs` hücrelerinden.

    İstemci `extractRisingCandidates` ile AYNI hesap (her TF'te `cell.green`),
    ama artık sunucuda: tek doğruluk kaynağı.
    """
    tfs = row.get("tfs") or {}
    count = 0
    for tf in _macd.TF_LIST:
        cell = tfs.get(tf)
        if cell and bool(cell.get("green")):
            count += 1
    return count


# ---------------------------------------------------------------------------
# Saf kararlar (unit-test edilebilir)
# ---------------------------------------------------------------------------
def strength_qualifies(strength, green) -> bool:
    """YÜKSELİŞ sınıfı eşiği: GÜÇ ≥ RISING_MIN_STRENGTH VE yeşil ≥ RISING_MIN_GREEN."""
    try:
        if strength is None or green is None:
            return False
        return (float(strength) >= float(config.RISING_MIN_STRENGTH)
                and int(green) >= int(config.RISING_MIN_GREEN))
    except (TypeError, ValueError):
        return False


def rising_edge_trigger(prev_key, cur_key, first_observation: bool = False) -> bool:
    """Yeniden ateşleme kenarı — `macd_monitor._early_trigger` ile aynı mantık.

    * `first_observation` (satırda önceki küme yok: süreç yeni başladı / sembol
      evrene yeni girdi) → **sessiz ARM**, tetik YOK. Aksi halde her restart'ta
      aynı saniyede toplu bildirim üretilirdi.
    * Öncü yoktu, şimdi var (0→1) → tetik.
    * Kümeye YENİ bir öncü/etiket eklendi → tetik (bilgi gerçekten yeni).
    * Aynı kümenin sürmesi → tetik YOK.
    """
    if first_observation:
        return False
    if not cur_key:
        return False
    if not prev_key:
        return True
    return bool(set(cur_key) - set(prev_key or ()))


def cooldown_active(symbol: str, now: float) -> bool:
    """Sembol cooldown'ı dolmadı mı? (`RISING_COOLDOWN_SEC`)"""
    last = _rising_alerted_at.get(symbol)
    if last is None:
        return False
    return (now - last) < float(getattr(config, "RISING_COOLDOWN_SEC", 1800) or 0)


def last_key(symbol: str) -> tuple | None:
    """Sembolün son GÖRÜLEN öncü kümesi (yoksa None → ilk gözlem)."""
    return _rising_last_key.get(str(symbol or ""))


def observe(candidate: dict) -> None:
    """Öncü kümesini COOLDOWN BAŞLATMADAN kaydet (sessiz arm).

    İlk gözlemde (süreç yeni başladı / sembol evrene yeni girdi) kullanılır:
    her restart'ta aynı saniyede toplu bildirim üretilmesini engeller ama
    sinyalin "görülmüş" sayılmasını sağlar.
    """
    symbol = str(candidate.get("symbol") or "")
    key = signal_key(candidate)
    if symbol and key:
        _rising_last_key[symbol] = key


def should_fire(candidate: dict, now: float) -> bool:
    """Aday YENİ bilgi taşıyor mu? (histerezis + cooldown)"""
    symbol = str(candidate.get("symbol") or "")
    key = signal_key(candidate)
    if not key:
        return False
    prev = _rising_last_key.get(symbol)
    if cooldown_active(symbol, now):
        return False
    return rising_edge_trigger(prev, key, first_observation=(prev is None))


def mark_fired(candidate: dict, now: float) -> None:
    """Ateşlenen sinyalin durumunu kaydet (cooldown + son küme)."""
    symbol = str(candidate.get("symbol") or "")
    _rising_last_key[symbol] = signal_key(candidate)
    _rising_alerted_at[symbol] = now


def signal_key(candidate: dict) -> tuple:
    """Öncü KİMLİK imzası: hangi sinyaller açık? (sıralı tuple → determinizm)

    Açık bir öncü kümesi değişmediği sürece yeni bilgi yoktur. Yalnız
    `approach`/`m1` gibi TANIMLAYICI alanlar değil, kapıyı oluşturan sinyaller
    (`dip`, `transition`, `break`, `buy_dominant`) imzaya girer.
    """
    signals = candidate.get("signals") or {}
    keys = []
    if signals.get("dip"):
        keys.append("dip")
    if signals.get("transition"):
        keys.append("transition")
    if signals.get("break5"):
        keys.append("break5")
    if signals.get("break15"):
        keys.append("break15")
    if signals.get("buy_dominant"):
        keys.append("buy_dominant")
    if candidate.get("kind") == KIND_STRENGTH:
        keys.append("strength")
    return tuple(sorted(keys))


# ---------------------------------------------------------------------------
# Tespit
# ---------------------------------------------------------------------------
def _signals_from_row(row: dict) -> dict:
    """Snapshot satırından okunabilir sinyal sözlüğü (kapı + tanımlayıcılar)."""
    pre = row.get("pre") or {}
    detail = row.get("pre_detail") or {}
    sigs = row.get("sigs") or {}
    cvd = row.get("cvd") or {}
    m5 = sigs.get("5m") or {}
    m15 = sigs.get("15m") or {}
    return {
        # AKTİF kapı sinyali (dip-turn AND yakınlık; snapshot'ta hazır)
        "dip": bool(pre.get("dip")),
        # TANIMLAYICI (kanıtta ters yönlü — aktive EDİLMEZ, yalnız gösterim)
        "approach": bool(pre.get("approach")),
        "m1": bool(pre.get("m1")),
        "pre_any": bool(row.get("pre_any")),
        "proximity": detail.get("proximity"),
        "gap_atr": detail.get("gap_atr"),
        "dip_hist": detail.get("dip_hist"),
        "dip_delta": detail.get("dip_delta"),
        # bağlam
        "transition": bool(detail.get("transition")),
        "squeeze_now": bool(detail.get("squeeze_now")),
        "expand_now": bool(detail.get("expand_now")),
        "break5": bool(m5.get("break")),
        "break15": bool(m15.get("break")),
        "buy_dominant": bool(cvd.get("buy_dominant")),
    }


def _candidate(symbol: str, row: dict, kind: str) -> dict:
    early = row.get("early_score")
    strength = row.get("strength")
    # `score`: otonom/bildirim kapılarının beklediği 0-100 panel benzeri değer.
    #  ERKEN  → `early_score` (tanımlayıcı bileşim, zaten 0-100).
    #  YÜKSELİŞ → `strength` 0-10 ölçeğinde olduğundan ×10 ile 0-100'e ölçeklenir.
    #  NOT: bu ölçekleme YALNIZ eşik karşılaştırması içindir; TP kademesi
    #  esnetilmez (bkz. plan §4/R3 — ölçek karışımı bilinçli olarak yapılmaz).
    if kind == KIND_EARLY:
        score = float(early) if early is not None else 0.0
    else:
        score = round(float(strength) * 10.0, 1) if strength is not None else 0.0
    return {
        "symbol": symbol,
        "kind": kind,
        "score": score,
        "early_score": early,
        "strength": strength,
        "green": green_count(row),
        "tier": row.get("tier"),
        "signals": _signals_from_row(row),
        "target_pct": float(getattr(config, "RISING_TARGET_PCT", 2.0) or 2.0),
        "tf": "5m",
        "source": "macd_snapshot",
    }


def detect_rising_candidates(now: float | None = None) -> list[dict]:
    """Snapshot'tan yükseliş/erken adaylarını seç (SALT OKUNUR, ağ isteği YOK).

    Öncelik: bir sembol hem ERKEN hem YÜKSELİŞ koşulunu sağlıyorsa ERKEN seçilir
    (daha spesifik ve kırılımdan önce). Sıralama: skor desc, sonra yeşil TF desc.
    """
    if not bool(getattr(config, "RISING_SIGNALS_ENABLED", True)):
        return []
    if rising_is_stale(now):
        return []
    snapshot = _macd._SNAPSHOT or {}
    symbols = snapshot.get("symbols") or {}
    universe = snapshot.get("universe") or list(symbols)
    out: list[dict] = []
    for symbol in universe:
        row = symbols.get(symbol) or {}
        if not row:
            continue
        if bool(getattr(config, "RISING_EARLY_ENABLED", True)) and bool((row.get("pre") or {}).get("dip")):
            out.append(_candidate(symbol, row, KIND_EARLY))
        elif bool(getattr(config, "RISING_STRENGTH_ENABLED", True)) \
                and strength_qualifies(row.get("strength"), green_count(row)):
            out.append(_candidate(symbol, row, KIND_STRENGTH))
    out.sort(key=lambda item: (-float(item.get("score") or 0.0), -int(item.get("green") or 0),
                               str(item.get("symbol"))))
    return out


def rising_summary_payload() -> dict:
    """Panel/state için hafif özet (bildirim ÜRETMEZ)."""
    candidates = detect_rising_candidates()
    return {
        "enabled": bool(getattr(config, "RISING_SIGNALS_ENABLED", True)),
        "stale": rising_is_stale(),
        "snapshot_age_sec": (lambda age: None if age is None else round(age, 1))(snapshot_age_sec()),
        "count": len(candidates),
        "candidates": candidates,
        "thresholds": {
            "min_strength": float(getattr(config, "RISING_MIN_STRENGTH", 9.8)),
            "min_green": int(getattr(config, "RISING_MIN_GREEN", 5)),
            "dip_gap_atr": float(getattr(config, "RISING_DIP_GAP_ATR", 1.5)),
            "cooldown_sec": float(getattr(config, "RISING_COOLDOWN_SEC", 1800)),
        },
    }
