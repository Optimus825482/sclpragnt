# MA BUY 30 günlük replay (CANLI sembol seçimiyle) — sinyal sonrası en yüksek yükseliş (2026-10-20 22:47)

Kapsam: son 30 gün, 277 (canlı seçim; evren 310) sembol, zaman dilimleri M5, M15, M30, H1. Kural ve parametreler canlı motorla aynı (SMA 7/20/99, StochRSI K ≤ 80 (1m hariç)).

**Ölçüt:** sinyal mumunun KAPANIŞINA göre, bir SONRAKİ sinyale (aynı sembol + TF) kadar görülen en yüksek `high` (MFE). Sonraki sinyali olmayan son sinyaller veri sonuna kadar ölçülür ve *açık uçlu* sayılır. 15 dk / 1 sa / 4 sa / 24 sa sütunları sabit ufuklardır, sonraki sinyalle sınırlanmaz.

## Özet (TF bazında)

| TF | Kural | Sinyal | Medyan MFE | Ortalama | P25 | P75 | ≥%1 | ≥%2 | ≥%3 | Hedefe dokunma | Zirveye medyan dk | Sonrakine medyan dk | Açık uçlu |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M5 | all | 1558 | 3.37% | 6.24% | 1.28% | 7.91% | 0.81 | 0.64 | 0.54 | 0.71 | 155.00 | 857.50 | 235 |
| M5 | fast_cross_mid | 1253 | 3.42% | 6.22% | 1.29% | 8.01% | 0.81 | 0.64 | 0.54 | 0.71 | 155 | 780 | 183 |
| M5 | mid_cross_slow | 306 | 3.28% | 6.27% | 1.25% | 7.68% | 0.82 | 0.62 | 0.52 | 0.70 | 160.00 | 1577.50 | 52 |
| M15 | all | 766 | 4.70% | 8.82% | 1.81% | 11.23% | 0.86 | 0.72 | 0.63 | 0.72 | 360.00 | 3495.00 | 196 |
| M15 | fast_cross_mid | 714 | 4.64% | 8.93% | 1.75% | 11.32% | 0.85 | 0.71 | 0.62 | 0.71 | 360.00 | 3060.00 | 178 |
| M15 | mid_cross_slow | 52 | 5.41% | 7.42% | 2.72% | 10.41% | 0.94 | 0.81 | 0.73 | 0.81 | 532.50 | 4327.50 | 18 |
| M30 | all | 353 | 6.24% | 12.87% | 2.98% | 14.74% | 0.92 | 0.84 | 0.74 | 0.80 | 840 | 7680 | 149 |
| M30 | fast_cross_mid | 279 | 6.52% | 13.73% | 2.99% | 14.85% | 0.91 | 0.84 | 0.75 | 0.81 | 750 | 7560 | 114 |
| M30 | mid_cross_slow | 75 | 5.51% | 9.96% | 2.91% | 14.44% | 0.96 | 0.84 | 0.75 | 0.79 | 1110 | 7770 | 35 |
| H1 | all | 158 | 8.59% | 14.71% | 3.42% | 19.74% | 0.93 | 0.85 | 0.78 | 0.78 | 1740.00 | 14220.00 | 98 |
| H1 | fast_cross_mid | 97 | 8.59% | 14.80% | 3.19% | 21.26% | 0.93 | 0.82 | 0.76 | 0.76 | 1680 | 14580 | 60 |
| H1 | mid_cross_slow | 61 | 8.59% | 14.56% | 4.02% | 18.21% | 0.93 | 0.89 | 0.80 | 0.80 | 1860 | 14220 | 38 |

## Sabit ufuklarda medyan en yüksek yükseliş

| TF | 15 dk | 1 sa | 4 sa | 24 sa |
|---|---:|---:|---:|---:|
| M5 | 0.50% (n=1558) | 1.11% (n=1557) | 1.99% (n=1550) | 4.36% (n=1527) |
| M15 | 0.51% (n=766) | 0.99% (n=765) | 1.93% (n=765) | 3.81% (n=744) |
| M30 | — | 1.09% (n=353) | 2.47% (n=353) | 4.31% (n=348) |
| H1 | — | 1.31% (n=158) | 2.32% (n=158) | 4.32% (n=155) |

