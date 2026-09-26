"""WebSocket client lifecycle and fan-out primitives.

BACKPRESSURE (Görev 11)
-----------------------
Eskiden `broadcast` `asyncio.gather` ile TÜM göndermelerin bitmesini bekliyordu
(istemci başına 0.75 sn zaman aşımı). Tek bir yavaş istemci (arka plan sekmesi,
donmuş mobil ağ) döngünün büyük bir kısmını harcıyor, `ws_live_candles` her
kline'da `create_task(broadcast(...))` çağırdığı için de görev patlaması
(~25 görev/sn) oluşuyordu.

Yeni model — istemci başına KUYRUK + per-istemci gönderim görevi:

    broadcast(message)
        └─ her istemcinin kuyruğuna `put_nowait` (O(1), ASLA beklemez)
             ├─ kuyruk doluysa EN ESKİ mesaj düşürülür (ticker verisi zaten
             │  "en son" anlamında; eski kare işe yaramaz)
             └─ her istemcinin kendi `drain` görevi kuyruğu boşaltır

`broadcast` artık hiçbir zaman I/O beklemez: çağıran (radar döngüsü, kline
dinleyicisi) anında geri döner, yavaş istemci yalnız KENDİ kuyruğunu
geciktirir ve geciktiğinde en eski mesajını kaybeder — diğer istemciler
etkilenmez.

KULLANICI KAPSAMI (GÜVENLİK — çok kullanıcılı kurulum)
------------------------------------------------------
`broadcast` varsayılan olarak TÜM bağlantılara gider; bu, piyasa verisi
(sinyal, fiyat, kline) için doğrudur çünkü veri zaten herkese açıktır.
Ancak `binance_account_update` **kişiye özeldir**: bakiye, holdings ve
pozisyonlar yalnız o kullanıcının hesabına aittir. Kapsamsız yayında
her bağlı istemci HERKESİN bakiyesini görürdü.

Bu yüzden `broadcast(message, *, user_id=None)`:
  * `user_id=None` → eski davranış (herkese açık veri).
  * `user_id=<id>` → yalnız O kullanıcıya ait bağlantıların kuyruğuna konur.
Filtre KULLANICI SEÇİMİNDE yapılır, kuyruk katmanında değil: `_ClientOutbox`
bileşenleri değişmeden kalır, her istemcinin kuyruğu yine kendisine ait.

FAIL-CLOSED (güvenlik varsayılanı)
---------------------------------
`user_id` VERİLİYSE ve hiçbir bağlantı o kullanıcıya eşlenmemişse mesaj
HİÇBİR YERE gönderilmez. "Eşleşmeyen bağlantıya gönder" kuralı, kimlik
çıkarılamayan bir bağlantıya (kimliksiz `connect()`) kişisel veri sızdırırdı.
Yalnız `user_id=None` (herkese açık) yayınlar kimliksiz bağlantılara gider —
mevcut test doubles ve tek kullanıcılı kurulum böyle çalışır.
"""

import asyncio
from typing import Any, Hashable

# İstemci başına kuyruk derinliği. Ticker/kline akışı "en son değer"
# anlamında olduğu için 64 kare bol; dolu kuyruk yavaş istemciyi korur.
CLIENT_QUEUE_MAXSIZE = 64
# Tek bir gönderim için zaman aşımı: yavaş/kopuk istemci döngüyü bloklamaz.
CLIENT_SEND_TIMEOUT_SEC = 0.75


class _ClientOutbox:
    """Tek bir istemciye ait kuyruk + onu boşaltan görev."""

    __slots__ = ("websocket", "queue", "task", "dropped", "on_dead")

    def __init__(self, websocket, maxsize: int = CLIENT_QUEUE_MAXSIZE,
                 on_dead=None):
        self.websocket = websocket
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self.task: asyncio.Task | None = None
        self.dropped = 0
        #: Gönderim kalıcı olarak başarısız olduğunda çağrılır; bağlantı
        #: yöneticisini temizlik yapmaya çağırır (D-15).
        self.on_dead = on_dead

    def offer(self, message: dict) -> None:
        """Mesajı kuyruğa koy; doluysa EN ESKİ mesajı düşür (bloklama YOK)."""
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            try:
                self.queue.get_nowait()          # en eskiyi at
                self.dropped += 1
                self.queue.put_nowait(message)   # yerine yenisini koy
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                self.dropped += 1                # yarış: mesajı bu turda at

    async def drain(self) -> None:
        while True:
            message = await self.queue.get()
            try:
                await asyncio.wait_for(
                    self.websocket.send_json(message), timeout=CLIENT_SEND_TIMEOUT_SEC)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Kopmuş/yavaş istemci: bu istemcinin döngüsü kapanır ve
                # bağlantı yöneticisi onu listeden çıkarır.
                #
                # D-15 (2026-09-26, gerçek hata): burada yalnız `return`
                # yazılıydı; "yönetici listeden çıkarır" vaadi TUTULMUYORDU.
                # Sonuç: (1) kopmuş istemci `active_connections` ve
                # `_outboxes` içinde sonsuza dek birikiyordu, (2) her
                # `broadcast` ölü istemcinin kuyruğunu dolduruyor, kuyruk
                # taşıp `dropped` sayacı yanlış yere yazıyordu — `offer()`
                # artık var olmayan bir bağlantıya da mesaj koyuyordu.
                # Düzeltme: kopma sinyalini yöneticiye bildir, O DA
                # `disconnect` ile listelerden temizlesin.
                if self.on_dead is not None:
                    await self.on_dead(self.websocket)
                return


