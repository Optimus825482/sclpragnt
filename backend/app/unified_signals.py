"""BİRLEŞİK SİNYAL MOTORU (2026-09-17) — tek tespit, tek bildirim.

MİMARİ:
    Radarda üç BAĞIMSIZ tespit algoritması vardı ve her biri KENDİ bildirimini
    atıyordu (velocity radar push'u, rising push'u, MACD jump push'u). Kullanıcı
    kararı: uygulama farklı fonksiyonlardan farklı bildirimler GÖNDERMESİN;
    tüm algoritmaların en iyi yönleri TEK füzyon skorunda birleşsin ve en hızlı
    + güçlü yükselme potansiyeline sahip semboller TEK bildirimle önceden
    haber verilsin.

    Bu modül FÜZYON KATMANIDIR: tespit algoritmalarının ÇIKTILARINI birleştirir;
    kendi başına hiçbir veri çekmez. Tek doğruluk kaynakları değişmez:
      * velocity  → `routers/velocity.py` aday satırları (panel skoru)
      * MACD jump → `routers/macd_monitor.py` `_SNAPSHOT` (jump 0-100)
      * MACD erken→ aynı snapshot (`early_score` / dip kapısı / strength)

    `routers/monitoring.py` burayı ÇAĞIRIR (modül seviyesinde; döngü yok — bu
    modül yalnız `macd_monitor` ve `config` import eder). `macd_monitor` da
    hızlı-yol bildirimi için `monitoring.unified_fast_notify`'yi TEMBEL import
    eder → tek yönlü bağımlılık korunur.

REPLAY PARİTESİ:
    `fusion_score` SAF fonksiyondur; `scripts/combined_radar_replay_24h.py`
    unified akışı için AYNI fonksiyonu import eder. Canlı ve replay aynı
    füzyon formülünü kullanır — aksi halde replay başka bir motoru ölçerdi.

AKTİVASYON:
    `config.UNIFIED_SIGNALS_ENABLED` (varsayılan AÇIK). Kapalıysa tüm çağıran
    taraf eski davranışa döner.
"""
from __future__ import annotations

import logging
import time

from app.config import config
from app.routers import macd_monitor as _macd

logger = logging.getLogger("scalper.unified")

# Kaynak etiketleri (bildirim mesajı + rapor sütunu)
SOURCE_VELOCITY = "velocity"   # radar hız/volatilite taraması
SOURCE_JUMP = "jump"           # MACD sıçrama (kırılım) adayı
SOURCE_EARLY = "early"         # MACD erken sıçrama (dip dönüşü + yakınlık)
SOURCE_RISING = "rising"       # MACD güç/yeşil-TF yükseliş eğilimi

SOURCE_LABELS = {
    SOURCE_VELOCITY: "RADAR",
    SOURCE_JUMP: "MACD SIRÇRAMA",
    SOURCE_EARLY: "ERKEN SIRÇRAMA",
    SOURCE_RISING: "YÜKSELİŞ",
}

# Son birleşik bildirim zamanı (symbol → wall-clock epoch). Push tekilleştirme
# ve `_rising_deliver` bastırması bu haritaya bakar; radar turu başına temizlenen
# `_unified_pushed_symbols`'tan FARKLI olarak tur SIRASINDA korunur.
_unified_notified_at: dict[str, float] = {}
# Sembolün SON bildirim skoru (sinyal terfisi kapısı için; 2026-09-19).
_unified_notified_score: dict[str, float] = {}


def reset_state_for_tests() -> None:
    """Test izolasyonu: modül durumunu sıfırla (üretimde çağrılmaz)."""
    _unified_notified_at.clear()
    _unified_notified_score.clear()


def note_notified(symbol: str, at: float | None = None, score: float | None = None) -> None:
    """Birleşik bildirim gönderildi — çapraz bastırma için kaydet.

    ``score`` verilirse sembolün SON bildirim skorunu da saklar; sinyal
    terfisi (upgrade) kapısı bununla karşılaştırır: yeni sinyal öncekinden
    belirgin güçlüyse (config.UNIFIED_UPGRADE_MIN_GAIN) bastırma yerine
    güncelleme push'u izinli olur.
    """
    sym = str(symbol or "").upper()
    if sym:
        _unified_notified_at[sym] = float(at if at is not None else time.time())
        if score is not None:
            try:
                _unified_notified_score[sym] = float(score)
            except (TypeError, ValueError):
                pass


