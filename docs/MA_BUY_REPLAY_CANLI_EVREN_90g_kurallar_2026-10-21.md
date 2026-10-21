# MA BUY 90 günlük replay (CANLI sembol seçimiyle) — sinyal sonrası en yüksek yükseliş (2026-10-21 00:21)

Kapsam: son 90 gün, 303 (canlı seçim; evren 310) sembol, zaman dilimleri M5, M15, M30, H1. Kural ve parametreler canlı motorla aynı (SMA 7/20/99, StochRSI K ≤ 80 (1m hariç)).

**Ölçüt:** sinyal mumunun KAPANIŞINA göre, bir SONRAKİ sinyale (aynı sembol + TF) kadar görülen en yüksek `high` (MFE). Sonraki sinyali olmayan son sinyaller veri sonuna kadar ölçülür ve *açık uçlu* sayılır. 15 dk / 1 sa / 4 sa / 24 sa sütunları sabit ufuklardır, sonraki sinyalle sınırlanmaz.

## Özet (TF bazında)

| TF | Kural | Sinyal | Medyan MFE | Ortalama | P25 | P75 | ≥%1 | ≥%2 | ≥%3 | Hedefe dokunma | Zirveye medyan dk | Sonrakine medyan dk | Açık uçlu |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M5 | all | 4517 | 3.98% | 7.92% | 1.37% | 10.07% | 0.81 | 0.67 | 0.57 | 0.73 | 175 | 765 | 288 |
| M5 | fast_cross_mid | 3685 | 3.98% | 7.90% | 1.34% | 10.03% | 0.81 | 0.66 | 0.57 | 0.73 | 165 | 700 | 228 |
| M5 | mid_cross_slow | 836 | 3.98% | 8.05% | 1.51% | 10.34% | 0.84 | 0.67 | 0.57 | 0.75 | 230.00 | 1485.00 | 60 |
| M15 | all | 297 | 18.50% | 29.61% | 7.34% | 40.92% | 0.94 | 0.90 | 0.87 | 0.90 | 2700 | 19020 | 132 |
| M15 | fast_cross_mid | 285 | 18.50% | 29.84% | 7.22% | 41.02% | 0.94 | 0.90 | 0.86 | 0.90 | 2700 | 19020 | 126 |
| M15 | mid_cross_slow | 12 | 16.88% | 24.26% | 9.26% | 31.44% | 1.00 | 1.00 | 1.00 | 1.00 | 1957.50 | 22147.50 | 6 |
| M30 | all | 577 | 14.64% | 24.91% | 5.18% | 33.24% | 0.95 | 0.90 | 0.84 | 0.87 | 2820 | 14730 | 195 |
| M30 | fast_cross_mid | 538 | 15.04% | 25.76% | 5.36% | 34.37% | 0.95 | 0.90 | 0.85 | 0.88 | 2835.00 | 14280.00 | 180 |
| M30 | mid_cross_slow | 41 | 10.58% | 14.36% | 4.17% | 15.71% | 0.93 | 0.88 | 0.78 | 0.83 | 1500 | 17520 | 15 |
| H1 | all | 55 | 31.21% | 44.82% | 14.33% | 59.16% | 0.98 | 0.96 | 0.95 | 0.95 | 17340 | 54120 | 48 |
| H1 | fast_cross_mid | 41 | 34.63% | 48.67% | 17.77% | 66.73% | 0.98 | 0.95 | 0.95 | 0.95 | 16380 | 57780 | 36 |
| H1 | mid_cross_slow | 14 | 18.52% | 33.56% | 6.78% | 50.79% | 1.00 | 1.00 | 0.93 | 0.93 | 22200.00 | 47250.00 | 12 |

## Sabit ufuklarda medyan en yüksek yükseliş

| TF | 15 dk | 1 sa | 4 sa | 24 sa |
|---|---:|---:|---:|---:|
| M5 | 0.47% (n=4517) | 1.08% (n=4516) | 2.10% (n=4509) | 4.92% (n=4486) |
| M15 | 0.76% (n=297) | 1.61% (n=297) | 3.07% (n=297) | 6.63% (n=296) |
| M30 | — | 1.12% (n=577) | 2.55% (n=577) | 4.74% (n=574) |
| H1 | — | 0.87% (n=55) | 1.78% (n=55) | 2.92% (n=55) |