## Sembol bazında sinyal sayısı

| Sembol | M5 | M15 | M30 | H1 | Toplam |
|---|---:|---:|---:|---:|---:|
| 0GTRY | 6 | 3 | 1 | 1 | 11 |
| 1000CATTRY | 3 | 0 | 1 | 0 | 4 |
| 2ZTRY | 5 | 4 | 2 | 0 | 11 |
| AAVETRY | 7 | 2 | 1 | 0 | 10 |
| ACETRY | 18 | 17 | 7 | 2 | 44 |
| ACHTRY | 5 | 1 | 1 | 0 | 7 |
| ACMTRY | 1 | 2 | 1 | 0 | 4 |
| ACTTRY | 4 | 3 | 3 | 1 | 11 |
| ADATRY | 9 | 4 | 1 | 1 | 15 |
| AEROTRY | 8 | 3 | 0 | 0 | 11 |
| AEVOTRY | 4 | 0 | 0 | 0 | 4 |
| AITRY | 5 | 4 | 4 | 0 | 13 |
| AIXBTTRY | 1 | 0 | 0 | 0 | 1 |
| ALGOTRY | 2 | 1 | 1 | 0 | 4 |
| ALICETRY | 10 | 3 | 1 | 1 | 15 |
| ALLOTRY | 6 | 0 | 1 | 0 | 7 |
| ALPINETRY | 1 | 1 | 0 | 1 | 3 |
| ALTTRY | 7 | 4 | 0 | 1 | 12 |
| AMPTRY | 16 | 12 | 6 | 3 | 37 |
| APETRY | 9 | 3 | 1 | 1 | 14 |
| API3TRY | 8 | 3 | 3 | 0 | 14 |
| APTTRY | 7 | 5 | 1 | 2 | 15 |
| ARBTRY | 7 | 5 | 1 | 1 | 14 |
| ARKMTRY | 6 | 1 | 1 | 0 | 8 |
| ARKTRY | 15 | 6 | 5 | 2 | 28 |
| ARPATRY | 5 | 1 | 0 | 1 | 7 |
| ARTRY | 3 | 2 | 1 | 2 | 8 |
| ASRTRY | 1 | 1 | 1 | 1 | 4 |
| ASTERTRY | 4 | 2 | 0 | 0 | 6 |
| ATMTRY | 0 | 1 | 0 | 1 | 2 |
| ATOMTRY | 3 | 0 | 0 | 0 | 3 |
| ATRY | 3 | 1 | 1 | 0 | 5 |
| ATTRY | 1 | 0 | 0 | 0 | 1 |
| AUDIOTRY | 17 | 6 | 3 | 0 | 26 |
| AVAXTRY | 18 | 4 | 2 | 2 | 26 |
| AVNTTRY | 2 | 1 | 0 | 1 | 4 |
| AXLTRY | 2 | 1 | 2 | 1 | 6 |
| AXSTRY | 3 | 2 | 1 | 0 | 6 |
| BABYTRY | 1 | 1 | 0 | 0 | 2 |
| BANKTRY | 1 | 1 | 1 | 0 | 3 |
| BARTRY | 0 | 0 | 0 | 1 | 1 |
| BBTRY | 9 | 4 | 1 | 1 | 15 |
| BCHTRY | 6 | 4 | 2 | 0 | 12 |
| BEAMXTRY | 8 | 4 | 3 | 3 | 18 |
| BELTRY | 1 | 0 | 0 | 0 | 1 |
| BERATRY | 6 | 2 | 1 | 0 | 9 |
| BIOTRY | 5 | 1 | 2 | 0 | 8 |
| BLURTRY | 2 | 2 | 0 | 0 | 4 |
| BMTTRY | 3 | 1 | 1 | 0 | 5 |
| BNBTRY | 2 | 0 | 0 | 0 | 2 |
| BOMETRY | 14 | 7 | 1 | 2 | 24 |
| BONKTRY | 15 | 5 | 1 | 1 | 22 |
| BTCTRY | 6 | 1 | 0 | 0 | 7 |
| CAKETRY | 2 | 0 | 0 | 0 | 2 |
| CETUSTRY | 4 | 0 | 3 | 0 | 7 |
| CFGTRY | 15 | 1 | 1 | 1 | 18 |
| CFXTRY | 3 | 3 | 1 | 0 | 7 |
| CHIPTRY | 19 | 7 | 3 | 3 | 32 |
| CKBTRY | 1 | 1 | 0 | 0 | 2 |
| COMPTRY | 3 | 0 | 0 | 0 | 3 |
| COTITRY | 7 | 5 | 0 | 1 | 13 |
| CRVTRY | 3 | 1 | 0 | 1 | 5 |
| CTRY | 1 | 0 | 0 | 0 | 1 |
| CYBERTRY | 2 | 2 | 0 | 1 | 5 |
| DASHTRY | 6 | 3 | 2 | 0 | 11 |
| DODOTRY | 14 | 6 | 8 | 1 | 29 |
| DOGETRY | 3 | 2 | 1 | 0 | 6 |
| DOGSTRY | 4 | 2 | 1 | 0 | 7 |
| DOLOTRY | 1 | 1 | 0 | 0 | 2 |
| DOTTRY | 0 | 0 | 0 | 1 | 1 |
| DYMTRY | 7 | 4 | 4 | 0 | 15 |
| EDENTRY | 5 | 2 | 1 | 1 | 9 |
| EDUTRY | 6 | 1 | 0 | 2 | 9 |
| EGLDTRY | 1 | 0 | 1 | 0 | 2 |
| EIGENTRY | 16 | 7 | 5 | 3 | 31 |
| ENATRY | 15 | 10 | 3 | 1 | 29 |
| ENJTRY | 3 | 3 | 2 | 0 | 8 |
| ENSOTRY | 0 | 0 | 1 | 0 | 1 |
| ENSTRY | 0 | 1 | 1 | 0 | 2 |
| ERATRY | 5 | 2 | 0 | 2 | 9 |
| ESPTRY | 6 | 2 | 3 | 0 | 11 |
| ETCTRY | 0 | 1 | 0 | 0 | 1 |
| ETHFITRY | 15 | 5 | 4 | 1 | 25 |
| ETHTRY | 3 | 0 | 1 | 0 | 4 |
| FETTRY | 21 | 5 | 5 | 2 | 33 |
| FFTRY | 2 | 2 | 1 | 0 | 5 |
| FIDATRY | 3 | 1 | 0 | 0 | 4 |
| FILTRY | 5 | 3 | 2 | 1 | 11 |
| FLOKITRY | 9 | 7 | 1 | 0 | 17 |
| FOGOTRY | 1 | 0 | 1 | 0 | 2 |
| FORMTRY | 5 | 1 | 1 | 0 | 7 |
| GALATRY | 5 | 3 | 2 | 2 | 12 |
| GENIUSTRY | 2 | 2 | 0 | 0 | 4 |
| GIGGLETRY | 4 | 2 | 1 | 0 | 7 |
| GMTTRY | 2 | 0 | 0 | 0 | 2 |
| GPSTRY | 2 | 1 | 0 | 0 | 3 |
| GRAMTRY | 2 | 3 | 1 | 2 | 8 |
| GRTTRY | 10 | 2 | 0 | 0 | 12 |
| GUNTRY | 2 | 0 | 0 | 0 | 2 |
| HBARTRY | 8 | 5 | 0 | 0 | 13 |
| HEITRY | 5 | 5 | 3 | 0 | 13 |
| HEMITRY | 5 | 5 | 1 | 1 | 12 |
| HUMATRY | 4 | 2 | 0 | 1 | 7 |
| HYPERTRY | 1 | 1 | 0 | 0 | 2 |
| HYPETRY | 3 | 2 | 1 | 0 | 6 |
| ICPTRY | 2 | 1 | 0 | 0 | 3 |
| IDTRY | 0 | 1 | 0 | 0 | 1 |
| INITTRY | 11 | 4 | 1 | 0 | 16 |
| INJTRY | 17 | 7 | 3 | 2 | 29 |
| IOTATRY | 4 | 3 | 0 | 0 | 7 |
| IOTRY | 5 | 2 | 0 | 0 | 7 |
| JASMYTRY | 1 | 0 | 0 | 0 | 1 |
| JTOTRY | 10 | 5 | 2 | 0 | 17 |
| JUPTRY | 5 | 4 | 0 | 0 | 9 |
| JUVTRY | 1 | 2 | 1 | 1 | 5 |
| KAITOTRY | 1 | 0 | 1 | 0 | 2 |
| KATTRY | 1 | 0 | 0 | 0 | 1 |
| KERNELTRY | 4 | 2 | 1 | 0 | 7 |
| KITETRY | 3 | 2 | 0 | 0 | 5 |
| KSMTRY | 2 | 0 | 0 | 0 | 2 |
| LATRY | 1 | 1 | 0 | 1 | 3 |
| LAZIOTRY | 13 | 10 | 3 | 3 | 29 |
| LDOTRY | 1 | 2 | 2 | 0 | 5 |
| LINEATRY | 5 | 0 | 0 | 0 | 5 |
| LINKTRY | 8 | 3 | 2 | 2 | 15 |
| LPTTRY | 7 | 3 | 0 | 2 | 12 |
| LTCTRY | 6 | 2 | 2 | 0 | 10 |
| LUMIATRY | 7 | 8 | 0 | 3 | 18 |
| LUNATRY | 3 | 3 | 0 | 0 | 6 |
| LUNCTRY | 1 | 0 | 1 | 0 | 2 |
| MAGICTRY | 13 | 7 | 2 | 1 | 23 |
| MANATRY | 1 | 1 | 0 | 2 | 4 |
| MANTATRY | 6 | 2 | 1 | 0 | 9 |
| MANTRATRY | 4 | 2 | 1 | 0 | 7 |
| MARSCOINTRY | 20 | 11 | 9 | 2 | 42 |
| MASKTRY | 1 | 0 | 0 | 0 | 1 |
| MAVTRY | 1 | 0 | 0 | 0 | 1 |
| MEGATRY | 7 | 3 | 1 | 0 | 11 |
| METISTRY | 3 | 0 | 1 | 0 | 4 |
| METRY | 1 | 0 | 0 | 0 | 1 |
| METTRY | 5 | 2 | 1 | 0 | 8 |
| MINATRY | 11 | 7 | 2 | 1 | 21 |
| MIRATRY | 3 | 1 | 0 | 0 | 4 |
| MITOTRY | 4 | 2 | 0 | 0 | 6 |
| MMTTRY | 1 | 1 | 0 | 0 | 2 |
| MOVRTRY | 21 | 10 | 5 | 1 | 37 |
| MUBARAKTRY | 34 | 20 | 10 | 6 | 70 |
| NEARTRY | 29 | 19 | 8 | 2 | 58 |
| NEOTRY | 1 | 0 | 0 | 0 | 1 |
| NIGHTTRY | 18 | 7 | 2 | 0 | 27 |
| NILTRY | 33 | 19 | 9 | 6 | 67 |
| NMRTRY | 13 | 6 | 3 | 1 | 23 |
| NOMTRY | 14 | 10 | 2 | 3 | 29 |
| NXPCTRY | 1 | 0 | 0 | 1 | 2 |
| OGNTRY | 7 | 4 | 1 | 0 | 12 |
| OGTRY | 0 | 1 | 0 | 0 | 1 |
| ONDOTRY | 11 | 5 | 3 | 1 | 20 |
| ONETRY | 6 | 5 | 3 | 4 | 18 |
| ONTTRY | 1 | 1 | 1 | 0 | 3 |
| OPGTRY | 9 | 4 | 1 | 1 | 15 |
| OPNTRY | 5 | 1 | 1 | 0 | 7 |
| OPTRY | 6 | 0 | 1 | 0 | 7 |
| ORCATRY | 6 | 5 | 0 | 0 | 11 |
| PARTITRY | 10 | 2 | 1 | 1 | 14 |
| PENDLETRY | 1 | 0 | 0 | 0 | 1 |
| PENGUTRY | 13 | 5 | 3 | 0 | 21 |
| PEPETRY | 24 | 9 | 1 | 1 | 35 |
| PHATRY | 15 | 7 | 4 | 2 | 28 |
| PIXELTRY | 4 | 1 | 0 | 1 | 6 |
| PLUMETRY | 11 | 6 | 1 | 0 | 18 |
| POLTRY | 4 | 1 | 0 | 0 | 5 |
| PORTALTRY | 2 | 0 | 2 | 0 | 4 |
| PORTOTRY | 1 | 0 | 1 | 0 | 2 |
| PROVETRY | 0 | 1 | 0 | 0 | 1 |
| PSGTRY | 1 | 1 | 0 | 1 | 3 |
| PUMPTRY | 27 | 14 | 8 | 3 | 52 |
| PYTHTRY | 22 | 11 | 6 | 1 | 40 |
| RADTRY | 10 | 4 | 2 | 1 | 17 |
| RARETRY | 11 | 6 | 4 | 0 | 21 |
| RAYTRY | 11 | 7 | 5 | 1 | 24 |
| REDTRY | 3 | 1 | 0 | 0 | 4 |
| RENDERTRY | 10 | 4 | 2 | 0 | 16 |
| RESOLVTRY | 4 | 0 | 0 | 0 | 4 |
| RETRY | 0 | 1 | 0 | 0 | 1 |
| REZTRY | 8 | 6 | 1 | 1 | 16 |
| ROSETRY | 7 | 4 | 2 | 1 | 14 |
| RSRTRY | 5 | 2 | 1 | 0 | 8 |
| RVNTRY | 3 | 2 | 0 | 1 | 6 |
| SAGATRY | 17 | 11 | 5 | 2 | 35 |
| SAHARATRY | 1 | 0 | 0 | 0 | 1 |
| SANDTRY | 7 | 5 | 5 | 3 | 20 |
| SANTOSTRY | 5 | 0 | 1 | 1 | 7 |
| SCRTRY | 6 | 3 | 1 | 0 | 10 |
| SEITRY | 14 | 7 | 2 | 0 | 23 |
| SENTTRY | 23 | 14 | 5 | 2 | 44 |
| SHELLTRY | 2 | 2 | 0 | 1 | 5 |
| SHIBTRY | 6 | 5 | 1 | 0 | 12 |
| SKLTRY | 4 | 2 | 3 | 1 | 10 |
| SKYTRY | 1 | 1 | 2 | 1 | 5 |
| SLPTRY | 2 | 0 | 0 | 0 | 2 |
| SNXTRY | 1 | 0 | 1 | 0 | 2 |
| SOLTRY | 4 | 2 | 0 | 0 | 6 |
| SOLVTRY | 1 | 1 | 0 | 0 | 2 |
| SOMITRY | 1 | 0 | 0 | 0 | 1 |
| SPELLTRY | 1 | 1 | 0 | 0 | 2 |
| SPKTRY | 2 | 2 | 0 | 0 | 4 |
| STOTRY | 1 | 0 | 0 | 1 | 2 |
| STRAXTRY | 4 | 2 | 1 | 0 | 7 |
| STRKTRY | 19 | 13 | 9 | 1 | 42 |
| STRY | 16 | 8 | 3 | 1 | 28 |
| STXTRY | 8 | 4 | 2 | 1 | 15 |
| SUITRY | 12 | 9 | 5 | 1 | 27 |
| SUPERTRY | 8 | 4 | 4 | 1 | 17 |
| SUSHITRY | 3 | 2 | 0 | 0 | 5 |
| SXTTRY | 3 | 1 | 0 | 0 | 4 |
| SYRUPTRY | 3 | 0 | 0 | 0 | 3 |
| TAOTRY | 10 | 5 | 1 | 1 | 17 |
| THETRY | 2 | 1 | 0 | 0 | 3 |
| TIATRY | 24 | 9 | 4 | 5 | 42 |
| TLMTRY | 3 | 1 | 0 | 0 | 4 |
| TNSRTRY | 1 | 0 | 0 | 0 | 1 |
| TOWNSTRY | 3 | 2 | 0 | 1 | 6 |
| TRBTRY | 2 | 1 | 1 | 0 | 4 |
| TRUMPTRY | 2 | 0 | 0 | 0 | 2 |
| TSTTRY | 7 | 3 | 2 | 1 | 13 |
| UMATRY | 2 | 2 | 3 | 0 | 7 |
| UNITRY | 1 | 3 | 2 | 1 | 7 |
| USUALTRY | 1 | 0 | 0 | 0 | 1 |
| VETTRY | 1 | 0 | 0 | 0 | 1 |
| VIRTUALTRY | 0 | 1 | 1 | 0 | 2 |
| WALTRY | 8 | 5 | 1 | 2 | 16 |
| WCTTRY | 2 | 1 | 0 | 0 | 3 |
| WIFTRY | 7 | 4 | 3 | 0 | 14 |
| WLDTRY | 24 | 9 | 7 | 5 | 45 |
| WLFITRY | 1 | 0 | 0 | 0 | 1 |
| WTRY | 8 | 3 | 2 | 0 | 13 |
| XAITRY | 9 | 4 | 1 | 1 | 15 |
| XAUTTRY | 1 | 1 | 0 | 0 | 2 |
| XECTRY | 6 | 2 | 1 | 0 | 9 |
| XLMTRY | 4 | 4 | 2 | 0 | 10 |
| XPLTRY | 6 | 1 | 3 | 0 | 10 |
| XRPTRY | 10 | 3 | 0 | 0 | 13 |
| XVGTRY | 2 | 2 | 0 | 0 | 4 |
| YBTRY | 1 | 0 | 0 | 0 | 1 |
| ZKTRY | 9 | 8 | 1 | 0 | 18 |
| ZROTRY | 22 | 10 | 4 | 1 | 37 |

