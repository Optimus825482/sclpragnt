"""Kök pytest yapılandırması / paylaşımlı fixture'lar (backend/).

2026-10-07 denetimi (P2-10/3): `backend/conftest.py` YOKTU. Bu dosya
oluşturulmadan önce 113 test dosyasının neredeyse tamamı `unittest.TestCase`
tabanlıdır ve kurulumu kendi `setUp`/`tearDown`'ında yapar.

NEDEN MİNİMAL?
-------------
Denetim, "tekrarlanan event-loop / temp-db / client kurulumu" için ortak
fixture arandı. Bulgular:
  1. Event loop: 49 dosya `unittest.IsolatedAsyncioTestCase` kullanır (pytest
     bunu native koşar; dışarıdan bir loop fixture'ı GEREKSİZ). Kalan senkron
     testler gerektiğinde `asyncio.run(...)` çağırır — paylaşılabilir bir
     kurulum yok.
  2. Temp DB / sahte bağlantı: ~13 dosya `app.database._run_db`'yi yamalar ama
     HER BİRİ kendi sahte bağlantı sınıfını (`_RoutedConn`/`_RecordingConn`/
     `_ReconcileConn` ...) SQL'e göre farklı cevaplarla tanımlar. Ortak bir
     fixture'a çekmek tek tek farklı olan bu sınıfları tek şemaya zorlar →
     gerçek ama BÜYÜK ve riskli bir refactor; bu denetimde ERTELENDİ.
  3. TestClient / gerçek HTTP: pytest suite'inde `TestClient`/`AsyncClient`
     kullanan hiçbir test YOK (bkz. rapor) — dolayısıyla client fixture'ı da
     kimse kullanmıyor.
  4. `sys.path.insert` / `ROOT = parents[1]` ~68 dosyada tekrarlanıyor ama
     `pytest.ini` zaten `pythonpath = .` verir; bu kalan boilerplate kozmetiktir
     ve refactor riski faydasından büyüktür.

Bu yüzden burada YALNIZCA, tüm suite için gerçekten yararlı ve güvenli olan
TEK bir autouse fixture tanımlanır: ortam değişkeni (`os.environ`) izolasyonu.
`test_w18_runtime_residual.py` gibi testler `os.environ.pop("CORS_ORIGINS")`
yapıp değeri GERİ KOYMAZ; bu tür sızıntılar testleri KAYNAK/varış sırasına
bağımlı hale getirir. Fixture her testten sonra ortamı başa döndürür.
"""
import os
from unittest.mock import AsyncMock

import pytest


@pytest.fixture(autouse=True)
def _isolate_environment():
    """Her testten sonra `os.environ`'ı başlangıç durumuna döndür.

    Bir test `os.environ`'ı değiştirip geri koymazsa (ör. `CORS_ORIGINS`
    pop'layıp restore etmezse) sonraki testler kirlenmiş ortamla koşar. Bu
    fixture her test için ortamı anlık görüntüler ve test bittikten sonra
    (hata dâhil) geri yükler → sızıntı testleri sıraya bağımlı yapamaz.

    Not: `unittest.TestCase` metotları pytest tarafından koşulduğunda da
    autouse fixture'lar uygulanır (denetimde doğrulandı).
    """
    saved = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


# Üretim kopyasının CANLI içeriğine bağlı testleri ayıran opt-in fixture.
#
# 2026-10-16: DATABASE_URL bir üretim kopyasına işaret ettiğinde auto_paper /
# yürütme testleri 12 yerde kırılıyordu: `llm_settings.auto_paper_settings`
# (min_score=85, reopen kapalı ...) kod varsayılanlarını eziyor, açık
# auto_paper pozisyonları ve `positions` satırları giriş kapılarını kapatıyor,
# üstüne `test_execution_fixes` gerçek `save_position` ile `positions`'a
# TESTTRY satırı yazıp bırakıyordu. Aşağıdaki fixture OKUMA tarafını
# "boş/varsayılan veritabanı"na sabitler, YAZMA tarafını no-op yapar: test
# sonucu DB'nin içeriğine bağlı olmaz ve DB'ye hiçbir şey yazılmaz.
#
# Neden `_run_db` yerine fonksiyon düzeyinde? (Bkz. yukarıdaki not 2.) Testler
# zaten `patch.object(database, "<fonksiyon>", ...)` ile fonksiyon düzeyinde
# yamalar; burada aynı seviyede, tek yerde ve açık varsayılanlarla yapılır.
# Bir test belirli bir okumayı kendi `patch`'iyle ezebilir (iç içe patch,
# fixture'ın değerinin üstüne biner ve çıkışta ona döner).
#
# Kullanım (test modülünün başında):
#     pytestmark = pytest.mark.usefixtures("isolated_db_state")
_ISOLATED_DB_READS = {
    # Ayar okuması: anahtar için `default` döner → kod varsayılanları geçerli.
    "get_llm_setting": lambda: AsyncMock(side_effect=lambda key, default=None: default),
    "load_positions": lambda: AsyncMock(return_value={}),
    "get_open_auto_paper_trade": lambda: AsyncMock(return_value=None),
    "list_auto_paper_trades": lambda: AsyncMock(return_value=[]),
    "get_last_auto_paper_stop_loss_time": lambda: AsyncMock(return_value=None),
    "get_last_auto_paper_entry_time": lambda: AsyncMock(return_value=None),
    "get_last_auto_paper_winning_trade_time": lambda: AsyncMock(return_value=None),
    "get_recent_auto_paper_trade_by_notification": lambda: AsyncMock(return_value=None),
    "get_recent_auto_paper_trade_by_notification_key": lambda: AsyncMock(return_value=None),
}
_ISOLATED_DB_WRITES = (
    "set_llm_setting", "save_position", "delete_position", "save_signal",
    "save_decision_log",
)


@pytest.fixture
def isolated_db_state(monkeypatch):
    """`app.database` okumalarını boş/varsayılan duruma sabitle, yazmaları kapat."""
    from app import database

    for name, make_mock in _ISOLATED_DB_READS.items():
        if hasattr(database, name):
            monkeypatch.setattr(database, name, make_mock())
    for name in _ISOLATED_DB_WRITES:
        if hasattr(database, name):
            monkeypatch.setattr(database, name, AsyncMock(return_value=None))
    yield database
