# docs/ Altındaki Veri Üretim Artefaktları

> **2026-09-26 denetimi ile eklendi (bulgu: "docs/ — 17 CSV/SQL çıktısı → veri
> üretim artefaktı, kaynak değil").**
>
> Bu dosya, `docs/` dizinindeki **CSV/SQL çıktılarının ne olduğunu, üretim mi
> araştırma mı olduklarını ve hangi script'in hangisini ürettiğini** belgeler.
>
> **Bunlar kaynak DEĞİLDİR.** Hiçbir Python/TypeScript modülü bunları içe
> aktarmaz; çalışma zamanında okunmazlar. `.gitignore` **kasıtlı olarak
> değiştirilmedi** — bu dosyalar araştırma geçmişi olarak silinmek üzere
> değil, KALDIRILMAK üzere değil.

## Bunlar neden burada?

Bu dizin, strateji araştırmasının **ham çıktılarının** yanlışlıkla dokümantasyon
klasörüne düştüğü bir "sonuç gömme" alanıdır. İçerik tarihsel olarak
değerlidir: bir stratejinin hangi pencerede, hangi parametrelerle ölçüldüğünü
gösterebilir. Ancak dosya adlarındaki `(2)` gibi ekler (yedekleme kalıntısı)
hangi dosyanın "asıl" olanı olduğunu belli etmez.

## Envanter

### 1. Birleşik radar replay CSV'leri (12 dosya)

```
birlesik-radar-replay-20260917-*.csv          (6 adet)
birlesik-radar-geometri-taramasi-20260917-*.csv (6 adet)
```

| Alan | Değer |
| --- | --- |
| **Üreten script** | `backend/scripts/combined_radar_replay_24h.py` (24 saatlik birleşik radar replay'i) |
| **İkincil üretici** | `backend/scripts/analyze_unified_replay_csv.py` (CSV'yi okuyup taramayı yapar) |
| **Tarih** | 2026-09-17, 02:27 – 06:10 arası art arda 6 koşu |
| **Tür** | **Araştırma** — oyun içi (in-game) replay çıktısı, üretim verisi değil |
| **Okuyan kod** | Yok. Yalnız insanlar/araştırma script'leri okur. |

6 farklı zaman damgası, aynı gün içinde tekrarlanan parametre taramasını
gösterir (geometri sweep). Bunlar **sweep'in her adımının ham çıktısıdır**;
parametre önerisi çıkarmak dışında hiçbir işlevsel değerleri yoktur.

### 2. `analysis_snapshots (2).sql` ve `velocity_candidates (2).sql`

| Alan | Değer |
| --- | --- |
| **Üreten script** | `backend/scripts/combined_radar_replay_24h.py` (tablo dökümü) |
| **Tür** | **Araştırma** — canlı DB'den alınmış tablo dökümü |
| **Okuyan kod** | Yok |
| **Uyarı** | Dosya adındaki `(2)` bir **yedekleme kalıntısıdır** (Windows dosya kopyalama çakışması). Asıl dosya adı bu adı taşımıyor; hangisinin güncel olduğu belirsizdir. |

Bu iki dosya canlı üretim tablosunun SQL dökümüdür. Kullanıcı verisi içerebilir
(sembol, fiyat, pozisyon kayıtları) — commit edilmiş olmaları ayrı bir gizlilik
konusudur ve denetim kapsamı dışında bırakılmıştır.

### 3. `monitoring_notifications.sql`

| Alan | Değer |
| --- | --- |
| **Tür** | **Araştırma** — canlı DB'den alınmış tablo dökümü |
| **Üreten** | Elle veya `backend/app/routers/reports.py` / `maintenance.py` çıktısı yönlendirilerek |
| **Okuyan kod** | Yok |

## Özet tablo

| Desen | Adet | Tür | Üreten | Okuyan kod |
| --- | --- | --- | --- | --- |
| `birlesik-radar-replay-*.csv` | 6 | Araştırma | `combined_radar_replay_24h.py` | Yok |
| `birlesik-radar-geometri-taramasi-*.csv` | 6 | Araştırma | `combined_radar_replay_24h.py` + `analyze_unified_replay_csv.py` | Yok |
| `analysis_snapshots (2).sql` | 1 | Araştırma (yedek) | `combined_radar_replay_24h.py` | Yok |
| `velocity_candidates (2).sql` | 1 | Araştırma (yedek) | `combined_radar_replay_24h.py` | Yok |
| `monitoring_notifications.sql` | 1 | Araştırma | elle / rapor uçları | Yok |
| **Toplam** | **17** | | | |

## Öneri (uygulanmadı)

Denetim, bu dosyaların **silinmesini değil belgelenmesini** önerdi; ancak
kalıcı öneri şudur:

1. **Bu dosyalar `.gitignore`'a eklenmemeli** — araştırma geçmişi olarak
   versiyonlanmış kalıyorlar ve bu README onları belgeliyor.
2. Yeni replay/CSV çıktıları **`backend/outputs/`** altına yazılmalı
   (`outputs/` zaten `.gitignore`'da: satır 16).
3. `docs/` altına yalnız **yorumlanmış sonuç** (`.md`) konmalı, ham CSV/SQL
   değil.
4. Eğer silinmek istenirse: 17 dosyanın **hiçbir üretim bağımlılığı yoktur**
   (yukarıdaki "Okuyan kod" sütunu boş) — silmek güvenlidir. Ancak bu bir
   **ürün kararıdır** ve kullanıcının onayı gerekir.

## İlgili belgeler

- [`../backend/scripts/README.md`](../backend/scripts/README.md) — 93 Python script'inin hangilerinin kalıcı bağımlılık olduğu
- [`SISTEM_DENETIMI_2026-09-26.md`](SISTEM_DENETIMI_2026-09-26.md) — denetim raporu (§6 "Ölü kod / ölü ayar")