## Sembol bazında sinyal sayısı

| Sembol | M5 | M15 | M30 | H1 | Toplam |
|---|---:|---:|---:|---:|---:|
| 0GTRY | 26 | 2 | 1 | 0 | 29 |
| 1000CATTRY | 7 | 0 | 2 | 0 | 9 |
| 1000SATSTRY | 3 | 1 | 1 | 0 | 5 |
| 2ZTRY | 10 | 0 | 1 | 0 | 11 |
| AAVETRY | 22 | 0 | 3 | 0 | 25 |
| ACETRY | 51 | 5 | 5 | 2 | 63 |
| ACHTRY | 8 | 1 | 4 | 0 | 13 |
| ACMTRY | 2 | 1 | 0 | 0 | 3 |
| ACTTRY | 15 | 0 | 2 | 0 | 17 |
| ADATRY | 24 | 0 | 4 | 0 | 28 |
| AEROTRY | 17 | 0 | 0 | 0 | 17 |
| AEVOTRY | 8 | 1 | 1 | 0 | 10 |
| AIGENSYNTRY | 6 | 0 | 0 | 0 | 6 |
| AITRY | 6 | 0 | 3 | 0 | 9 |
| AIXBTTRY | 2 | 0 | 1 | 0 | 3 |
| ALGOTRY | 2 | 1 | 2 | 0 | 5 |
| ALICETRY | 22 | 0 | 1 | 0 | 23 |
| ALLOTRY | 32 | 3 | 4 | 1 | 40 |
| ALPINETRY | 5 | 0 | 0 | 0 | 5 |
| ALTTRY | 7 | 1 | 0 | 0 | 8 |
| AMPTRY | 21 | 3 | 3 | 0 | 27 |
| ANIMETRY | 1 | 0 | 0 | 0 | 1 |
| ANKRTRY | 5 | 0 | 0 | 0 | 5 |
| APETRY | 13 | 0 | 0 | 0 | 13 |
| API3TRY | 13 | 0 | 4 | 0 | 17 |
| APTTRY | 12 | 0 | 0 | 0 | 12 |
| ARBTRY | 28 | 2 | 3 | 0 | 33 |
| ARKMTRY | 9 | 1 | 2 | 0 | 12 |
| ARKTRY | 28 | 2 | 5 | 1 | 36 |
| ARPATRY | 10 | 0 | 1 | 0 | 11 |
| ARTRY | 17 | 0 | 1 | 0 | 18 |
| ASRTRY | 1 | 0 | 1 | 0 | 2 |
| ASTERTRY | 16 | 1 | 1 | 0 | 18 |
| ATMTRY | 14 | 1 | 0 | 1 | 16 |
| ATOMTRY | 6 | 0 | 0 | 0 | 6 |
| ATRY | 4 | 0 | 1 | 0 | 5 |
| ATTRY | 1 | 0 | 0 | 0 | 1 |
| AUCTIONTRY | 4 | 0 | 0 | 0 | 4 |
| AUDIOTRY | 19 | 0 | 3 | 0 | 22 |
| AVAXTRY | 34 | 0 | 2 | 0 | 36 |
| AVNTTRY | 6 | 2 | 0 | 0 | 8 |
| AXLTRY | 2 | 0 | 1 | 0 | 3 |
| AXSTRY | 3 | 0 | 1 | 0 | 4 |
| BABYTRY | 3 | 0 | 0 | 0 | 3 |
| BANKTRY | 37 | 6 | 6 | 1 | 50 |
| BARDTRY | 6 | 0 | 1 | 0 | 7 |
| BARTRY | 2 | 0 | 2 | 0 | 4 |
| BBTRY | 22 | 2 | 3 | 0 | 27 |
| BCHTRY | 9 | 0 | 1 | 0 | 10 |
| BEAMXTRY | 10 | 0 | 2 | 1 | 13 |
| BELTRY | 3 | 0 | 0 | 1 | 4 |
| BERATRY | 18 | 0 | 3 | 0 | 21 |
| BIOTRY | 21 | 1 | 2 | 0 | 24 |
| BLURTRY | 3 | 0 | 0 | 0 | 3 |
| BMTTRY | 22 | 3 | 1 | 0 | 26 |
| BNBTRY | 8 | 0 | 0 | 0 | 8 |
| BOMETRY | 68 | 5 | 6 | 2 | 81 |
| BONKTRY | 40 | 1 | 1 | 1 | 43 |
| BTCTRY | 15 | 0 | 0 | 0 | 15 |
| CAKETRY | 8 | 0 | 0 | 0 | 8 |
| CATITRY | 6 | 1 | 3 | 0 | 10 |
| CELOTRY | 1 | 0 | 0 | 0 | 1 |
| CETUSTRY | 8 | 0 | 1 | 0 | 9 |
| CFGTRY | 36 | 1 | 5 | 0 | 42 |
| CFXTRY | 5 | 0 | 1 | 0 | 6 |
| CHIPTRY | 71 | 6 | 7 | 0 | 84 |
| CHZTRY | 1 | 0 | 0 | 0 | 1 |
| CKBTRY | 2 | 0 | 0 | 0 | 2 |
| COMPTRY | 3 | 0 | 0 | 0 | 3 |
| COTITRY | 59 | 6 | 8 | 1 | 74 |
| COWTRY | 5 | 0 | 0 | 0 | 5 |
| CRVTRY | 14 | 0 | 4 | 1 | 19 |
| CTRY | 20 | 1 | 2 | 1 | 24 |
| CYBERTRY | 2 | 1 | 0 | 0 | 3 |
| DASHTRY | 27 | 1 | 6 | 0 | 34 |
| DODOTRY | 53 | 4 | 15 | 1 | 73 |
| DOGETRY | 15 | 0 | 3 | 1 | 19 |
| DOGSTRY | 15 | 2 | 2 | 0 | 19 |
| DOLOTRY | 8 | 1 | 0 | 0 | 9 |
| DOTTRY | 2 | 0 | 1 | 0 | 3 |
| DYDXTRY | 2 | 0 | 0 | 0 | 2 |
| DYMTRY | 15 | 0 | 3 | 0 | 18 |
| EDENTRY | 41 | 3 | 2 | 0 | 46 |
| EDUTRY | 7 | 0 | 0 | 1 | 8 |
| EGLDTRY | 6 | 1 | 0 | 0 | 7 |
| EIGENTRY | 35 | 1 | 5 | 1 | 42 |
| ENATRY | 72 | 4 | 11 | 1 | 88 |
| ENJTRY | 5 | 1 | 3 | 0 | 9 |
| ENSOTRY | 8 | 1 | 1 | 0 | 10 |
| ENSTRY | 2 | 0 | 1 | 0 | 3 |
| ERATRY | 10 | 1 | 0 | 0 | 11 |
| ESPTRY | 52 | 2 | 9 | 0 | 63 |
| ETCTRY | 2 | 0 | 0 | 0 | 2 |
| ETHFITRY | 47 | 4 | 8 | 0 | 59 |
| ETHTRY | 18 | 0 | 3 | 0 | 21 |
| EULTRY | 19 | 3 | 1 | 0 | 23 |
| FETTRY | 45 | 3 | 5 | 1 | 54 |
| FFTRY | 29 | 4 | 3 | 1 | 37 |
| FIDATRY | 10 | 0 | 2 | 0 | 12 |
| FILTRY | 19 | 0 | 3 | 1 | 23 |
| FLOKITRY | 21 | 0 | 3 | 0 | 24 |
| FOGOTRY | 1 | 0 | 0 | 0 | 1 |
| FORMTRY | 16 | 2 | 3 | 0 | 21 |
| FTRY | 5 | 0 | 0 | 0 | 5 |
| GALATRY | 17 | 1 | 1 | 0 | 19 |
| GENIUSTRY | 9 | 2 | 2 | 0 | 13 |
| GIGGLETRY | 34 | 2 | 5 | 0 | 41 |
| GMTTRY | 2 | 0 | 0 | 0 | 2 |
| GPSTRY | 18 | 0 | 3 | 0 | 21 |
| GRAMTRY | 8 | 0 | 0 | 0 | 8 |
| GRTTRY | 14 | 1 | 0 | 0 | 15 |
| GTRY | 7 | 1 | 0 | 0 | 8 |
| GUNTRY | 4 | 0 | 0 | 0 | 4 |
| HAEDALTRY | 1 | 0 | 0 | 0 | 1 |
| HBARTRY | 14 | 0 | 0 | 0 | 14 |
| HEITRY | 57 | 6 | 10 | 0 | 73 |
| HEMITRY | 60 | 6 | 8 | 1 | 75 |
| HIVETRY | 2 | 0 | 0 | 0 | 2 |
| HMSTRTRY | 8 | 0 | 1 | 1 | 10 |
| HOLOTRY | 13 | 0 | 1 | 0 | 14 |
| HOMETRY | 25 | 2 | 6 | 0 | 33 |
| HOTTRY | 3 | 0 | 1 | 0 | 4 |
| HUMATRY | 7 | 0 | 0 | 0 | 7 |
| HYPERTRY | 3 | 0 | 0 | 0 | 3 |
| HYPETRY | 3 | 0 | 1 | 0 | 4 |
| ICPTRY | 3 | 0 | 0 | 0 | 3 |
| IDTRY | 1 | 0 | 0 | 0 | 1 |
| INITTRY | 16 | 0 | 1 | 0 | 17 |
| INJTRY | 59 | 2 | 6 | 2 | 69 |
| IOTATRY | 5 | 2 | 0 | 0 | 7 |
| IOTRY | 8 | 0 | 0 | 0 | 8 |
| JASMYTRY | 4 | 0 | 1 | 0 | 5 |
| JTOTRY | 27 | 1 | 5 | 0 | 33 |
| JUPTRY | 7 | 0 | 3 | 0 | 10 |
| JUVTRY | 1 | 0 | 0 | 0 | 1 |
| KAITOTRY | 31 | 1 | 2 | 0 | 34 |
| KATTRY | 11 | 1 | 3 | 0 | 15 |
| KERNELTRY | 4 | 0 | 1 | 0 | 5 |
| KITETRY | 20 | 1 | 0 | 0 | 21 |
| KSMTRY | 3 | 0 | 0 | 0 | 3 |
| LATRY | 21 | 1 | 5 | 0 | 27 |
| LAZIOTRY | 13 | 2 | 3 | 0 | 18 |
| LDOTRY | 12 | 0 | 2 | 0 | 14 |
| LINEATRY | 7 | 0 | 0 | 0 | 7 |
| LINKTRY | 12 | 0 | 2 | 0 | 14 |
| LISTATRY | 4 | 0 | 0 | 0 | 4 |
| LPTTRY | 10 | 2 | 1 | 0 | 13 |
| LTCTRY | 6 | 0 | 2 | 0 | 8 |
| LUMIATRY | 17 | 1 | 0 | 1 | 19 |
| LUNATRY | 11 | 0 | 2 | 0 | 13 |
| LUNCTRY | 4 | 0 | 1 | 0 | 5 |
| MAGICTRY | 13 | 1 | 1 | 0 | 15 |
| MANATRY | 1 | 0 | 0 | 0 | 1 |
| MANTATRY | 6 | 0 | 1 | 0 | 7 |
| MANTRATRY | 11 | 0 | 1 | 0 | 12 |
| MARSCOINTRY | 34 | 8 | 4 | 1 | 47 |
| MASKTRY | 2 | 0 | 0 | 0 | 2 |
| MAVTRY | 3 | 0 | 0 | 0 | 3 |
| MEGATRY | 19 | 0 | 3 | 0 | 22 |
| METISTRY | 5 | 0 | 1 | 0 | 6 |
| METRY | 7 | 0 | 0 | 0 | 7 |
| METTRY | 14 | 0 | 0 | 1 | 15 |
| MINATRY | 23 | 2 | 2 | 0 | 27 |
| MIRATRY | 9 | 0 | 1 | 0 | 10 |
| MITOTRY | 13 | 0 | 1 | 0 | 14 |
| MMTTRY | 29 | 1 | 4 | 2 | 36 |
| MORPHOTRY | 6 | 0 | 0 | 0 | 6 |
| MOVRTRY | 29 | 5 | 5 | 0 | 39 |
| MUBARAKTRY | 76 | 8 | 9 | 0 | 93 |
| NEARTRY | 62 | 5 | 5 | 1 | 73 |
| NEIROTRY | 11 | 2 | 1 | 0 | 14 |
| NEOTRY | 1 | 0 | 0 | 0 | 1 |
| NIGHTTRY | 25 | 3 | 2 | 0 | 30 |
| NILTRY | 66 | 6 | 6 | 1 | 79 |
| NMRTRY | 13 | 1 | 2 | 0 | 16 |
| NOMTRY | 19 | 3 | 2 | 0 | 24 |
| NOTTRY | 9 | 1 | 1 | 0 | 11 |
| NXPCTRY | 2 | 0 | 1 | 0 | 3 |
| OGNTRY | 10 | 1 | 1 | 0 | 12 |
| OGTRY | 2 | 0 | 0 | 0 | 2 |
| ONDOTRY | 26 | 1 | 2 | 1 | 30 |
| ONETRY | 22 | 7 | 4 | 1 | 34 |
| ONTTRY | 11 | 1 | 5 | 1 | 18 |
| OPENTRY | 14 | 0 | 2 | 0 | 16 |
| OPGTRY | 12 | 0 | 2 | 0 | 14 |
| OPNTRY | 12 | 0 | 1 | 0 | 13 |
| OPTRY | 8 | 0 | 2 | 0 | 10 |
| ORCATRY | 9 | 3 | 1 | 0 | 13 |
| ORDITRY | 20 | 1 | 1 | 0 | 22 |
| PARTITRY | 11 | 0 | 0 | 0 | 11 |
| PAXGTRY | 1 | 0 | 0 | 0 | 1 |
| PENDLETRY | 4 | 0 | 0 | 0 | 4 |
| PENGUTRY | 36 | 1 | 11 | 0 | 48 |
| PEOPLETRY | 7 | 2 | 0 | 0 | 9 |
| PEPETRY | 42 | 0 | 3 | 0 | 45 |
| PHATRY | 18 | 6 | 2 | 0 | 26 |
| PIXELTRY | 8 | 0 | 0 | 1 | 9 |
| PLUMETRY | 18 | 0 | 0 | 0 | 18 |
| PNUTTRY | 4 | 0 | 0 | 0 | 4 |
| POLTRY | 16 | 1 | 2 | 0 | 19 |
| POLYXTRY | 1 | 0 | 0 | 0 | 1 |
| PORTALTRY | 56 | 7 | 8 | 1 | 72 |
| PORTOTRY | 3 | 1 | 0 | 0 | 4 |
| PSGTRY | 1 | 0 | 0 | 0 | 1 |
| PUMPTRY | 95 | 7 | 12 | 1 | 115 |
| PYTHTRY | 32 | 2 | 3 | 0 | 37 |
| RADTRY | 13 | 3 | 1 | 0 | 17 |
| RARETRY | 18 | 1 | 4 | 0 | 23 |
| RAYTRY | 24 | 2 | 3 | 2 | 31 |
| REDTRY | 8 | 0 | 0 | 0 | 8 |
| RENDERTRY | 11 | 0 | 2 | 0 | 13 |
| RESOLVTRY | 12 | 0 | 0 | 1 | 13 |
| RETRY | 35 | 1 | 1 | 1 | 38 |
| REZTRY | 28 | 2 | 1 | 0 | 31 |
| ROBOTRY | 12 | 1 | 4 | 0 | 17 |
| ROSETRY | 15 | 1 | 6 | 1 | 23 |
| RSRTRY | 5 | 0 | 1 | 0 | 6 |
| RVNTRY | 8 | 0 | 1 | 0 | 9 |
| SAGATRY | 58 | 7 | 6 | 1 | 72 |
| SAHARATRY | 14 | 0 | 1 | 2 | 17 |
| SANDTRY | 9 | 1 | 5 | 0 | 15 |
| SANTOSTRY | 12 | 0 | 0 | 1 | 13 |
| SAPIENTRY | 10 | 0 | 0 | 0 | 10 |
| SCRTRY | 15 | 0 | 3 | 0 | 18 |
| SEITRY | 16 | 2 | 2 | 0 | 20 |
| SENTTRY | 43 | 0 | 4 | 1 | 48 |
| SHELLTRY | 2 | 0 | 0 | 0 | 2 |
| SHIBTRY | 22 | 1 | 3 | 0 | 26 |
| SKLTRY | 4 | 1 | 3 | 0 | 8 |
| SKYTRY | 2 | 0 | 2 | 0 | 4 |
| SLPTRY | 6 | 0 | 0 | 0 | 6 |
| SNXTRY | 2 | 0 | 1 | 0 | 3 |
| SOLTRY | 17 | 0 | 2 | 0 | 19 |
| SOLVTRY | 10 | 1 | 1 | 0 | 12 |
| SOMITRY | 7 | 0 | 0 | 0 | 7 |
| SOPHTRY | 8 | 2 | 1 | 0 | 11 |
| SPELLTRY | 1 | 0 | 1 | 0 | 2 |
| SPKTRY | 14 | 0 | 1 | 0 | 15 |
| STOTRY | 10 | 0 | 1 | 1 | 12 |
| STRAXTRY | 8 | 0 | 0 | 0 | 8 |
| STRKTRY | 40 | 4 | 7 | 0 | 51 |
| STRY | 19 | 0 | 3 | 0 | 22 |
| STXTRY | 32 | 4 | 3 | 0 | 39 |
| SUITRY | 25 | 0 | 4 | 0 | 29 |
| SUPERTRY | 12 | 1 | 3 | 0 | 16 |
| SUSHITRY | 6 | 1 | 0 | 1 | 8 |
| SXTTRY | 8 | 1 | 0 | 0 | 9 |
| SYRUPTRY | 9 | 1 | 1 | 0 | 11 |
| TAOTRY | 18 | 0 | 1 | 0 | 19 |
| THETATRY | 7 | 1 | 1 | 0 | 9 |
| THETRY | 18 | 0 | 1 | 0 | 19 |
| TIATRY | 48 | 2 | 6 | 0 | 56 |
| TLMTRY | 25 | 0 | 7 | 0 | 32 |
| TNSRTRY | 5 | 1 | 0 | 0 | 6 |
| TOWNSTRY | 3 | 0 | 0 | 1 | 4 |
| TRBTRY | 5 | 1 | 2 | 0 | 8 |
| TREETRY | 3 | 0 | 3 | 0 | 6 |
| TRUMPTRY | 21 | 3 | 4 | 0 | 28 |
| TSTTRY | 43 | 4 | 6 | 2 | 55 |
| TURBOTRY | 2 | 1 | 0 | 0 | 3 |
| TWTTRY | 8 | 0 | 2 | 0 | 10 |
| UMATRY | 2 | 0 | 2 | 0 | 4 |
| UNITRY | 33 | 2 | 5 | 0 | 40 |
| USUALTRY | 13 | 2 | 1 | 0 | 16 |
| VANATRY | 2 | 0 | 0 | 0 | 2 |
| VETTRY | 12 | 1 | 3 | 0 | 16 |
| VIRTUALTRY | 4 | 0 | 0 | 0 | 4 |
| WALTRY | 9 | 1 | 1 | 0 | 11 |
| WCTTRY | 3 | 0 | 0 | 0 | 3 |
| WIFTRY | 14 | 2 | 5 | 0 | 21 |
| WLDTRY | 55 | 1 | 10 | 0 | 66 |
| WLFITRY | 4 | 0 | 0 | 0 | 4 |
| WTRY | 9 | 2 | 1 | 0 | 12 |
| XAITRY | 22 | 2 | 3 | 0 | 27 |
| XAUTTRY | 5 | 0 | 0 | 0 | 5 |
| XECTRY | 12 | 1 | 1 | 0 | 14 |
| XLMTRY | 16 | 0 | 3 | 1 | 20 |
| XPLTRY | 34 | 0 | 3 | 0 | 37 |
| XRPTRY | 32 | 0 | 4 | 0 | 36 |
| XTZTRY | 5 | 1 | 1 | 0 | 7 |
| XVGTRY | 9 | 1 | 0 | 0 | 10 |
| YBTRY | 2 | 0 | 0 | 0 | 2 |
| ZBTTRY | 10 | 2 | 2 | 0 | 14 |
| ZILTRY | 10 | 1 | 1 | 0 | 12 |
| ZKCTRY | 2 | 1 | 0 | 0 | 3 |
| ZKPTRY | 9 | 0 | 4 | 0 | 13 |
| ZKTRY | 17 | 0 | 1 | 0 | 18 |
| ZROTRY | 26 | 4 | 1 | 0 | 31 |