def last_notified_score(symbol: str) -> float | None:
    """Sembolün son bildirim skorunu döndürür (sinyal terfisi için)."""
    return _unified_notified_score.get(str(symbol or "").upper())


def should_upgrade_signal(symbol: str, new_score: float,
                          min_gain: float | None = None) -> bool:
    """Sinyal terfisi kapısı (kullanıcı iyileştirmesi 2026-09-19).

    Erken sinyal sonrası cooldown'da gelen güçlü teyit (jump/rising) eskiden
    tamamen yutuluyordu. Artık yeni skor, son bildirim skorundan
    ``min_gain`` (varsayılan config.UNIFIED_UPGRADE_MIN_GAIN = 10) kadar
    yüksekse "sinyal güçlendi" güncellemesi izinli sayılır.
    """
    sym = str(symbol or "").upper()
    prev = _unified_notified_score.get(sym)
    if prev is None:
        return True  # önceki kayıt yok → bastırma kapısı zaten geçmez
    gain = float(min_gain if min_gain is not None
                 else getattr(config, "UNIFIED_UPGRADE_MIN_GAIN", 10.0))
    return float(new_score) >= float(prev) + gain


def recently_notified(symbol: str, ttl_sec: float | None = None) -> bool:
    """Sembole yakın zamanda birleşik bildirim gitmiş mi?

    `ttl_sec` verilmezse hızlı-yol cooldown'u (`UNIFIED_FAST_COOLDOWN_SEC`)
    kullanılır. Rising/MACD yolları kendi bildirimlerini buna göre bastırır —
    kullanıcıya aynı sembol için ikinci bir push gitmez.
    """
    sym = str(symbol or "").upper()
    last = _unified_notified_at.get(sym)
    if last is None:
        return False
    ttl = float(ttl_sec if ttl_sec is not None
                else getattr(config, "UNIFIED_FAST_COOLDOWN_SEC", 1800))
    return (time.time() - last) < ttl


def enabled() -> bool:
    """Birleşik sinyal motoru aktif mi? (tek kapı — tüm çağıranlar bunu sorar)"""
    return bool(getattr(config, "UNIFIED_SIGNALS_ENABLED", False))


# ---------------------------------------------------------------------------
# SAF füzyon (replay ile ORTAK — imzayı değiştirirsen replay'i de güncelle)
# ---------------------------------------------------------------------------
def fusion_score(components: dict[str, float | None]) -> tuple[float, list[str]]:
    """Kaynak skorlarını TEK 0-100 füzyon skoruna indirger.

    components: {kaynak: 0-100 skor veya None}. None/<=0 bileşen yok sayılır;
    ağırlıklar KALAN kaynaklar üzerinden yeniden normalize edilir (yani MACD
    evreninde olmayan sembolün skoru velocity paneliyle eşit kalır, eksik kaynak
    cezalandırmaz). 2+ kaynak aynı sembolde hemfikirse sinerji çarpanı
    (`UNIFIED_SYNERGY_BONUS`) uygulanır — kanıtlanmış kesişim üstünlüğünün
    (confluence lift) füzyondaki karşılığı budur.

    Dönüş: (füzyon skoru 0-100, katkı veren kaynak etiketleri sıralı).
    """
    weights = {
        SOURCE_VELOCITY: float(getattr(config, "UNIFIED_W_VELOCITY", 0.50)),
        SOURCE_JUMP: float(getattr(config, "UNIFIED_W_JUMP", 0.25)),
        SOURCE_EARLY: float(getattr(config, "UNIFIED_W_EARLY", 0.25)),
        SOURCE_RISING: float(getattr(config, "UNIFIED_W_RISING", 0.25)),
    }
    active: list[tuple[str, float, float]] = []
    for source, value in components.items():
        if value is None:
            continue
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        if v <= 0:
            continue
        active.append((str(source), min(100.0, v), weights.get(str(source), 0.0)))
    if not active:
        return 0.0, []
    total_weight = sum(w for _, _, w in active)
    if total_weight <= 0:
        # Ağırlıklar sıfırlanmışsa düz ortalama — fonksiyon asla patlamasın.
        score = sum(v for _, v, _ in active) / len(active)
    else:
        score = sum(v * w for _, v, w in active) / total_weight
    if len(active) >= 2:
        score *= float(getattr(config, "UNIFIED_SYNERGY_BONUS", 1.15))
    return round(min(100.0, score), 1), [s for s, _, _ in active]


