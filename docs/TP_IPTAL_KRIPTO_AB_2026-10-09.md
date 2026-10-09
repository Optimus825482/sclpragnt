# TP-İptal (cancel-on-trail) Kripto A/B — Bulgular ve Karar (2026-10-09)

**Görev:** Forex'te (`scalperagent_global`) kanıtlanan "trailing devreye girince sabit TP
emrini iptal et" mekanizmasını Binance TR kripto otonom işlemlerine (`auto_paper`)
uygula — ama kör kopyalama yok; önce bu projede çok-pencereli A/B ile test et.

**Karar (sonuçtan önce yazıldı, `work/ab_tp_cancel.py` başlığında):**
B (cancel), ≥3 bağımsız pencerede A'yı geçer VE işaret-tutarlı VE genel net iyileşir VE
maxDD artmazsa → uygula; aksi halde dokunma. **Sonuç: B uygulandı** (opt-in, varsayılan
KAPALI).

> ### ⚠️ EK BÖLÜM (2026-10-09, daha sonra): CANLI PARAMETRELERDE SONUÇ DEĞİŞTİ
>
> Aşağıdaki §Yöntem repodaki **kanon** parametreleri kullanır (SL 5,0 / trig 1,0 / gap 0,3 /
> 120 dk). Ama canlı `auto_paper_settings` satırı **bambaşka**: **SL 1,5 / trig 1,8 / gap 0,6 /
> 60 dk**. Canlı parametrelerle aynı A/B tekrarlandığında sıralama **tersine döner** ve asıl
> kazanan **C (TP-primary kapalı)** olur — B (bu görevin mekanizması) neredeyse değersizdir.
> Kanıt ve uygulama: **aşağıda "Canlı parametrelerle yeniden koşum" bölümü.** O bölüm bu
> dokümanın kararını **geçersiz kılar**; üstteki tablo yalnız kanon parametreler için geçerlidir.

---

## Yöntem

- **Veri:** `work/analiz_2026-10-07/klines_30d.json` — 256 sembol × gerçek Binance TR 5 dk
  mumu, 2026-09-06 → 2026-10-07 (30 gün). Bildirimler: `n[0-9].json` (3223 satır).
- **Havuz:** `mode ∈ {trend_devam, unified}` (canlı `allowed_modes`) + 60 dk dedup → **1231 işlem**.
- **Maliyet:** %0,325/işlem (repo kanonu).
- **Model** (`work/ab_tp_cancel.py`), canlı `_manage_single_trade` (30 sn yoklama ≈ mum-içi):
  muhafazakâr sıra — önce SL, sonra TP; trailing `hi ≥ trig` ile aktive, `stop = tepe−(gap)`,
  ilk aktivasyonda stop güncel fiyatın altına çekilir (canlı koddaki gibi).
- **Varyantlar:**
  - **A `ratchet`** — mevcut: TP asla silinmez; trailing stop TP'nin üstüne çıkarsa TP yukarı kayar.
  - **B `cancel`** — trailing **devreye girdiği an** TP iptal (önceki barlarda ratchet → canlı kodun minimal değişimi).
  - **B' `cancel0`** — ratchet hiç yok, düz cancel-on-trail.
  - **C `tp_off`** — TP-primary tümden kapalı (`AUTO_PAPER_TP_PRIMARY_ENABLED=false`).

## Sonuç (1231 işlem, 30 gün)

| Varyant | İşlem başı net | İsabet | maxDD |
| --- | ---: | ---: | ---: |
| A ratchet (mevcut) | **+0,299%** | 72% | 48,6 |
| B cancel-on-trail | **+0,436%** | 72% | 46,6 |
| C TP-primary kapalı | **+1,087%** | 72% | 37,1 |

**Eşleştirilmiş test (A referans):** B−A **+0,138%** [%95 CI +0,092…+0,188], wilcoxon
**p=2,1e-14**. `cancel0` birebir aynı (ratchet engellenen 60 işlem zaten koşulu sağlamıyordu).

**Bağımsız pencereler (5 günlük kronolojik bloklar):**

| Pencere | n | A | B | B−A |
| --- | ---: | ---: | ---: | ---: |
| 09-07 | 122 | +0,552 | +0,830 | +0,277 |
| 09-12 | 62 | +1,583 | +1,757 | +0,174 |
| 09-17 | 442 | +0,142 | +0,303 | +0,161 |
| 09-22 | 227 | +0,260 | +0,260 | −0,000 |
| 09-27 | 141 | +0,340 | +0,478 | +0,138 |
| 10-02 | 233 | +0,117 | +0,265 | +0,148 |

→ **B 5/6 pencere.** Parametre taraması (trig 0.8/1.0/1.2 × gap 0.3/0.5 × SL 4/5/6 = 18
kombinasyon): **B 18/18 kazandı**, hepsinde train VE test pozitif. → **Kanıt-tutarlı.**

## KRİTİK YAN BULGU: asıl kazanç "sabit TP'yi kaldırmak"ta (varyant C), "iptal anı"nda değil