## En yüksek 10 yükseliş

| Sembol | TF | Kural | Sinyal zamanı | Fiyat | MFE | Zirveye dk | Sonrakine dk | Açık uçlu |
|---|---|---|---|---:|---:|---:|---:|---|
| MAGICTRY | M30 | fast_cross_mid | 01.10 19:30 | 2.66 | 203.01% | 12150 | 15540 | hayır |
| OGNTRY | M15 | fast_cross_mid | 06.10 02:00 | 1.072 | 132.18% | 3975 | 3990 | hayır |
| SAGATRY | H1 | fast_cross_mid | 21.09 20:00 | 1.944 | 127.47% | 4740 | 21840 | hayır |
| SAGATRY | M30 | fast_cross_mid | 22.09 08:30 | 2.045 | 116.23% | 3990 | 12060 | hayır |
| NILTRY | M30 | fast_cross_mid | 21.09 09:00 | 3.457 | 111.17% | 4290 | 13230 | hayır |
| MAGICTRY | M15 | fast_cross_mid | 09.10 17:00 | 3.86 | 108.81% | 795 | 2865 | hayır |
| OGNTRY | M5 | mid_cross_slow | 06.10 12:15 | 1.096 | 106.30% | 3110 | 3200 | hayır |
| STRKTRY | M30 | fast_cross_mid | 09.10 04:30 | 2.955 | 106.29% | 2940 | 3210 | hayır |
| MUBARAKTRY | M30 | fast_cross_mid | 22.09 04:30 | 2.187 | 94.74% | 1050 | 5340 | hayır |
| SAGATRY | M15 | fast_cross_mid | 23.09 14:45 | 2.274 | 94.46% | 2175 | 7200 | hayır |

