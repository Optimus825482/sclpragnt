BINANCE TR SPOT EMIR KODU - RESMI DOKUMAN DENETIMI
Tarih: 2026-10-18. Kapsam: backend/app/binance_tr_private.py, binance_tr_public.py, binance_tr_user_stream.py, main.py ve routers/binance_trade.py cagri noktalari.
GERCEK BORSAYA ISTEK ATILMADI, DB'ye yazilmadi, commit yok.

======================================================================
1. KAYNAKLAR
======================================================================
- https://www.binance.tr/apidocs/ (resmi, "Docbox"): ERISILDI. Ham HTML curl ile indirildi (apidocs_raw.html, 200 KB, sunucu tarafi render) ve metne cevrildi (apidocs_text.txt). Surum = sayfadaki Change Log'un en yenisi: 2026-08-28 (Travel Rule uclari). Cekim tarihi 2026-10-18.
- GitHub deposu (binance-tr-api-docs vb.): web aramasinda bulunamadi; kullanilmadi. Ikincil kaynak KULLANILMADI, her sey resmi sayfadan.
- Bu klasordeki dosyalar: apidocs_raw.html, apidocs_text.txt (tam metin), excerpt_01_changelog_general_signing.txt, excerpt_02_enums_filters_general_market.txt, excerpt_03_account_order_endpoints.txt, excerpt_04_user_data_streams.txt, fetch_date.txt

Dokumanin onemli noktalari
- Base: https://www.binance.tr ; bazi public market uclari https://api.binance.me (type 1) / https://cloudme-tr.2meta.app (type 3).
- Auth: X-MBX-APIKEY; imza HMAC-SHA256, totalParams = query string + request body; timestamp ms; recvWindow varsayilan 5000, max 60000; kural: timestamp < serverTime+1000 && serverTime-timestamp <= recvWindow. POST parametreleri query'de, body'de ya da karisik olabilir (body oncelikli).
- 5XX = durum BILINMIYOR (basarili olmus olabilir). 429/418 + Retry-After. Agirlik basligi X-MBX-USED-WEIGHT-(n)(harf), emir sayaci X-MBX-ORDER-COUNT-... Sayisal agirlik/limit degerleri (or. 1200/dk) dokumanda YOK.
- Enum: side 0 BUY / 1 SELL; type 1 LIMIT, 2 MARKET, 3 STOP_LOSS, 4 STOP_LOSS_LIMIT, 5 TAKE_PROFIT, 6 TAKE_PROFIT_LIMIT, 7 LIMIT_MAKER; timeInForce (INT) 1 GTC, 2 IOC, 3 FOK, 4 GTX; status -2 SYSTEM_PROCESSING, 0 NEW, 1 PARTIALLY_FILLED, 2 FILLED, 3 CANCELED, 4 PENDING_CANCEL (kullanilmiyor), 5 REJECTED, 6 EXPIRED.
- Filtre adlari: PRICE_FILTER, PERCENT_PRICE, LOT_SIZE, NOTIONAL (minNotional, applyToMarket, avgPriceMins; "MIN_NOTIONAL" adi YOK), ICEBERG_PARTS, MARKET_LOT_SIZE, MAX_NUM_*.
- POST /open/v1/orders: zorunlu symbol, side, type, timestamp; tipe gore: 1->quantity+price; 2->quantity (sell) veya quoteOrderQty (buy); 3->quantity+stopPrice; 4->quantity+price+stopPrice; 5->quantity+stopPrice; 6->quantity+price+stopPrice; 7->quantity+price. clientId: "sunucu benzersizligi denetlemez, gonderilmezse uretilir" (uzunluk/karakter kurali YOK). Cevap: data.orderId (string) + createTime. Dolum alani YOK.
- POST /open/v1/orders/oco: symbol, side, quantity, price, stopPrice, stopLimitPrice zorunlu; listClientId, limitClientId, stopClientId opsiyonel; stopLimitTimeInForce YOK; tekil clientId YOK. Cevap ornegi data.orderId + createTime.
- GET /open/v1/orders/detail, POST /open/v1/orders/cancel: orderId veya clientId (biri zorunlu); symbol parametresi dokumanda YOK. POST /open/v1/orders/batch-cancel (symbol veya orderIds). OCO icin ayri iptal ucu dokumanda YOK.
- GET /open/v1/orders: symbol ZORUNLU; type 1 acik / 2 gecmis / -1 hepsi; limit max 1000. Detay cevabi alanlari: executedQty, executedPrice, executedQuoteQty, origQty, origQuoteQty, status (int).
- GET /open/v1/orders/trades: symbol zorunlu; fromId varsa direct zorunlu; alanlar tradeId, orderId, qty, quoteQty, commission, commissionAsset, isBuyer, isMaker, time.
- GET /open/v1/account/spot (+ 2026-04-07: fiatMakerCommission / fiatTakerCommission).
- Kullanici akisi: POST /open/v1/user-data-stream (listenKey) 2026-04-30'da kapatilacagi duyuruldu; guncel yol POST /open/v1/user-listen-token (validity ms, varsayilan ve azami 24 sa) + WS API wss://ws-api.binance.tr:443/ws-api/v3 userDataStream.subscribe.listenToken; yenileme = yeni token + yeniden subscribe; sure dolarsa eventStreamTerminated. Olaylar executionReport, outboundAccountPosition.
- Hata kodu tablosu (3703, -1013, -2010 vb.) dokumanda YOK. clientId karakter/uzunluk kurali YOK.
- Yeni: selfTradePreventionMode (2026-05-19), timeInForce (2026-03-23), GET /api/v3/executionRules + Price Range Execution Rule (taker emri aralik disi -> EXPIRED, eR).

