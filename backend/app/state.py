"""Shared market singletons.

`market` and `analyzer` are created once at import time (same lifecycle the
old app.main module had) and imported by main.py and every router module.

DENETİM 3.4 #41 (2026-09-26) — sembol evreni için TEK kaynak:

Eski sözleşme `config.SYMBOLS` idi, ama `market.symbols` bu listeyi import
anında bir kez kopyalıyordu ve sonradan bağımsız bir ikinci gerçek haline
gelmişti. İki yazar birbirini eziyordu:

* ``startup_services`` DB'den ``runtime_config`` yükler → ``config.SYMBOLS``
  güncellenir → ``market.symbols`` elle atanır (main.py)
* ``bootstrap_symbol_activity`` aynı listeyi kendi ``hot_symbols`` listesiyle
  EZER (runtime.py) — DB yüklemesi sessizce geri alınır
* ``refresh_top_gainer_symbols`` üçüncü bir yazar (config + market birlikte)

``bootstrap_symbol_activity`` bir kez hata fırlatırsa (Binance TR kesintisi)
``market.symbols`` hiç set edilmeden kalabiliyor ve ``strategy_loop`` boş
evrende dönüyordu.

Yeni sözleşme — İKİ ayrı kavram, TEK yazma kapısı:

* ``config.SYMBOLS`` (list[str], BÜYÜK HARF) = **tarama evreni**: kullanıcının
  seçtiği paper giriş sembolleri. Okuyucular: ``_apply_config_update``,
  ``refresh_top_gainer_symbols``, radar/LLM taramaları.
* ``market.symbols`` (list[str], küçük harf) = **akış evreni**: pahalı WS
  kline/depth akışlarının açık tutulduğu semboller. Bu küme
  ``tarama evreni + AÇIK POZİSYONLAR``'dır — listeden düşürülmüş bir
  sembolün açık pozisyonu stop/TP yönetimi için akışta kalmalıdır.
  Okuyucular: ``MarketData.connect/ensure_history/poll_*``.

İkisini birbirinden bağımsız yazmak sessiz yarıştı; bu yüzden ikisi de
``_write_stream_universe()`` üzerinden tek kapıdan yazılır:

* ``apply_symbol_universe(symbols)`` → tam değiştirme (tarama evreni de
  değişir): kullanıcı ayarı, top-gainer aktivasyonu.
* ``extend_stream_universe(extra)`` → yalnız EKLEME: açık pozisyonlar gibi
  tarama evreninin dışına düşen ama akışta tutulması gereken semboller.

Her iki kapı da boş listeyi reddeder ve ``config.SYMBOLS``'u yalnız tam
değiştirme yapar; böylece ``bootstrap_symbol_activity`` hata fırlatırsa bile
evren BOŞ kalmaz (denetim 3.4 #41: eski hâlde ``market.symbols`` hiç set
edilmeden kalabiliyor ve ``strategy_loop`` boş evrende dönüyordu).
"""
import logging

from app.config import config
from app.market_data import MarketData
from app.analyzer import ScalpAnalyzer

logger = logging.getLogger("scalper.state")

market = MarketData(config.SYMBOLS)
analyzer = ScalpAnalyzer(market)


def _normalize(symbols) -> list[str]:
    return list(dict.fromkeys(
        str(symbol).strip().upper() for symbol in (symbols or []) if str(symbol).strip()))


def _reject_empty(normalized: list[str], source: str) -> None:
    """Boş evreni reddet: akış evreninin boşalması ``strategy_loop``'u ve WS
    aboneliklerini ölü bırakır, ``config.SYMBOLS``'un boşalması ise
    mutabakat/rapor yollarını yanlış bakiye göstermeye iter."""
    if normalized:
        return
    raise RuntimeError(
        f"boş sembol evreni reddedildi (kaynak: {source or 'bilinmiyor'}) — "
        "mevcut evren korunuyor")


def apply_symbol_universe(symbols, *, source: str = "") -> list[str]:
    """Sembol evrenini tam olarak değiştir; dönüş: normalize edilmiş liste.

    Hem tarama evreni (``config.SYMBOLS``) hem akış evreni
    (``market.symbols``) güncellenir. Kullanıcı ayarı (``PUT /api/config``)
    ve top-gainer aktivasyonu bu kapıdan geçer; doğrudan
    ``market.symbols = ...`` ataması ``config.SYMBOLS``'u geride bırakır ve
    yeniden başlatmada evrenin geri sarılmasına yol açar.
    """
    normalized = _normalize(symbols)
    _reject_empty(normalized, source)
    market.symbols = [symbol.lower() for symbol in normalized]
    config.SYMBOLS = normalized
    logger.info("sembol evreni güncellendi (kaynak: %s): %d sembol",
                source or "bilinmiyor", len(normalized))
    return normalized


def extend_stream_universe(extra, *, source: str = "") -> list[str]:
    """Akış evrenine sembol EKLE (tarama evrenine dokunmadan).

    Kullanım: açık pozisyonlar. Bir sembol kullanıcı tarafından listeden
    çıkarılmış olsa bile pozisyonu kapanana kadar WS akışı ve mum verisi
    gerekir; ancak yeni giriş taramasına açılmamalıdır.

    DENETİM 3.4 #41: ``market.symbols`` ATANMASI bu fonksiyonda kalır ama
    ``config.SYMBOLS``'a dokunmaz — böylece ``bootstrap_symbol_activity``
    akış kümesini genişletirken kullanıcının kalıcı tarama evrenini geri
    almaz. (Eski hâlde tam tersiydi: kalıcı evren sessizce eziliyordu.)
    """
    additions = _normalize(extra)
    if not additions:
        return [symbol.upper() for symbol in market.symbols]
    current_stream = _normalize(market.symbols)
    merged = list(dict.fromkeys([*current_stream, *additions]))
    # Akış kümesi tarama kümesinden dar olamaz; `apply_symbol_universe`
    # ayrıca `config.SYMBOLS`'u yazdığı için burada elle birleştirilir.
    merged = list(dict.fromkeys([*_normalize(config.SYMBOLS), *merged]))
    _reject_empty(merged, source)
    market.symbols = [symbol.lower() for symbol in merged]
    if set(additions) - set(current_stream):
        logger.info("akış evreni genişletildi (kaynak: %s): +%d sembol (toplam %d)",
                    source or "bilinmiyor", len(set(additions) - set(current_stream)),
                    len(merged))
    return merged