## En zayıf 10 sinyal

| Sembol | TF | Kural | Sinyal zamanı | Fiyat | MFE | Zirveye dk | Sonrakine dk | Açık uçlu |
|---|---|---|---|---:|---:|---:|---:|---|
| AAVETRY | M5 | mid_cross_slow | 01.10 17:35 | 8306 | -0.41% | 70 | 70 | hayır |
| LUMIATRY | M15 | fast_cross_mid | 13.10 17:00 | 5.508 | -0.33% | 15 | 2670 | hayır |
| PHATRY | M30 | fast_cross_mid | 20.10 09:00 | 3.28 | -0.30% | 30 | 780 | evet |
| SUSHITRY | M5 | fast_cross_mid | 23.09 13:55 | 13.65 | -0.29% | 5 | 9160 | hayır |
| SENTTRY | M5 | mid_cross_slow | 24.09 03:40 | 1.0479 | -0.25% | 5 | 75 | hayır |
| UNITRY | M15 | fast_cross_mid | 01.10 17:15 | 452 | -0.20% | 15 | 270 | hayır |
| DASHTRY | M5 | mid_cross_slow | 27.09 09:00 | 3555 | -0.20% | 5 | 140 | hayır |
| SANTOSTRY | M5 | fast_cross_mid | 07.10 18:40 | 26.03 | -0.19% | 5 | 355 | hayır |
| AUDIOTRY | M30 | fast_cross_mid | 17.10 16:30 | 0.7875 | -0.18% | 30 | 4650 | evet |
| FETTRY | M30 | fast_cross_mid | 12.10 08:00 | 11.89 | -0.17% | 30 | 12360 | evet |

