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