## En yüksek 10 yükseliş

| Sembol | TF | Kural | Sinyal zamanı | Fiyat | MFE | Zirveye dk | Sonrakine dk | Açık uçlu |
|---|---|---|---|---:|---:|---:|---:|---|
| ACETRY | M30 | fast_cross_mid | 06.08 02:00 | 3.429 | 427.56% | 12900 | 65550 | hayır |
| HEITRY | M15 | fast_cross_mid | 24.07 07:15 | 5.011 | 410.88% | 19005 | 20940 | hayır |
| MAGICTRY | M30 | fast_cross_mid | 01.10 19:30 | 2.66 | 203.01% | 12150 | 27510 | evet |
| LUMIATRY | H1 | fast_cross_mid | 24.07 22:00 | 3.295 | 173.14% | 112920 | 126660 | evet |
| HEMITRY | M30 | fast_cross_mid | 27.08 09:30 | 0.3992 | 172.52% | 8400 | 9930 | hayır |
| NILTRY | H1 | fast_cross_mid | 30.08 14:00 | 2.7 | 170.37% | 35640 | 73860 | evet |
| SOPHTRY | M15 | fast_cross_mid | 07.09 22:30 | 0.253 | 166.40% | 855 | 6765 | hayır |
| MOVRTRY | M30 | fast_cross_mid | 04.09 17:00 | 38.7 | 160.21% | 37170 | 37680 | hayır |
| ACETRY | M15 | fast_cross_mid | 07.08 10:30 | 7.231 | 150.17% | 10965 | 16605 | hayır |
| MMTTRY | M30 | fast_cross_mid | 28.07 12:00 | 8.83 | 150.06% | 4410 | 74190 | hayır |