## Dürüst sınırlar

- Mum verisi Binance TR herkese açık klines ucundan; sinyal mumu KAPANIŞI giriş fiyatı sayılır (spread/kayma yok).
- MFE "en yüksek görülen fiyat"tır, gerçekleşmiş kazanç değildir; çıkış kuralı simüle edilmemiştir.
- Açık uçlu sinyaller veri sonuna kadar ölçüldüğü için gerçek MFE daha yüksek olabilir.
- Sembol evreni raporun üretildiği andaki aktif + izlenen listedir; geçmişte aktif olup çıkanlar yoktur.

## Canlı sembol seçimi (yeniden üretim)

- Her 600 sn: 24 sa yükselenler ilk 50 (5m mumlardan: son kapanış / 24 sa önceki kapanış; 24 sa quote hacim). Her 3600 sn: aktivite filtresi (hacim ≥ 1,000,000 TL, 15 dk aralık ≥ %0.05, ATR ≥ 0.0012, hacim oranı ≥ 0.5, M1 düz mum filtresi açık [5/4, 30/25], kapsamlı pasiflik analizi).
- Saatlik anlık görüntü: 720; izlenen evrene giren sembol: 310; saat başına AKTİF: ortalama 12.2, en az 1, en çok 28; aktif küme boş olup izlenen listeye düşülen saat: 0.
- Aktivite kararları: {'PASSIVE': 27222, 'ACTIVE': 8778}. Sinyal elemesi: 58625 ham sinyalden 2835 tanesi o anda taranan sembolde (kalanı sistem görmezdi).