======================================================================
2. KARSILASTIRMA TABLOSU
======================================================================
MATCH = dokuman ile ayni; MISMATCH = dokumanla celisiyor; UNVERIFIED = dokuman sessiz/belirsiz.

 #  | Uc / konu | Bizim kod | Dokuman | Durum
 1  | Base URL | https://www.binance.tr (REST_BASE) | ayni | MATCH
 2  | Auth basligi | X-MBX-APIKEY | ayni | MATCH
 3  | Imza | HMAC-SHA256(secret, siralı urlencode query); POST govdesi bos; &signature= sona | totalParams = query+body | MATCH
 4  | timestamp | ms, sunucu saati ofsetli (/open/v1/common/time) | ms, < serverTime+1000 | MATCH
 5  | recvWindow | 10000 | varsayilan 5000, max 60000 | MATCH
 6  | Agirlik basligi | X-MBX-USED-WEIGHT-1M okunuyor | X-MBX-USED-WEIGHT-(n)(harf) | MATCH
 7  | 5XX/zaman asimi emir POST'u | tekrar gonderilmez, BinanceTrAmbiguousOrderError | 5XX = durum bilinmiyor | MATCH
 8  | 418/429 + Retry-After | isleniyor | ayni | MATCH
 9  | Dakikalik 1200 agirlik limiti | REST_MAX_WEIGHT_1M=1200 | sayi yok | UNVERIFIED
 10 | Private sembol bicimi | BTC_TRY (alt cizgi) | alt cizgi | MATCH
 11 | side kodlari | BUY=0, SELL=1 | 0/1 | MATCH
 12 | type kodlari | LIMIT=1, MARKET=2, STOP_LOSS_LIMIT=4 | 1/2/4 | MATCH
 13 | LIMIT emri | quantity+price+timeInForce=1 (INT) | 1->quantity,price; tif INT 1=GTC | MATCH
 14 | STOP_LOSS_LIMIT | quantity+price(stopLimit)+stopPrice+tif=1 | 4->quantity,price,stopPrice | MATCH
 15 | MARKET SELL | quantity (LOT_SIZE adimina asagi) | quantity | MATCH
 16 | MARKET BUY | quoteOrderQty (quantity yok) | quoteOrderQty | MATCH
 17 | Parametre tipleri | quantity/price/stopPrice STRING | STRING | MATCH
 18 | Bilimsel gosterim | _fmt_quantity/_fmt_price f"{x:.8f}" bicimi, e-notasyon yok | belirtilmemis | MATCH (guvenli)
 19 | Tekil emir clientId adi | clientId | clientId | MATCH
 20 | clientId karakter/uzunluk kurali, 3703 | yalniz ASCII harf/rakam, <=36 (canli gozleme dayali) | HICBIR kural yazmiyor | UNVERIFIED
 21 | Yeni emir cevabi | orderId okunuyor; dolum alani yoksa tam dolum varsayiliyor (_order_fill) | cevap yalniz orderId+createTime | UNVERIFIED (risk, bkz. 5.1)
 22 | OCO tekil kimlik parametresi | clientId gonderiliyordu | listClientId/limitClientId/stopClientId; clientId yok | MISMATCH -> DUZELTILDI
 23 | OCO zorunlu alanlar | symbol, side=1, quantity, price, stopPrice, stopLimitPrice | ayni | MATCH
 24 | OCO stopLimitTimeInForce | gonderilmiyor | parametre yok | MATCH
 25 | OCO cevabi | orderListId okunuyordu | data.orderId+createTime | MISMATCH -> kismen duzeltildi (order_id eklendi; order_list_id korundu)
 26 | OCO fiyat kurali | TP > son fiyat > SL | SELL: Limit > Last > Stop | MATCH
 27 | Emir iptali orderId | orderId (int) | orderId LONG | MATCH
 28 | Iptal/detay symbol parametresi | ekstra symbol gonderiliyor | dokumanda yok | UNVERIFIED (canlida calisiyor kabul; degistirilmedi)
 29 | OCO iptal ucu | bacaklar ayri orderId ile iptal | OCO iptal ucu belgelenmemis | UNVERIFIED
 30 | Emir detayi orderId/clientId | biri gonderilir | biri zorunlu | MATCH
 31 | Detay cevabi alanlari | executedQty, executedQuoteQty (+ eski cummulativeQuoteQty yedegi) | executedQty, executedPrice, executedQuoteQty | MATCH
 32 | Acik emirler type=1, limit<=1000 | type=1, limit 100/50 | type 1=open, max 1000 | MATCH
 33 | Acik emirlerde symbol | once sembolsuz dener, hata verirse tarar | symbol ZORUNLU | MISMATCH (tolere; fallback var, degistirilmedi)
 34 | Durum kodlari | ham sayi gecer; UI (OrderPanel.tsx) -2,0,1,2,3,5,6 esliyor | -2,0..6 (4 kullanilmiyor) | MATCH
 35 | Trade gecmisi | symbol, startTime, endTime, fromId+direct=prev, limit<=1000; tradeId/qty/quoteQty/... | ayni | MATCH
 36 | Hesap | data.accountAssets[{asset,free,locked}] | ayni | MATCH
 37 | Komisyon alanlari | maker/taker + fiatMaker/fiatTaker | ayni | MATCH
 38 | Sembol listesi | GET /open/v1/common/symbols -> data.list; LOT_SIZE, MARKET_LOT_SIZE, NOTIONAL(minNotional), PRICE_FILTER(tickSize), ocoEnable, orderTypes | ayni | MATCH
 39 | Sembol status alani | status yoksa TRADING varsayiliyor | status yok; spotTradingEnable var | UNVERIFIED
 40 | Sunucu saati | timestamp (data yok) okunuyor | timestamp ust seviye | MATCH
 41 | Lot/tick kurali (q-min)%step==0 | floor(q/step)*step (min'e hizalama yok) | kural bu | UNVERIFIED (bkz. 5.2)
 42 | User stream: listenKey | KULLANILMIYOR (2026-04-30 kapatildi) | kapatildi/duyurulu | MATCH
 43 | User stream: token olusturma | POST /open/v1/user-listen-token, validity=86400000 | max 24 sa | MATCH
 44 | User stream: WS | wss://ws-api.binance.tr:443/ws-api/v3, userDataStream.subscribe.listenToken | ayni | MATCH
 45 | Yenileme | sure bitimine 5 dk kala yeni token + yeniden subscribe; eventStreamTerminated -> yeniden baglan | ayni akis | MATCH
 46 | Olay alanlari | executionReport (c,i,x,X,z,Z,l,L,n,N,r...), outboundAccountPosition (B[a,f,l]) | ayni | MATCH
 47 | selfTradePreventionMode | gonderilmiyor (opsiyonel) | opsiyonel | MATCH
 48 | GET /api/v3/executionRules / Price Range | entegre degil | taker emri aralik disi EXPIRED (eR) | UNVERIFIED (risk)
 49 | Public /api/v3/depth (api.binance.me) | kullaniliyor | GET api.binance.me/api/v3/depth | MATCH
 50 | Public klines | /api/v3/klines | dokumanda /api/v1/klines | UNVERIFIED (v3 belgelenmemis; calisiyor kabul)
 51 | Public ticker/24hr, ticker/price, bookTicker, exchangeInfo, yedek host api.binance.com | kullaniliyor | TR dokumaninda yok | UNVERIFIED
 52 | Hata kodlari (3703, -1013, -2010, -1021) | kod isliyor (is_transient, -1021 yenileme) | hata tablosu yok | UNVERIFIED

OZET (52 satir): MATCH 38 | MISMATCH 3 (22 ve 25 duzeltildi; 33 tolere) | UNVERIFIED 11.

======================================================================
3. YAPILAN DEGISIKLIKLER
======================================================================
1) backend/app/binance_tr_private.py - place_oco_sell (satir ~1100-1103)
   Once : "clientId": sanitize_client_order_id(...) or new_client_order_id("oc")
   Sonra: "listClientId": ...  (ayni temizlenmis deger)
   Neden: OCO dokumaninda tekil clientId yok; liste kimligi listClientId. Atif: apidocs "New OCO (SIGNED)" parametre tablosu.
   Donus: client_order_id anahtari ayni kaldi (sekil geriye uyumlu), degeri params["listClientId"].