## En zayıf 10 sinyal

| Sembol | TF | Kural | Sinyal zamanı | Fiyat | MFE | Zirveye dk | Sonrakine dk | Açık uçlu |
|---|---|---|---|---:|---:|---:|---:|---|
| PEOPLETRY | M5 | fast_cross_mid | 02.08 16:30 | 0.339 | -0.89% | 5 | 15 | hayır |
| SUSHITRY | M5 | mid_cross_slow | 06.09 05:15 | 12.62 | -0.48% | 5 | 780 | hayır |
| AAVETRY | M5 | mid_cross_slow | 01.10 17:35 | 8306 | -0.41% | 70 | 70 | hayır |
| LUMIATRY | M15 | fast_cross_mid | 13.10 17:00 | 5.508 | -0.33% | 15 | 10395 | evet |
| ORDITRY | M5 | fast_cross_mid | 08.09 14:00 | 216.1 | -0.32% | 5 | 40 | hayır |
| LATRY | M5 | fast_cross_mid | 31.08 18:10 | 3.09 | -0.32% | 5 | 650 | hayır |
| HOLOTRY | M5 | fast_cross_mid | 29.08 02:00 | 3.218 | -0.31% | 5 | 10 | hayır |
| PHATRY | M30 | fast_cross_mid | 20.10 09:00 | 3.28 | -0.30% | 30 | 780 | evet |
| JUPTRY | M30 | fast_cross_mid | 07.09 02:30 | 13.34 | -0.30% | 30 | 6600 | hayır |
| ROSETRY | M5 | fast_cross_mid | 22.08 08:00 | 0.3371 | -0.30% | 5 | 13460 | hayır |