class ConnectionManager:
    def __init__(self):
        self.active_connections = []
        # {id(websocket): _ClientOutbox} — bağlantı kimliğiyle eşlenir.
        self._outboxes: dict[int, _ClientOutbox] = {}
        # {id(websocket): user_id} — bağlantı → sahibi kullanıcı (kişisel
        # yayınların hedefi). `connect()` verilmezse anahtar YOKTUR: o bağlantı
        # kimliksizdir ve hiçbir kişisel yayını almaz (fail-closed).
        self._owners: dict[int, Hashable] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket, *, user_id: Any = None):
        """Bağlantıyı kabul et, kuyruğunu başlat, sahibini kaydet.

        `user_id` verilirse bu bağlantı o kullanıcıya aittir ve
        `broadcast(..., user_id=<id>)` yayınlarını alır. Verilmezse bağlantı
        kimliksizdir: yalnız herkese açık (`user_id=None`) yayınları alır.
        """
        await websocket.accept()
        async with self._lock:
            if websocket not in self.active_connections:
                self.active_connections.append(websocket)
            if user_id is not None:
                self._owners[id(websocket)] = user_id
            if id(websocket) not in self._outboxes:
                outbox = _ClientOutbox(websocket, on_dead=self.disconnect)
                self._outboxes[id(websocket)] = outbox
                outbox.task = asyncio.create_task(outbox.drain())

    async def disconnect(self, websocket):
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
            outbox = self._outboxes.pop(id(websocket), None)
            self._owners.pop(id(websocket), None)
        if outbox and outbox.task and not outbox.task.done():
            outbox.task.cancel()

    def owner_of(self, websocket) -> Any:
        """Bu bağlantının kullanıcı kimliği (kayıt yoksa `None`)."""
        return self._owners.get(id(websocket))

    def has_owner(self, user_id: Any) -> bool:
        """Verilen kullanıcının EN AZ BİR açık bağlantısı var mı?

        Hesap push döngüsü boşta tur atlamak için kullanır: kullanıcının
        hiç sekmesi yoksa bakiye/pozisyon sorgusu hiç yapılmaz.
        """
        return any(owner == user_id for owner in self._owners.values())

    def clients_for(self, user_id: Any) -> list:
        """Yalnız bu kullanıcıya ait bağlantılar (tanıtım/gözlemlenebilirlik)."""
        return [ws for ws in self.active_connections
                if self._owners.get(id(ws)) == user_id]

    async def broadcast(self, message: dict, *, user_id: Any = None):
        """Mesajı KUYRUĞA koy; hiçbir gönderimi beklemez.

        Çağıran (radar döngüsü, kline dinleyicisi) anında geri döner. Yavaş bir
        istemci diğerlerini geciktiremez; yalnızca kendi kuyruğu dolar ve en
        eski mesajları düşer.

        `user_id` VERİLİYSE mesaj YALNIZ o kullanıcının bağlantılarına gider
        (bakiye/pozisyon gibi kişisel veri için ZORUNLU). Kimliği eşleşmeyen
        hiçbir bağlantı mesajı ALMAZ.
        """
        for outbox in self._target_outboxes(user_id):
            outbox.offer(message)
        # Bağlantı listesine hiç girmemiş (nadir, test) durumlar için yedek yol:
        # kuyruk kaydı olmayan bağlantılar doğrudan gönderilir.
        known = {id(o.websocket) for o in self._outboxes.values()}
        for websocket in self._target_connections(user_id):
            if id(websocket) in known:
                continue
            try:
                await asyncio.wait_for(websocket.send_json(message),
                                       timeout=CLIENT_SEND_TIMEOUT_SEC)
            except Exception:
                await self.disconnect(websocket)

    def _target_outboxes(self, user_id: Any) -> list:
        """Bu yayının HEDEFLEDİĞİ kuyruklar (kapsam burada uygulanır)."""
        if user_id is None:
            return list(self._outboxes.values())
        return [outbox for key, outbox in self._outboxes.items()
                if self._owners.get(key) == user_id]

    def _target_connections(self, user_id: Any) -> list:
        """Bu yayının HEDEFLEDİĞİ bağlantılar (yedek gönderim yolu)."""
        if user_id is None:
            return list(self.active_connections)
        return [ws for ws in self.active_connections
                if self._owners.get(id(ws)) == user_id]

    def queue_stats(self) -> dict:
        """Backpressure gözlemlenebilirliği (sağlık ucu için)."""
        return {
            "clients": len(self.active_connections),
            "identified_clients": len(self._owners),
            "scoped_clients": len(set(self._owners.values())),
            "queue_maxsize": CLIENT_QUEUE_MAXSIZE,
            "dropped_total": sum(o.dropped for o in self._outboxes.values()),
            "pending": sum(o.queue.qsize() for o in self._outboxes.values()),
        }


ws_manager = ConnectionManager()
