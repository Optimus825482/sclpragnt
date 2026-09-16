"""BİRLEŞİK RADAR (2026-09-16) — Hız Avcısı + Yükseliş + Radar tespitleri.

NEDEN BU MODÜL VAR:
    Üç sinyal sistemi tek bir karara indirgemek istendi. Keşif şunu gösterdi:

    * "Radar Tespitleri" AYRI bir motor DEĞİLDİR: `monitoring._run_scan`
      doğrudan `velocity.detect_velocity_candidates(5m/15m)` çağırır. Yani
      Radar = Velocity'nin kapı+bildirim+DB koludur.
    * Gerçek ikinci kaynak **Yükseliş**'tir (`app/rising_signals.py`), o da tek
      doğruluk kaynağı olarak `macd_monitor._SNAPSHOT`'ı okur.
    * İki kaynak AYNI 60 sn'lik döngü turunda (`monitoring.py` `_run_scan` sonra
      `_run_rising_scan`) ÇAPRAZ KONTROL OLMADAN çalışır → aynı sembol için
      `monitoring-{sym}` VE `rising-{sym}` olmak üzere İKİ push gönderilirdi.

TASARIM KARARLARI:
    1. **Yeni eşik YOK.** Her kaynak KENDİ kalibre edilmiş kapısını korur
       (velocity ham eşik + panel; yükseliş dip+yakınlık / strength+green).
       Sembol herhangi birini geçerse adaydır → recall kaybı yok.
    2. **Çakışma (confluence) bir GATE değil, bir İŞARETtir.** İki kaynak aynı
       pencere içinde aynı sembolü işaret ediyorsa `confluence=true` olur; bu
       sıralama/raporlama için kullanılır, kapı gevşetmek için DEĞİL.
    3. **Skor ölçekleri karıştırılmaz.** Velocity panel (log, 0-100) ile yükseliş
       `early_score`/`strength×10` FARKLI ölçeklerdir. Bu yüzden sayısal karışım
       (ortalama/ağırlık) YAPILMAZ; `score` tetikleyen kaynağın skoru olur ve
       ham per-kaynak değerler `evidence` içinde ayrı ayrı taşınır.
    4. **macd_monitor DOKUNULMAZ.** Bu modül snapshot'ı yalnız OKUR (satır
       alanları `pre.dip`, `pre_detail.proximity`, `strength`, `green`,
       `early_score`, `sigs`); formül kopyalamaz, import döngüsü yaratmaz.

İKİ GİRİŞ NOKTASI, TEK BİRLEŞİM ÇEKİRDEĞİ:
    * `build_combined_events(...)`   → zaman-farkında KÜMELEME (replay kullanır).
      Aynı sembolde pencere içindeki olaylar tek kümeye iner; kümeler kronolojik
      olay dizisini korur, yani 24h replay "ne zaman, hangi kaynak" sorusunu
      cevaplayabilir.
    * `build_combined_candidates(...)` → sembol başına EN İYİ küme (canlı bildirim
      kullanır; canlıda zaten kaynak başına tek olay gelir).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

# Birleşik zarf tek tag şeması kullanır → tarayıcı push'u aynı sembol için
# birbirini EZER (aynı tag), uygulama-içi liste tek satır gösterir.
RADAR_TAG_PREFIX = "radar"

# Yükseliş tarafında ufuk sabittir (monitoring.py `_build_rising_notification`).
RISING_HORIZON_MINUTES = 5

_SOURCES = ("velocity", "rising")


# ---------------------------------------------------------------------------
# Normalizasyon — journal satırları VE canlı zarflar aynı şekle iner
# ---------------------------------------------------------------------------
def _num(value: Any, default: float | None = None) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out != out:            # NaN
        return default
    return out


def _epoch_seconds(value: Any, default: float | None = None) -> float | None:
    """Zaman alanını epoch SANİYE'ye indirger.

    Journal `created_at` saniye; canlı zarf `detected_at` saniye. Bazı satırlarda
    ms gelmiş olabilir (eski kayıtlar) → 1e11 üstü ms kabul edilir. Yanlış birim
    çakışma penceresini tamamen bozar (sinyaller asla eşleşmez), bu yüzden
    savunmacı davranıyoruz.
    """
    out = _num(value)
    if out is None:
        return default
    if out > 1e11:            # ms -> sn
        out = out / 1000.0
    return out


def normalize_velocity_candidate(raw: dict) -> dict | None:
    """Velocity adayını (journal satırı VEYA canlı zarf) ortak şekle indirger."""
    if not isinstance(raw, dict):
        return None
    symbol = str(raw.get("symbol") or "").replace("_", "").strip().upper()
    if not symbol:
        return None
    score = _num(raw.get("score"), _num(raw.get("velocity_score")))
    raw_score = _num(raw.get("raw_score"), _num(raw.get("velocity_score")))
    detected = _epoch_seconds(raw.get("detected_at"), _epoch_seconds(raw.get("created_at")))
    if score is None and raw_score is None:
        return None
    price = _num(raw.get("price"))
    target = _num(raw.get("target_pct"))
    return {
        "symbol": symbol,
        "source": "velocity",
        "score": score,
        "raw_score": raw_score,
        "price": price,
        "target_pct": target,
        "horizon_minutes": _num(raw.get("horizon_minutes"), 5.0),
        "detected_at": detected,
        "ml_hit_probability": _num(raw.get("ml_hit_probability")),
        "ml_target_pct": _num(raw.get("ml_target_pct")),
        "rr": _num(raw.get("rr")),
        "sl_pct": _num(raw.get("sl_pct")),
    }


def normalize_rising_evidence(raw: dict) -> dict | None:
    """Yükseliş kanıtını (rising_alerts satırı VEYA canlı zarf) ortak şekle indirger."""
    if not isinstance(raw, dict):
        return None
    symbol = str(raw.get("symbol") or "").replace("_", "").strip().upper()
    if not symbol:
        return None
    score = _num(raw.get("score"))
    if score is None:
        # rising_signals.py: early_score yoksa strength × 10 kullanılır.
        early = _num(raw.get("early_score"))
        strength = _num(raw.get("strength"))
        score = early if early is not None else (strength * 10 if strength is not None else None)
    if score is None:
        return None
    price = _num(raw.get("price"))
    target = _num(raw.get("target_pct"))
    return {
        "symbol": symbol,
        "source": "rising",
        "score": score,
        "early_score": _num(raw.get("early_score")),
        "strength": _num(raw.get("strength")),
        "green": _num(raw.get("green")),
        "proximity": _num(raw.get("proximity")),
        "kind": str(raw.get("kind") or ""),
        "price": price,
        "target_pct": target,
        "horizon_minutes": _num(raw.get("horizon_minutes"), float(RISING_HORIZON_MINUTES)),
        "detected_at": _epoch_seconds(raw.get("detected_at"),
                                      _epoch_seconds(raw.get("created_at"))),
    }


# ---------------------------------------------------------------------------
# Birleşim
# ---------------------------------------------------------------------------
def _expected_price(price: float | None, target_pct: float | None) -> float | None:
    if price is None or target_pct is None or price <= 0:
        return None
    return round(price * (1.0 + target_pct / 100.0), 8)


def _fmt_price(value: float | None) -> str:
    if value is None:
        return "—"
    if value >= 1000:
        return f"{value:,.0f}".replace(",", ".")
    if value >= 1:
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return f"{value:.8f}".rstrip("0")


def _cluster_events(items: list[dict], window_sec: int) -> list[list[dict]]:
    """Aynı sembolün olaylarını zaman penceresine göre kümeler (greedy, kronolojik).

    Kural: ardışık iki olay arasındaki boşluk `window_sec`'i aşarsa YENİ küme
    başlar. Zamanı bilinmeyen olaylar ayrılmaz (aynı sembolde birleşir) — canlı
    kullanımda kaynak başına zaten tek olay gelir, bu yüzden davranış değişmez.
    """
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        by_symbol[item["symbol"]].append(item)

    clusters: list[list[dict]] = []
    for _symbol, events in by_symbol.items():
        ordered = sorted(events, key=lambda e: (
            e["detected_at"] is None,
            e["detected_at"] if e["detected_at"] is not None else 0.0,
        ))
        current: list[dict] = []
        for event in ordered:
            if not current:
                current.append(event)
                continue
            prev_t = current[-1]["detected_at"]
            cur_t = event["detected_at"]
            same_window = prev_t is None or cur_t is None or (cur_t - prev_t) <= window_sec
            if same_window:
                current.append(event)
            else:
                clusters.append(current)
                current = [event]
        if current:
            clusters.append(current)
    return clusters


def _merge_cluster(events: list[dict]) -> dict:
    """Kümedeki olayları TEK birleşik adaya indirger (birleşim + çakışma)."""
    sources = sorted({e.get("source") for e in events if e.get("source") in _SOURCES},
                     key=lambda s: _SOURCES.index(s))
    confluence = len(sources) >= 2

    def best(source: str) -> dict | None:
        pool = [e for e in events if e.get("source") == source]
        if not pool:
            return None
        return max(pool, key=lambda e: (e.get("score") if e.get("score") is not None else -1))

    primary = max(
        events,
        key=lambda e: (
            e.get("score") if e.get("score") is not None else -1,
            -_SOURCES.index(e.get("source")) if e.get("source") in _SOURCES else 0,
        ),
    )
    secondary = best("rising" if primary.get("source") == "velocity" else "velocity")

    # GİRİŞ ÇAPASI (2026-09-16): fiyat/hedef/ufuk EN ERKEN olaydan alınır — skor
    # sıralamasından DEĞİL. Eskiden hepsi `primary`den (en yüksek skorlu olay) ±
    # alınıyordu; küme birden çok olayı birleştirdiğinde giriş fiyatı ile giriş
    # ZAMANI farklı olaylardan geliyordu (ör. "0.0764'ten 0.0702 anında gir") ve
    # ölçüm bozuluyordu (negatif MFE: -11.26%, -5.00%). Ticaret İLK sinyalde
    # açılır; ölçüm de onu yansıtmalı.
    entry_event = min(
        events,
        key=lambda e: (
            e["detected_at"] is None,
            e["detected_at"] if e.get("detected_at") is not None else 0.0,
            _SOURCES.index(e.get("source")) if e.get("source") in _SOURCES else 99,
        ),
    )

    score = primary.get("score")
    price = entry_event.get("price")
    if price is None and secondary:
        price = secondary.get("price")
    target_pct = entry_event.get("target_pct")
    if target_pct is None and secondary:
        target_pct = secondary.get("target_pct")
    horizon = entry_event.get("horizon_minutes")
    if horizon is None and secondary:
        horizon = secondary.get("horizon_minutes")
    detected_at = min((e["detected_at"] for e in events if e.get("detected_at") is not None),
                      default=None)

    symbol = primary["symbol"]
    expected = _expected_price(price, target_pct)
    tag = f"{RADAR_TAG_PREFIX}-{symbol}"

    if confluence:
        title = f"🎯📈 RADAR · {symbol}"
    elif primary.get("source") == "velocity":
        title = f"🎯 RADAR · {symbol}"
    else:
        title = f"📈 RADAR · {symbol}"

    parts = [f"{symbol} birleşik radar sinyali"]
    if confluence:
        parts.append("hız + yükseliş kanıtı ÇAKIŞIYOR")
    elif primary.get("source") == "velocity":
        parts.append("hız avcısı tetiklendi")
    else:
        parts.append("yükseliş eğilimi tetiklendi")
    parts.append(f"skor {_fmt_price(score)}")
    if target_pct is not None:
        parts.append(f"hedef %{_fmt_price(target_pct)}")
    if price is not None:
        parts.append(_fmt_price(price))
    if expected is not None:
        parts.append(f"→ {_fmt_price(expected)}")

    vel, ris = best("velocity"), best("rising")
    return {
        "symbol": symbol,
        "sources": sources,
        "confluence": confluence,
        "score": score,
        # Ölçekler farklı olduğu için ham değerler ayrı taşınır (karıştırma yok).
        "scores": {
            "velocity": vel.get("score") if vel else None,
            "rising": ris.get("score") if ris else None,
        },
        "primary_source": primary.get("source"),
        "target_pct": target_pct,
        "price": price,
        "expected_price": expected,
        "horizon_minutes": horizon,
        "detected_at": detected_at,
        "tag": tag,
        "title": title,
        "message": " · ".join(parts),
        "url": f"/charts?symbol={symbol}",
        "paper_only": True,
        "evidence": {
            "velocity": None if vel is None else {
                "score": vel.get("score"), "raw_score": vel.get("raw_score"),
                "target_pct": vel.get("target_pct"),
                "horizon_minutes": vel.get("horizon_minutes"),
                "ml_hit_probability": vel.get("ml_hit_probability"),
                "ml_target_pct": vel.get("ml_target_pct"),
                "rr": vel.get("rr"), "sl_pct": vel.get("sl_pct"),
            },
            "rising": None if ris is None else {
                "score": ris.get("score"), "early_score": ris.get("early_score"),
                "strength": ris.get("strength"), "green": ris.get("green"),
                "proximity": ris.get("proximity"), "kind": ris.get("kind"),
                "target_pct": ris.get("target_pct"),
            },
        },
        # Yalnız `build_combined_events` çıktısında anlamlıdır (replay zaman çizelgesi).
        "events": [
            {"source": e.get("source"), "detected_at": e.get("detected_at"),
             "score": e.get("score"), "price": e.get("price"),
             "target_pct": e.get("target_pct")}
            for e in events
        ],
    }


def build_combined_events(velocity_items: Iterable[dict] = (),
                          rising_items: Iterable[dict] = (),
                          *,
                          confluence_window_sec: int = 1800) -> list[dict]:
    """İki olay akışını zaman-farkında kümelerle BİRLEŞTİRİR (replay çekirdeği).

    Dönüş: skorun ARTAN sırasına göre birleşik adaylar; her aday `events` alanında
    o kümeyi oluşturan kronolojik olayları taşır. Aynı sembolde pencere dışında
    kalan tekrarlar AYRI aday olarak döner — böylece replay, aynı sembolün günde
    birkaç kez sinyal verdiği gerçek davranışı ölçebilir.
    """
    items: list[dict] = []
    for raw in velocity_items:
        item = normalize_velocity_candidate(raw)
        if item is not None:
            items.append(item)
    for raw in rising_items:
        item = normalize_rising_evidence(raw)
        if item is not None:
            items.append(item)

    window = max(1, int(confluence_window_sec))
    merged = [_merge_cluster(cluster) for cluster in _cluster_events(items, window)]
    merged.sort(key=lambda c: (c["score"] if c["score"] is not None else 0), reverse=True)
    return merged


def build_combined_candidates(
    velocity_items: Iterable[dict] = (),
    rising_items: Iterable[dict] = (),
    *,
    confluence_window_sec: int = 1800,
) -> list[dict]:
    """Sembol başına TEK birleşik aday (canlı bildirim yolu).

    `build_combined_events` ile AYNI birleşim çekirdeğini kullanır; farkı, aynı
    sembolün birden çok kümesini en iyi skora göre TEKE indirmesidir. Canlıda
    kaynak başına zaten tek olay gelir, bu yüzden davranış değişmez.

    Birleşim kuralları:
      * Aynı sembol için iki kaynak da varsa ve zaman farkı
        `confluence_window_sec` içindeyse → `confluence=True` (İŞARET, kapı değil).
      * `score` = tetikleyen (skoru yüksek görünen) kaynağın skoru; diğer kaynağın
        skoru `evidence` içinde ayrı tutulur (ölçek karıştırma YOK).
      * `detected_at` = en ERKEN tespit (kaynağın ilk görmesi).
      * Çıktı skorun ARTAN sırasına göre sıralıdır (önce en güçlü aday).
    """
    events = build_combined_events(velocity_items, rising_items,
                                   confluence_window_sec=confluence_window_sec)
    best_by_symbol: dict[str, dict] = {}
    for cluster in events:
        symbol = cluster["symbol"]
        current = best_by_symbol.get(symbol)
        if current is None or (cluster["score"] or 0) > (current["score"] or 0):
            best_by_symbol[symbol] = cluster
    out = list(best_by_symbol.values())
    out.sort(key=lambda c: (c["score"] if c["score"] is not None else 0), reverse=True)
    return out


def build_unified_envelope(candidate: dict) -> dict:
    """Birleşik adayı TEK tip bildirim zarfına çevir (Aşama 2 teslimatı bunu gönderir).

    Sözleşme notları:
      * `tag` tek şema → tarayıcı aynı sembol için push'ları ezer, çift bildirim olmaz.
      * `score` auto_paper'ın `min_score` kapısına giren değerdir (tetikleyen kaynak).
      * `sources`/`confluence`/`evidence` istemci ve rapor için ek bağlamdır.
    """
    return {
        "symbol": candidate["symbol"],
        "message": candidate["message"],
        "title": candidate["title"],
        "url": candidate["url"],
        "tag": candidate["tag"],
        "score": candidate["score"],
        "target_pct": candidate["target_pct"],
        "price": candidate["price"],
        "expected_price": candidate["expected_price"],
        "horizon_minutes": candidate["horizon_minutes"],
        "detected_at": candidate["detected_at"],
        "sources": candidate["sources"],
        "confluence": candidate["confluence"],
        "primary_source": candidate["primary_source"],
        "evidence": candidate["evidence"],
        "paper_only": True,
        # `updated` radar sözleşmesinde "BEKLIYOR güncellemesi" anlamına gelir;
        # birleşik motor taze üretim yapar → her zaman False.
        "updated": False,
        "notification_key": f"radar-{candidate['symbol']}",
    }