## Dürüst sınırlar

- Mum verisi Binance TR herkese açık klines ucundan; sinyal mumu KAPANIŞI giriş fiyatı sayılır (spread/kayma yok).
- MFE "en yüksek görülen fiyat"tır, gerçekleşmiş kazanç değildir; çıkış kuralı simüle edilmemiştir.
- Açık uçlu sinyaller veri sonuna kadar ölçüldüğü için gerçek MFE daha yüksek olabilir.
- Sembol evreni raporun üretildiği andaki aktif + izlenen listedir; geçmişte aktif olup çıkanlar yoktur.

## Canlı sembol seçimi (yeniden üretim)

- Her 600 sn: 24 sa yükselenler ilk 50 (5m mumlardan: son kapanış / 24 sa önceki kapanış; 24 sa quote hacim). Her 3600 sn: aktivite filtresi (hacim ≥ 1,000,000 TL, 15 dk aralık ≥ %0.05, ATR ≥ 0.0012, hacim oranı ≥ 0.5, M1 düz mum filtresi açık [5/4, 30/25], kapsamlı pasiflik analizi).
- Saatlik anlık görüntü: 2160; izlenen evrene giren sembol: 310; saat başına AKTİF: ortalama 11.6, en az 0, en çok 33; aktif küme boş olup izlenen listeye düşülen saat: 1.
- Aktivite kararları: {'PASSIVE': 82886, 'ACTIVE': 25114}. Sinyal elemesi: 127542 ham sinyalden 5446 tanesi o anda taranan sembolde (kalanı sistem görmezdi).