# ---------------------------------------------------------------------------
# MACD bileşenleri (snapshot'tan SALT OKUMA — rising_signals deseni)
# ---------------------------------------------------------------------------
def macd_components(symbol: str) -> tuple[dict[str, float | None], dict]:
    """Sembolün MACD füzyon bileşenleri + bağlam sözlüğü.

    Bileşenler (hepsi 0-100 panel ölçeğinde):
      * jump   → sıçrama skoru (`row.jump`; eşik geçmiş ARM durumu değil,
                 anlık skor — füzyon güç ister, bayrak değil)
      * early  → erken sıçrama skoru (`row.early_score`; dip dönüşü + yakınlık)
      * rising → yükseliş eğilimi (`row.strength` 0-10 → ×10)

    Bağlam (bildirim mesajı ve UI için): green, tier, pre, cvd, proximity.
    Snapshot yoksa/sembol evrende değilse boş döner — eksik kaynak ceza değil.
    """
    sym = str(symbol or "").upper()
    out: dict[str, float | None] = {}
    context: dict = {}
    if not sym:
        return out, context
    snapshot = _macd._SNAPSHOT or {}
    row = (snapshot.get("symbols") or {}).get(sym)
    if not row:
        return out, context
    try:
        jump = row.get("jump")
        if jump is not None:
            out[SOURCE_JUMP] = float(jump)
        early = row.get("early_score")
        if early is not None:
            out[SOURCE_EARLY] = float(early)
        strength = row.get("strength")
        if strength is not None:
            out[SOURCE_RISING] = round(float(strength) * 10.0, 1)
    except (TypeError, ValueError):
        pass
    pre_detail = row.get("pre_detail") or {}
    context = {
        "green": row.get("green_count") if "green_count" in row else _macd_green_count(row),
        "tier": row.get("tier"),
        "dip": bool((row.get("pre") or {}).get("dip")),
        "proximity": pre_detail.get("proximity"),
        "buy_dominant": bool((row.get("cvd") or {}).get("buy_dominant")),
    }
    return out, context


def _macd_green_count(row: dict) -> int:
    """Snapshot satırındaki yeşil TF sayısı (rising_signals.green_count ile aynı)."""
    tfs = row.get("tfs") or {}
    count = 0
    for tf in _macd.TF_LIST:
        cell = tfs.get(tf)
        if cell and bool(cell.get("green")):
            count += 1
    return count


# ---------------------------------------------------------------------------
# Radar adaylarını zenginleştir + füzyon-tek adaylar
# ---------------------------------------------------------------------------
def enrich_candidates(candidates: list[dict], min_fusion_score: float | None = None) -> list[dict]:
    """Velocity adaylarına birleşik füzyon alanlarını işare; MACD-tek adayları üret.

    Her adaya şunlar yazılır (mevcut alanlar KORUNUR — salt ekleme):
      * `unified_score`  — füzyon skoru (0-100)
      * `unified_sources`— katkı veren kaynak etiketleri (["velocity", "jump", ...])
      * `macd_context`   — bildirim mesajı için MACD bağlamı

    MACD-TEK adaylar: radar velocity kapısını GEÇEMEDİĞİ halde MACD bileşenleri
    (jump/erken/yükseliş) güçlü olan semboller. `min_fusion_score`
    (`UNIFIED_FUSION_MIN_SCORE`) üzerindeki füzyon skoruyla aday listesine
    girerler; `monitoring._notify` bunları `unified_pass` kapısıyla kabul eder.
    Bunlar "radar görmesinin üzerinden 60 sn beklemek yerine MACD öncüsüyle
    önceden bildirim" hedefinin ta kendisidir.
    """
    min_fusion = float(min_fusion_score if min_fusion_score is not None
                       else getattr(config, "UNIFIED_FUSION_MIN_SCORE", 60))
    seen: set[str] = set()
    for candidate in candidates:
        sym = str(candidate.get("symbol") or "").upper()
        if not sym:
            continue
        seen.add(sym)
        panel = candidate.get("panel_score")
        if panel is None:
            panel = candidate.get("velocity_score")
        components, context = macd_components(sym)
        components.setdefault(SOURCE_VELOCITY, float(panel) if panel is not None else None)
        score, sources = fusion_score(components)
        candidate["unified_score"] = score
        candidate["unified_sources"] = sources
        candidate["macd_context"] = context

    fusion_only: list[dict] = []
    if not enabled():
        return fusion_only
    snapshot = _macd._SNAPSHOT or {}
    symbols = snapshot.get("symbols") or {}
    universe = snapshot.get("universe") or list(symbols)
    for sym in universe:
        sym = str(sym or "").upper()
        if not sym or sym in seen:
            continue
        row = symbols.get(sym) or {}
        if not row:
            continue
        components, context = macd_components(sym)
        if not components:
            continue
        score, sources = fusion_score(components)
        if score < min_fusion:
            continue
        price = row.get("last")
        try:
            price_f = float(price) if price is not None else None
        except (TypeError, ValueError):
            price_f = None
        from app.routers.velocity import dynamic_target_pct
        target = dynamic_target_pct(
            score=score,
            base_target_pct=float(getattr(config, "RISING_TARGET_PCT", 2.2) or 2.2),
            panel_score=True,
        )
        fusion_only.append({
            "symbol": sym,
            "velocity_score": 0.0,
            "unified_score": score,
            "unified_sources": sources,
            "unified_pass": True,     # _notify: ham skor kapısını atlar
            "source": "fusion",
            "macd_context": context,
            "price": price_f,
            "target_pct": target,
            "horizon_minutes": 5,
            "mode": "unified",
            "upside_rank": 0.0,
            "passes": False,
            # Journal anahtarı: `save_velocity_candidates` + rapor eşleşmesi
            # (±60 sn + hedef) ve MFE ölçümü radar adaylarıyla AYNI yoldan
            # geçer. "uni-" öneki `vel-` ayrıştırıcısında 5dk varsayılır.
            "candidate_id": f"uni-5dk-{int(time.time() * 1000)}-{sym}",
        })
    fusion_only.sort(key=lambda c: (-float(c.get("unified_score") or 0), str(c.get("symbol"))))
    return fusion_only