2) Ayni fonksiyon (satir ~1121-1123): yanita EKLENEN order_id anahtari = data.orderId (dokumanin OCO cevabi orderId+createTime). order_list_id korundu (yoksa None). Atif: "New OCO" Response ornegi.
3) backend/app/binance_tr_private.py satir 331-334: yeni kucuk yardimci _order_client_id(params) (clientId yoksa listClientId); _signed_request icindeki 3 BinanceTrAmbiguousOrderError(client_order_id=...) noktasi (satir 387, 443, 469) bunu kullaniyor. Neden: OCO belirsiz sonucunda kimlik bos donmesin.
4) main.py DEGISMEDI (dokumanla celisen nokta bulunmadi).

Testler
- tests/fake_binance_tr.py: dokumana gore yeniden yazildi: HMAC imza dogrulamasi (query string), X-MBX-APIKEY, timestamp/recvWindow kurali, tipe gore zorunlu parametreler, strict parametre kumeleri (OCO'da clientId/type/stopLimitTimeInForce reddedilir), emir cevabi orderId+createTime, OCO cevabi orderId, detay cevabi executedQty/executedPrice/executedQuoteQty (cummulativeQuoteQty ve orderListId kaldirildi), /orders/cancel eklendi.
- tests/test_open_position_e2e.py: fake api_key/secret ile kuruluyor; OCO'da listClientId var / clientId yok, stopLimitPrice, recvWindow<=60000, alista quantity/price yok, imzali isteklerde X-MBX-APIKEY.
- tests/test_binance_tr_private.py: OCO payload testi guclendirildi + 4 yeni test (listClientId + dokuman cevap sekli, belirsiz OCO hata kimligi, imza semasi, dokuman emir kodlari).
- Sonuc: 94 passed.
  Komut: cd backend && PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest tests/test_binance_tr_private.py tests/test_binance_trade_endpoints.py tests/test_open_position_e2e.py tests/test_binance_fee_mode.py tests/test_binance_key_verify.py tests/test_py311_fstring_guard.py -q -p no:cacheprovider

======================================================================
4. DOGRULANAMADI (dokuman sessiz - davranis DEGISTIRILMEDI)
======================================================================
- clientId karakter kumesi/uzunlugu ve hata 3703 anlami: dokuman hicbir kural yazmiyor. Mevcut "yalniz harf/rakam, <=36" tamamen canli gozlem; dokumanla celismez ama dokumanla dogrulanamaz.
- 3703, -1013, -2010, -1021 gibi hata kodlarinin anlamlari (hata kodu tablosu yok).
- Sayisal agirlik / 1200 dk limiti, emir sayaci limitleri.
- Iptal ve detay cagrilarina eklenen symbol parametresi (dokuman: yalniz orderId|clientId).
- OCO'yu bir butun olarak iptal etme ucu / tek bacagi iptal etmenin digerini dusurup dusurmedigi.
- Sembol islem durumu: kod status alanini bekliyor, dokuman spotTradingEnable veriyor.
- /api/v3/klines, ticker/*, exchangeInfo ve api.binance.com yedek hostu TR dokumaninda yok.
- (quantity-minQty) % stepSize == 0: minQty adimin tam kati degilse kod bunu yakalamaz.

======================================================================
5. KALAN RISKLER / YAN BULGULAR (kod degismedi)
======================================================================
1) Yeni emir cevabi dolum bilgisi tasimiyor (dokuman: yalniz orderId+createTime). place_market_sell executedQty yoksa "tam dolum" varsayar; kismi dolum yakalama (BinanceTrPartialFillError) gercekte hic tetiklenmeyebilir. Alis akisi (open_position._fetch_fill) detayi yokladigi icin guvenli; SELL yolu da emir sonrasi GET /orders/detail ile executedQty dogrulamali. Oneri, ayri is.
2) Float kaymasi: _fmt_quantity (ve main.py 3760/4133/4262, reconcile_sell_fill) math.floor(q/step)*step kullaniyor. Ornek: 1.15/0.01 -> 1.14, 0.29 -> 0.28, 0.3/0.1 -> 0.2, 2.3/0.1 -> 2.2 (bir adim eksik satis -> toz; OCO miktari bir adim dusuk). Gecersiz emir uretmez (guvenli yon) ama pozisyonun son adimi acik kalir. trade_plan.py zaten +1e-9 epsilon kullaniyor; Decimal ile duzeltilebilir. Dokumanla celismedigi icin dokunulmadi.
3) Price Range Execution Rule (2026-04): taker emri referans fiyat araliginin disinda kalirsa EXPIRED olur (eR = EXECUTION_RULE_PRICE_RANGE_EXCEEDED). Kodda executionRules yok; _normalize_event eR alanini almiyor. Volatil anlarda MARKET/limit emirlerin sessizce EXPIRED olmasi mumkun.
4) Acik emirlerde sembolsuz istek (dokuman: symbol zorunlu) her onbellek iskasinda 1 bosa istek olabilir; fallback taramasi calisiyor.
5) OrderPanel.tsx durum haritasinda 4 PENDING_CANCEL yok (dokumanda "kullanilmiyor").
6) place_spot_order yalniz type 1/2/4 destekliyor (3,5,6,7 yok) - dokumanla uyumlu bir alt kume.
7) listToken validity tam ust sinira (24 sa = 86 400 000 ms) ayarli; sunucu "max'i asarsa hata" diyor - esitlik kabul edilmeli ama canlida dogrulanmadi.

======================================================================
6. YALNIZ KUCUK TUTARLI CANLI TESTLE DOGRULANABILECEKLER
======================================================================
- OCO'nun listClientId ile kabul edilmesi (ozellikle oc... 34 karakter alfanumerik); gercek OCO cevabinda orderListId mi orderId mi dondugu; orders dizisi var mi.
- Iptal/detay uclarinda fazladan symbol parametresinin yok sayilip sayilmadigi.
- clientId kuralinin gercek siniri (tire/alt cizgi/uzunluk) ve 3703 tetikleyicileri.
- MARKET SELL cevabinda dolum alanlarinin gelip gelmedigi (yoksa detay yoklamasi gerekir).
- OCO'nun tek bacagini iptal edince digerinin dusup dusmedigi; OCO icin iptal yolu.
- Acik emirlerde sembolsuz isteginin kabul edilip edilmedigi; /api/v3/klines ve ticker uclarinin api.binance.me uzerindeki kararliligi.
- Price Range kurali nedeniyle EXPIRED olan emirlerin gercek sikligi.