`trig (1.0) < her TP (≥1.5)` olduğu için trailing TP'ye **uğramadan** aktive olur; dolayısıyla
B (aktivasyonda iptal) pratikte C (TP-primary kapalı) ile **aynı işlevdedir**. İkisi de sabit
TP'yi devre dışı bırakır. Fark yalnızca trigger'ın TP'ye çok yakın olduğu marjinal işlemlerde
görünür — orada B, TP'yi değmeden iptal ettiği için C'den **kötüdür**.

Ayrışan 243 işlemde tipik tablo: **B'de fiyat sabit TP'ye takılıp (+3,675'te) kapanırken, C'de
trailing aynı işlemi +6,6…+12,5'e taşıyor.** Yani sabit TP, havuzun sağ kuyruğunu
(120 dk'da işlemlerin %13'ü ≥+10%) kesiyor.

**Bu bulgu bu projede ZATEN belgeli:** `config.py:883` yorumu ve commit `928feaf` —
*"TP = bildirim hedefi … cogu islem hedefe hic degmiyor, degince de kazanan erken kesiliyordu"*;
o commit **`AUTO_PAPER_TP_PRIMARY_ENABLED` varsayılanını `false` yapmıştı (+1.375%/işlem)**.

**⚠️ ÇELİŞKİ (ayrı karar gerektirir):** canlı-backed kod varsayılanı `tp_primary_exit_enabled=True`
(`auto_paper.py:1485`) — commit `928feaf`'in `false` kanıtıyla **ÇELİŞİYOR**. Ölçtüğümüzde
TP-primary'i kapatmak (C) A'ya karşı **+0,789%** (p=6,4e-51, 6/6 pencere) veriyor.
Bu görevin kapsamı TP-cancel-on-trail'dir; ancak operatöre açık öneri:
**`tp_primary_exit_enabled` ile `tp_cancel_on_trail` aynı anda AÇIK olmasın** — aksi halde TP,
trailing devreye girdiği an iptal edilir ve C'ye kıyasla trigger'a yakın kalan işlemlerde
~%0,65/işlem kaybedilir. Tutarlı seçim, bu projenin kendi kanıtına göre **TP-primary kapalı**
(TP-emri yok; cancel ayarı etkisiz) veya ikisi de kapalı (mevcut ratchet).

## 2026-09-18 neden farklıydı?

O günkü başarısızlığın kök nedeni iptalin kendisi değil, **iptalin geri diriltilmesiydi**:
TP silindiğinde BE/trailing güncellemeleri TP'yi yeniden yazıp iptal edilen hedefi diriltiyordu
(bkz. `settings/page.tsx` eski metni ve `_update_existing_trade` yorumları). Bu uygulamada
dirilme **tek-yol bekçisiyle** engellenmiştir (aşağıda).

---

## Uygulama (kanon A/B'de yalnız B geçtiği için; canlı koşumda karar C'ye döndü — yukarı bakın)

| Katman | Değişiklik |
| --- | --- |
| `config.py` | `AUTO_PAPER_TP_CANCEL_ON_TRAIL` (env, varsayılan **`false`** = opt-in) |
| `database.py` | `auto_paper_trades.tp_cancelled BOOLEAN DEFAULT FALSE` (idempotent migration) |
| `database.py` | `cancel_auto_paper_trade_tp()` — tek yol: `take_profit=0` + `tp_cancelled=TRUE` |
| `database.py` | `update_auto_paper_trade_tp()` — `tp_cancelled` iken TP **yazmaz** (dirilme bekçisi) |
| `auto_paper.py` | `_manage_single_trade`: `tp_cancelled` okunur; TP-primary dalı `not tp_cancelled` ile; trailing aktivasyonunda iptal; ratchet dalı `not tp_cancelled` ile |
| `auto_paper.py` | `_update_existing_trade` (bildirim hedefi): `tp_cancelled` ise TP yazmaz |
| `auto_paper.py` | Ayarlar: `get_default_settings` + `editable` + `update_settings_endpoint` alanları |
| `auto_paper.py` | **`get_default_settings["tp_primary_exit_enabled"]` = `False`** (P2-2'nin `True`'su geri alındı) + `_manage_single_trade` ve `update_settings_endpoint` içindeki `getattr(..., True)` yedekleri `False`'a çekildi |
| `settings/page.tsx` | Trailing bölümüne toggle + **yanıltıcı metin düzeltmesi** (eski metin "trailing sonrası TP uygulanmaz" diyordu ama backend ratchet yapıyordu) |
| `settings/page.tsx` | **TP-Primary bölümü + toggle** (canlı DB satırı kodu ezdiği için tek operatör kontrolü bu) |
| `tests/test_auto_paper.py` | 4 test: iptal+flag, TP-primary engeli, varsayılan ratchet korunur, opt-in KAPALI + **`test_tp_primary_disabled_by_default`** |
| **canlı DB** | `auto_paper_settings.tp_primary_exit_enabled: true → false` (22 anahtar korunarak) |

**Dirilme engeli (brief'teki KRİTİK İNCELİK):** iptal `tp_cancelled` bayrağıyla **kalıcıdır**;
sonraki turlarda (1) TP-primary dalı ateşlemez, (2) `update_auto_paper_trade_tp` (bildirim
hedefi + ratchet + BE yollarının tümü aynı fonksiyonu kullanır) bayrak set olduğundan TP
yazmaz. Böylece TP bir kez iptal edilince **hiçbir yol geri diriltemez**.

## Geri alma

**Deploy edilen karar C (TP-primary kapalı).** Geri alma:

- **C'yi geri al** (sabit TP'yi tekrar aç): Ayarlar > Otonom Paper Trade >
  "Sabit Take-Profit (TP-Primary) Çıkışı" = **Açık**. Ya da env
  `AUTO_PAPER_TP_PRIMARY_ENABLED=true` — **ama** canlı DB satırı env'i ezer
  (bkz. `config.py:795` öncelik notu), yani pratikte **UI'dan** veya DB satırından değiştirin.
- **B'yi kapat** (uygulandı ama kapalı/etkisiz): Ayarlar > "Trailing'de TP İptali" = Kapalı
  veya env `AUTO_PAPER_TP_CANCEL_ON_TRAIL=false` (varsayılan zaten kapalı).

Geri alma sonrası not: A (ratchet) canlı parametrelerde **−0,073%/işlem** (6 pencerenin
6'sında negatif) veriyordu; C'ye dönmek geçmiş 30 güne göre tek pozitif seçenek.

## Canlı parametrelerle yeniden koşum — KARAR DEĞİŞTİ (2026-10-09, Erkan: "hangisi en karlı ise onu uygula")

**Tetikleyici:** `auto_paper_settings` DB satırı okunduğunda canlı parametrelerin yukarıdaki
A/B'nin grid'inde **hiç bulunmadığı** görüldü:

| Parametre | A/B (kanon) | **CANLI (DB)** |
| --- | ---: | ---: |
| Stop Loss | %5,0 | **%1,5** |
| Trailing trigger | %1,0 | **%1,8** |
| Trailing gap | %0,3 | **%0,6** |
| Max hold | 120 dk | **60 dk** |

**Canlı `TRIG (1,8) > TP (medyan 3,38; %22'sinde < 1,8)`** — yani sabit TP **trailing devreye
girmeden önce** doluyor. Bu, mekanizmayı tamamen tersine çevirir: "iptal anı" diye bir şey
kalmıyor. Bu yüzden kanon A/B'nin B lehine sonucu canlıya **taşınamaz**; `work/ab_tp_cancel_live.py`
aynı havuzu (1232 işlem) canlı değerlerle yeniden koştu.

| Varyant | İşlem başı net | İsabet | maxDD | Pencere |
| --- | ---: | ---: | ---: | ---: |
| A ratchet (**canlının mevcut hâli**) | **−0,073%** | %43 | 183,3 | **0/6** |
| B cancel-on-trail (forex mekanizması) | −0,034% | %43 | 154,7 | 0/6 |
| **C TP-primary kapalı** | **+0,479%** | %41 | **37,5** | **6/6** |

**Eşleştirilmiş test:** C−A **+0,552%** [%95 CI +0,428…+0,685], wilcoxon **p=1,8e-24**.
B−A yalnız **+0,040%** (p=2,5e-4) → B canlıda **neredeyse değersiz**.
**Parametre taraması (5 SL × 5 trig × 3 gap = 75 kombinasyon): C 75/75 kazandı**; train
(+0,587) ve test (+0,371) ikisinde de pozitif olan **tek** varyant. maxDD 183 → 37 (**5× azalma**).
Çıkış nedeni dağılımı da anlatı: TP-primary kapalıyken kapanışların 448'i trailing'e kayar,
`SL:574 → 595` (TP'ye takılan kazanlar artık SL'ye dönmüyor, trailing taşıyor).

**SONUÇ: C uygulandı.** Zincirleme neden: `tp_primary_exit_enabled` varsayılanı zaten `config.py:883`
+ commit `928feaf` ile `false` olmalıydı; koddaki `True` (P2-2) bununla çelişiyordu.
Bu oturumda üç katman birden hizalandı —
(1) kod varsayılanı `false`, (2) canlı DB satırı `false`, (3) Ayarlar UI'da anahtar.

**Not:** `tp_cancel_on_trail` (B) **kapalı** bırakıldı. Sebep: TP-primary kapalıyken iptal
edecek TP yoktur (ayar etkisiz); TP-primary açıkken ise B, C'den **kötüdür** (yukarıdaki
kanon tablo: B +0,436 vs C +1,087). Yani B bu projede **hiçbir konfigürasyonda** optimal değil.

## Kanıt dosyaları

- Kanon A/B harness: `work/ab_tp_cancel.py`, çıktı: `work/ab_tp_cancel_sonuc.txt`.
- **Canlı parametre A/B: `work/ab_tp_cancel_live.py`, çıktı: `work/ab_tp_cancel_live_sonuc.txt`.**
- Veri: `work/analiz_2026-10-07/` (gitignored, 30 gün mum + bildirim).
- Bu bulgu görev brief'ini uygular: `scalperagent_global/docs/GOREV_BRIEF_TP_IPTAL_KRIPTO.md`.