def build_fusion_candidate(symbol: str, kind: str,
                           velocity_candidate: dict | None = None) -> dict | None:
    """Hızlı yol: tek sembol için birleşik aday üret (MACD tetiklemesiyle).

    `kind`: "jump" | "early" — hangi MACD alarmlarının tetiklediği (kaynak
    etiketine eklenir; bildirim mesajında "ERKEN SIRÇRAMA öncüsü" görünür).
    Füzyon skoru `UNIFIED_FAST_MIN_SCORE` altındaysa None döner (bildirim yok).
    """
    sym = str(symbol or "").upper()
    if not sym:
        return None
    components, context = macd_components(sym)
    if not components:
        return None
    if velocity_candidate:
        panel = velocity_candidate.get("panel_score") or velocity_candidate.get("velocity_score")
        if panel is not None:
            try:
                components[SOURCE_VELOCITY] = float(panel)
            except (TypeError, ValueError):
                pass
    score, sources = fusion_score(components)
    if score < float(getattr(config, "UNIFIED_FAST_MIN_SCORE", 55)):
        return None
    if kind in (SOURCE_JUMP, SOURCE_EARLY) and kind not in sources:
        sources = sources + [kind]
    snapshot = _macd._SNAPSHOT or {}
    row = (snapshot.get("symbols") or {}).get(sym) or {}
    price = row.get("last") or (velocity_candidate or {}).get("price")
    try:
        price_f = float(price) if price is not None else None
    except (TypeError, ValueError):
        price_f = None
    if velocity_candidate and velocity_candidate.get("target_pct"):
        target = float(velocity_candidate.get("target_pct"))
    else:
        from app.routers.velocity import dynamic_target_pct
        target = dynamic_target_pct(
            score=score,
            base_target_pct=float(getattr(config, "RISING_TARGET_PCT", 2.2) or 2.2),
            panel_score=True,
        )
    return {
        "symbol": sym,
        "unified_score": score,
        "unified_sources": sources,
        "unified_pass": True,
        "trigger": kind,
        "source": "fusion",
        "macd_context": context,
        "price": price_f,
        "target_pct": target,
        "horizon_minutes": 5,
        "mode": "unified",
        "upside_rank": 0.0,
        "passes": False,
    }


def sources_text(sources: list[str] | None) -> str:
    """Kaynak etiketlerini kullanıcı dostu metne çevir ("RADAR + ERKEN SIRÇRAMA")."""
    labels = [SOURCE_LABELS.get(str(s), str(s)) for s in (sources or []) if s]
    return " + ".join(labels) if labels else "RADAR"