| Sembol | Aktif saat | Sinyal |
|---|---:|---:|
| MUBARAKTRY | 186 | 70 |
| NILTRY | 182 | 67 |
| NEARTRY | 149 | 58 |
| SENTTRY | 137 | 44 |
| WLDTRY | 136 | 45 |
| TIATRY | 133 | 42 |
| PUMPTRY | 127 | 52 |
| STRKTRY | 125 | 42 |
| ZROTRY | 114 | 37 |
| MARSCOINTRY | 113 | 42 |
| ACETRY | 111 | 44 |
| NOMTRY | 104 | 29 |
| PHATRY | 101 | 28 |
| SAGATRY | 99 | 35 |
| EIGENTRY | 99 | 31 |
| AMPTRY | 98 | 37 |
| MOVRTRY | 97 | 37 |
| PYTHTRY | 95 | 40 |
| ENATRY | 92 | 29 |
| CHIPTRY | 92 | 32 |

Sadeleştirmeler: açık paper pozisyonlarının evrene eklenmesi yok; ticker `priceChangePercent` yerine 5m kapanış oranı; `_m1_activity_features` karara girmediği için hesaplanmadı; aktivite kararı yalnız izlenen sembollerde (canlıda izlenmeyen sembolün 5m serisi olmadığından WARMING kalır).