| Sembol | Aktif saat | Sinyal |
|---|---:|---:|
| PUMPTRY | 424 | 115 |
| MUBARAKTRY | 418 | 93 |
| ENATRY | 408 | 88 |
| ACETRY | 391 | 63 |
| NILTRY | 388 | 79 |
| HEITRY | 347 | 73 |
| CHIPTRY | 332 | 84 |
| COTITRY | 316 | 74 |
| BOMETRY | 315 | 81 |
| HEMITRY | 298 | 75 |
| SAGATRY | 288 | 72 |
| WLDTRY | 287 | 66 |
| NEARTRY | 276 | 73 |
| PORTALTRY | 272 | 72 |
| ESPTRY | 265 | 63 |
| INJTRY | 253 | 69 |
| ETHFITRY | 246 | 59 |
| PEPETRY | 244 | 45 |
| SENTTRY | 240 | 48 |
| TIATRY | 238 | 56 |

Sadeleştirmeler: açık paper pozisyonlarının evrene eklenmesi yok; ticker `priceChangePercent` yerine 5m kapanış oranı; `_m1_activity_features` karara girmediği için hesaplanmadı; aktivite kararı yalnız izlenen sembollerde (canlıda izlenmeyen sembolün 5m serisi olmadığından WARMING kalır).

## Ek kurallar (2026-10-21 tablosu)

M15: mum gövdesi ≥ %1 (yükseliş) ve RSI14 45–65 · M30: MACD(12,26,9) histogramı artıyor ve ADX14 > 20 · H1: son 3 mum yükseliş, 3 mumluk aralık ≥ %2, RSI14 45–65, ADX14 > 20 · M5: ek kural yok (karşılaştırma).

| Elenme nedeni | Sinyal |
|---|---:|
| 15m: mum gövdesi < %1 | 39419 |
| 30m: adx ≤ 20 | 7552 |
| 1h: son 3 mum yükseliş değil | 7169 |
| 30m: macd histogram artmıyor | 6716 |
| 15m: rsi aralık dışı | 1433 |
| 1h: dalga dar | 1126 |
| 1h: rsi aralık dışı | 748 |
| 1h: adx ≤ 20 | 593 |
