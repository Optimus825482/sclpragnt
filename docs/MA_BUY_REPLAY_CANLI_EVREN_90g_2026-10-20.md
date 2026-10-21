# MA BUY 90 günlük replay (CANLI sembol seçimiyle) — sinyal sonrası en yüksek yükseliş (2026-10-20 22:52)

Kapsam: son 90 gün, 303 (canlı seçim; evren 310) sembol, zaman dilimleri M5, M15, M30, H1. Kural ve parametreler canlı motorla aynı (SMA 7/20/99, StochRSI K ≤ 80 (1m hariç)).

**Ölçüt:** sinyal mumunun KAPANIŞINA göre, bir SONRAKİ sinyale (aynı sembol + TF) kadar görülen en yüksek `high` (MFE). Sonraki sinyali olmayan son sinyaller veri sonuna kadar ölçülür ve *açık uçlu* sayılır. 15 dk / 1 sa / 4 sa / 24 sa sütunları sabit ufuklardır, sonraki sinyalle sınırlanmaz.

## Özet (TF bazında)

| TF | Kural | Sinyal | Medyan MFE | Ortalama | P25 | P75 | ≥%1 | ≥%2 | ≥%3 | Hedefe dokunma | Zirveye medyan dk | Sonrakine medyan dk | Açık uçlu |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M5 | all | 4520 | 3.99% | 7.92% | 1.37% | 10.07% | 0.81 | 0.67 | 0.57 | 0.73 | 175.00 | 765.00 | 288 |
| M5 | fast_cross_mid | 3688 | 3.99% | 7.90% | 1.34% | 10.03% | 0.81 | 0.66 | 0.57 | 0.73 | 167.50 | 700.00 | 228 |
| M5 | mid_cross_slow | 836 | 3.98% | 8.05% | 1.51% | 10.34% | 0.84 | 0.67 | 0.57 | 0.75 | 230.00 | 1485.00 | 60 |
| M15 | all | 2166 | 6.87% | 12.51% | 2.35% | 16.16% | 0.89 | 0.78 | 0.70 | 0.78 | 480.00 | 3262.50 | 267 |
| M15 | fast_cross_mid | 2007 | 6.85% | 12.54% | 2.27% | 16.15% | 0.88 | 0.78 | 0.70 | 0.78 | 450 | 3045 | 243 |
| M15 | mid_cross_slow | 159 | 7.73% | 12.19% | 3.02% | 16.23% | 0.92 | 0.84 | 0.75 | 0.84 | 855 | 4710 | 24 |
| M30 | all | 1068 | 11.03% | 19.20% | 4.17% | 24.39% | 0.94 | 0.88 | 0.81 | 0.85 | 1650.00 | 8025.00 | 227 |
| M30 | fast_cross_mid | 877 | 10.73% | 19.25% | 4.17% | 24.72% | 0.94 | 0.88 | 0.81 | 0.85 | 1590 | 7530 | 174 |
| M30 | mid_cross_slow | 194 | 11.73% | 19.06% | 3.97% | 23.45% | 0.95 | 0.89 | 0.81 | 0.86 | 2610.00 | 12765.00 | 53 |
| H1 | all | 471 | 15.93% | 27.56% | 6.00% | 36.98% | 0.96 | 0.91 | 0.87 | 0.87 | 3900 | 16380 | 182 |
| H1 | fast_cross_mid | 302 | 16.12% | 27.05% | 5.55% | 33.55% | 0.95 | 0.89 | 0.85 | 0.85 | 3300.00 | 16530.00 | 116 |
| H1 | mid_cross_slow | 172 | 15.16% | 28.46% | 6.39% | 42.70% | 0.96 | 0.94 | 0.88 | 0.88 | 4710.00 | 16080.00 | 66 |

## Sabit ufuklarda medyan en yüksek yükseliş

| TF | 15 dk | 1 sa | 4 sa | 24 sa |
|---|---:|---:|---:|---:|
| M5 | 0.48% (n=4520) | 1.08% (n=4519) | 2.11% (n=4512) | 4.93% (n=4489) |
| M15 | 0.50% (n=2166) | 1.04% (n=2165) | 2.07% (n=2165) | 4.51% (n=2144) |
| M30 | — | 0.99% (n=1068) | 2.17% (n=1068) | 4.38% (n=1063) |
| H1 | — | 1.23% (n=471) | 2.36% (n=471) | 4.75% (n=468) |

## Sembol bazında sinyal sayısı

| Sembol | M5 | M15 | M30 | H1 | Toplam |
|---|---:|---:|---:|---:|---:|
| 0GTRY | 26 | 15 | 2 | 2 | 45 |
| 1000CATTRY | 7 | 3 | 2 | 0 | 12 |
| 1000SATSTRY | 3 | 1 | 2 | 1 | 7 |
| 2ZTRY | 10 | 6 | 2 | 0 | 18 |
| AAVETRY | 22 | 9 | 6 | 2 | 39 |
| ACETRY | 51 | 30 | 15 | 7 | 103 |
| ACHTRY | 8 | 4 | 7 | 2 | 21 |
| ACMTRY | 2 | 3 | 2 | 0 | 7 |
| ACTTRY | 15 | 7 | 4 | 2 | 28 |
| ADATRY | 24 | 8 | 5 | 1 | 38 |
| AEROTRY | 17 | 9 | 0 | 0 | 26 |
| AEVOTRY | 8 | 4 | 2 | 0 | 14 |
| AIGENSYNTRY | 6 | 3 | 0 | 1 | 10 |
| AITRY | 6 | 4 | 4 | 0 | 14 |
| AIXBTTRY | 2 | 2 | 1 | 0 | 5 |
| ALGOTRY | 2 | 1 | 2 | 0 | 5 |
| ALICETRY | 22 | 8 | 2 | 3 | 35 |
| ALLOTRY | 32 | 19 | 6 | 2 | 59 |
| ALPINETRY | 5 | 2 | 0 | 1 | 8 |
| ALTTRY | 7 | 4 | 0 | 1 | 12 |
| AMPTRY | 21 | 12 | 8 | 3 | 44 |
| ANIMETRY | 1 | 2 | 0 | 0 | 3 |
| ANKRTRY | 5 | 2 | 1 | 1 | 9 |
| APETRY | 13 | 5 | 2 | 2 | 22 |
| API3TRY | 13 | 6 | 4 | 1 | 24 |
| APTTRY | 12 | 7 | 1 | 2 | 22 |
| ARBTRY | 28 | 19 | 5 | 3 | 55 |
| ARKMTRY | 9 | 4 | 2 | 0 | 15 |
| ARKTRY | 28 | 10 | 8 | 3 | 49 |
| ARPATRY | 10 | 5 | 2 | 1 | 18 |
| ARTRY | 17 | 6 | 3 | 2 | 28 |
| ASRTRY | 1 | 1 | 2 | 1 | 5 |
| ASTERTRY | 16 | 12 | 5 | 1 | 34 |
| ATMTRY | 14 | 8 | 0 | 3 | 25 |
| ATOMTRY | 6 | 2 | 0 | 1 | 9 |
| ATRY | 4 | 1 | 1 | 0 | 6 |
| ATTRY | 1 | 0 | 0 | 1 | 2 |
| AUCTIONTRY | 4 | 2 | 0 | 0 | 6 |
| AUDIOTRY | 19 | 7 | 3 | 0 | 29 |
| AVAXTRY | 34 | 11 | 5 | 2 | 52 |
| AVNTTRY | 6 | 3 | 0 | 2 | 11 |
| AXLTRY | 2 | 1 | 2 | 1 | 6 |
| AXSTRY | 3 | 2 | 1 | 0 | 6 |
| BABYTRY | 3 | 2 | 0 | 0 | 5 |
| BANKTRY | 38 | 22 | 14 | 6 | 80 |
| BARDTRY | 6 | 3 | 2 | 0 | 11 |
| BARTRY | 2 | 1 | 2 | 2 | 7 |
| BBTRY | 22 | 11 | 5 | 2 | 40 |
| BCHTRY | 9 | 5 | 2 | 0 | 16 |
| BEAMXTRY | 10 | 5 | 3 | 3 | 21 |
| BELTRY | 3 | 1 | 1 | 1 | 6 |
| BERATRY | 18 | 6 | 4 | 1 | 29 |
| BIOTRY | 21 | 8 | 6 | 0 | 35 |
| BLURTRY | 3 | 2 | 1 | 1 | 7 |
| BMTTRY | 22 | 12 | 4 | 2 | 40 |
| BNBTRY | 8 | 0 | 0 | 0 | 8 |
| BOMETRY | 68 | 38 | 11 | 10 | 127 |
| BONKTRY | 40 | 16 | 5 | 6 | 67 |
| BTCTRY | 15 | 3 | 0 | 0 | 18 |
| CAKETRY | 8 | 2 | 0 | 0 | 10 |
| CATITRY | 6 | 6 | 5 | 4 | 21 |
| CELOTRY | 1 | 0 | 0 | 0 | 1 |
| CETUSTRY | 8 | 2 | 4 | 0 | 14 |
| CFGTRY | 36 | 19 | 10 | 4 | 69 |
| CFXTRY | 5 | 3 | 1 | 0 | 9 |
| CHIPTRY | 71 | 34 | 15 | 9 | 129 |
| CHZTRY | 1 | 0 | 0 | 0 | 1 |
| CITYTRY | 0 | 0 | 0 | 1 | 1 |
| CKBTRY | 2 | 1 | 0 | 1 | 4 |
| COMPTRY | 3 | 0 | 0 | 0 | 3 |
| COTITRY | 59 | 29 | 16 | 11 | 115 |
| COWTRY | 5 | 1 | 0 | 0 | 6 |
| CRVTRY | 14 | 8 | 4 | 2 | 28 |
| CTRY | 20 | 8 | 3 | 2 | 33 |
| CYBERTRY | 2 | 2 | 0 | 1 | 5 |
| DASHTRY | 27 | 13 | 9 | 3 | 52 |
| DODOTRY | 54 | 29 | 22 | 7 | 112 |
| DOGETRY | 15 | 12 | 6 | 1 | 34 |
| DOGSTRY | 15 | 8 | 5 | 2 | 30 |
| DOLOTRY | 8 | 3 | 2 | 1 | 14 |
| DOTTRY | 2 | 1 | 1 | 2 | 6 |
| DYDXTRY | 2 | 1 | 0 | 0 | 3 |
| DYMTRY | 15 | 8 | 7 | 1 | 31 |
| EDENTRY | 41 | 15 | 10 | 2 | 68 |
| EDUTRY | 7 | 1 | 0 | 2 | 10 |
| EGLDTRY | 6 | 2 | 3 | 0 | 11 |
| EIGENTRY | 35 | 13 | 9 | 6 | 63 |
| ENATRY | 72 | 43 | 26 | 9 | 150 |
| ENJTRY | 5 | 3 | 4 | 1 | 13 |
| ENSOTRY | 8 | 3 | 3 | 1 | 15 |
| ENSTRY | 2 | 1 | 2 | 0 | 5 |
| ERATRY | 10 | 3 | 0 | 4 | 17 |
| ESPTRY | 52 | 21 | 16 | 1 | 90 |
| ETCTRY | 2 | 2 | 0 | 0 | 4 |
| ETHFITRY | 47 | 21 | 15 | 6 | 89 |
| ETHTRY | 18 | 2 | 5 | 0 | 25 |
| EULTRY | 19 | 11 | 3 | 2 | 35 |
| FETTRY | 45 | 12 | 9 | 3 | 69 |
| FFTRY | 29 | 22 | 11 | 4 | 66 |
| FIDATRY | 10 | 5 | 2 | 0 | 17 |
| FILTRY | 19 | 10 | 6 | 3 | 38 |
| FLOKITRY | 21 | 7 | 4 | 1 | 33 |
| FOGOTRY | 1 | 0 | 1 | 0 | 2 |
| FORMTRY | 16 | 3 | 6 | 2 | 27 |
| FTRY | 5 | 1 | 0 | 0 | 6 |
| GALATRY | 17 | 8 | 3 | 2 | 30 |
| GASTRY | 0 | 1 | 0 | 0 | 1 |
| GENIUSTRY | 9 | 6 | 4 | 1 | 20 |
| GIGGLETRY | 34 | 19 | 10 | 6 | 69 |
| GMTTRY | 2 | 0 | 0 | 0 | 2 |
| GPSTRY | 18 | 6 | 5 | 0 | 29 |
| GRAMTRY | 8 | 7 | 2 | 3 | 20 |
| GRTTRY | 14 | 5 | 0 | 0 | 19 |
| GTRY | 7 | 4 | 2 | 1 | 14 |
| GUNTRY | 4 | 1 | 0 | 1 | 6 |
| HAEDALTRY | 1 | 0 | 0 | 0 | 1 |
| HBARTRY | 14 | 7 | 0 | 0 | 21 |
| HEITRY | 57 | 40 | 21 | 7 | 125 |
| HEMITRY | 60 | 33 | 12 | 8 | 113 |
| HIVETRY | 2 | 0 | 0 | 0 | 2 |
| HMSTRTRY | 8 | 6 | 2 | 1 | 17 |
| HOLOTRY | 13 | 2 | 1 | 3 | 19 |
| HOMETRY | 25 | 12 | 8 | 5 | 50 |
| HOTTRY | 3 | 0 | 1 | 0 | 4 |
| HUMATRY | 7 | 4 | 0 | 1 | 12 |
| HYPERTRY | 3 | 1 | 0 | 0 | 4 |
| HYPETRY | 3 | 2 | 1 | 0 | 6 |
| ICPTRY | 3 | 1 | 0 | 0 | 4 |
| IDTRY | 1 | 1 | 0 | 0 | 2 |
| INITTRY | 16 | 5 | 2 | 0 | 23 |
| INJTRY | 59 | 30 | 10 | 7 | 106 |
| IOTATRY | 5 | 4 | 0 | 0 | 9 |
| IOTRY | 8 | 4 | 3 | 0 | 15 |
| JASMYTRY | 4 | 1 | 1 | 0 | 6 |
| JTOTRY | 27 | 14 | 10 | 1 | 52 |
| JUPTRY | 7 | 7 | 4 | 0 | 18 |
| JUVTRY | 1 | 2 | 1 | 1 | 5 |
| KAITOTRY | 31 | 11 | 8 | 0 | 50 |
| KATTRY | 11 | 5 | 3 | 2 | 21 |
| KERNELTRY | 4 | 2 | 1 | 0 | 7 |
| KITETRY | 20 | 7 | 1 | 0 | 28 |
| KSMTRY | 3 | 0 | 0 | 0 | 3 |
| LATRY | 21 | 8 | 5 | 3 | 37 |
| LAZIOTRY | 13 | 11 | 3 | 4 | 31 |
| LDOTRY | 12 | 5 | 3 | 1 | 21 |
| LINEATRY | 7 | 0 | 0 | 0 | 7 |
| LINKTRY | 12 | 7 | 2 | 2 | 23 |
| LISTATRY | 4 | 0 | 0 | 0 | 4 |
| LPTTRY | 10 | 5 | 1 | 2 | 18 |
| LTCTRY | 6 | 3 | 3 | 0 | 12 |
| LUMIATRY | 17 | 11 | 1 | 4 | 33 |
| LUNATRY | 11 | 5 | 3 | 0 | 19 |
| LUNCTRY | 4 | 3 | 3 | 0 | 10 |
| MAGICTRY | 13 | 7 | 2 | 1 | 23 |
| MANATRY | 1 | 1 | 0 | 2 | 4 |
| MANTATRY | 6 | 4 | 1 | 0 | 11 |
| MANTRATRY | 11 | 3 | 3 | 1 | 18 |
| MARSCOINTRY | 34 | 19 | 11 | 2 | 66 |
| MASKTRY | 2 | 0 | 0 | 0 | 2 |
| MAVTRY | 3 | 0 | 0 | 1 | 4 |
| MEGATRY | 19 | 7 | 3 | 1 | 30 |
| METISTRY | 5 | 0 | 2 | 0 | 7 |
| METRY | 7 | 1 | 0 | 1 | 9 |
| METTRY | 14 | 4 | 1 | 1 | 20 |
| MINATRY | 23 | 14 | 6 | 1 | 44 |
| MIRATRY | 10 | 7 | 2 | 1 | 20 |
| MITOTRY | 13 | 5 | 1 | 2 | 21 |
| MMTTRY | 29 | 13 | 8 | 4 | 54 |
| MORPHOTRY | 6 | 2 | 1 | 0 | 9 |
| MOVRTRY | 29 | 13 | 10 | 1 | 53 |
| MUBARAKTRY | 76 | 38 | 21 | 10 | 145 |
| NEARTRY | 62 | 35 | 11 | 8 | 116 |
| NEIROTRY | 11 | 2 | 2 | 0 | 15 |
| NEOTRY | 1 | 0 | 0 | 0 | 1 |
| NEWTTRY | 0 | 0 | 1 | 1 | 2 |
| NIGHTTRY | 25 | 9 | 2 | 0 | 36 |
| NILTRY | 66 | 38 | 17 | 11 | 132 |
| NMRTRY | 13 | 6 | 3 | 1 | 23 |
| NOMTRY | 19 | 14 | 3 | 3 | 39 |
| NOTTRY | 9 | 3 | 1 | 0 | 13 |
| NXPCTRY | 2 | 0 | 1 | 1 | 4 |
| OGNTRY | 10 | 5 | 1 | 0 | 16 |
| OGTRY | 2 | 2 | 0 | 1 | 5 |
| ONDOTRY | 26 | 12 | 5 | 4 | 47 |
| ONETRY | 22 | 14 | 8 | 5 | 49 |
| ONTTRY | 11 | 7 | 7 | 3 | 28 |
| OPENTRY | 14 | 7 | 4 | 0 | 25 |
| OPGTRY | 12 | 5 | 2 | 1 | 20 |
| OPNTRY | 12 | 4 | 1 | 0 | 17 |
| OPTRY | 8 | 3 | 2 | 0 | 13 |
| ORCATRY | 9 | 9 | 1 | 0 | 19 |
| ORDITRY | 20 | 6 | 1 | 3 | 30 |
| PARTITRY | 11 | 2 | 1 | 2 | 16 |
| PAXGTRY | 1 | 0 | 0 | 0 | 1 |
| PENDLETRY | 4 | 2 | 0 | 0 | 6 |
| PENGUTRY | 36 | 15 | 13 | 1 | 65 |
| PEOPLETRY | 7 | 5 | 1 | 1 | 14 |
| PEPETRY | 42 | 22 | 6 | 4 | 74 |
| PHATRY | 18 | 8 | 4 | 2 | 32 |
| PIXELTRY | 8 | 1 | 0 | 2 | 11 |
| PLUMETRY | 18 | 10 | 1 | 0 | 29 |
| PNUTTRY | 4 | 0 | 1 | 0 | 5 |
| POLTRY | 16 | 6 | 3 | 2 | 27 |
| POLYXTRY | 1 | 0 | 0 | 0 | 1 |
| PORTALTRY | 56 | 28 | 14 | 5 | 103 |
| PORTOTRY | 3 | 3 | 2 | 0 | 8 |
| PROVETRY | 0 | 2 | 0 | 0 | 2 |
| PSGTRY | 1 | 1 | 0 | 1 | 3 |
| PUMPTRY | 95 | 43 | 22 | 8 | 168 |
| PYTHTRY | 32 | 17 | 9 | 3 | 61 |
| RADTRY | 13 | 7 | 3 | 1 | 24 |
| RARETRY | 18 | 7 | 6 | 2 | 33 |
| RAYTRY | 24 | 15 | 9 | 4 | 52 |
| REDTRY | 8 | 3 | 0 | 1 | 12 |
| RENDERTRY | 11 | 4 | 3 | 0 | 18 |
| RESOLVTRY | 12 | 5 | 0 | 1 | 18 |
| RETRY | 35 | 13 | 5 | 5 | 58 |
| REZTRY | 28 | 16 | 9 | 7 | 60 |
| ROBOTRY | 12 | 4 | 5 | 1 | 22 |
| ROSETRY | 15 | 9 | 6 | 2 | 32 |
| RSRTRY | 5 | 2 | 1 | 0 | 8 |
| RVNTRY | 8 | 4 | 1 | 1 | 14 |
| SAGATRY | 58 | 25 | 9 | 4 | 96 |
| SAHARATRY | 14 | 5 | 1 | 3 | 23 |
| SANDTRY | 9 | 5 | 5 | 3 | 22 |
| SANTOSTRY | 12 | 4 | 6 | 2 | 24 |
| SAPIENTRY | 10 | 3 | 1 | 0 | 14 |
| SCRTRY | 15 | 6 | 3 | 1 | 25 |
| SEITRY | 16 | 9 | 2 | 2 | 29 |
| SENTTRY | 43 | 24 | 10 | 6 | 83 |
| SHELLTRY | 2 | 3 | 0 | 1 | 6 |
| SHIBTRY | 22 | 8 | 6 | 3 | 39 |
| SIGNTRY | 0 | 1 | 0 | 0 | 1 |
| SKLTRY | 4 | 3 | 5 | 1 | 13 |
| SKYTRY | 2 | 2 | 2 | 1 | 7 |
| SLPTRY | 6 | 0 | 0 | 0 | 6 |
| SNXTRY | 2 | 0 | 1 | 0 | 3 |
| SOLTRY | 17 | 8 | 4 | 0 | 29 |
| SOLVTRY | 10 | 4 | 2 | 1 | 17 |
| SOMITRY | 7 | 5 | 0 | 1 | 13 |
| SOPHTRY | 8 | 4 | 2 | 0 | 14 |
| SPELLTRY | 1 | 2 | 1 | 0 | 4 |
| SPKTRY | 14 | 6 | 1 | 1 | 22 |
| STOTRY | 10 | 8 | 2 | 2 | 22 |
| STRAXTRY | 8 | 3 | 1 | 2 | 14 |
| STRKTRY | 40 | 23 | 12 | 2 | 77 |
| STRY | 19 | 10 | 4 | 1 | 34 |
| STXTRY | 32 | 16 | 3 | 2 | 53 |
| SUITRY | 25 | 15 | 8 | 1 | 49 |
| SUPERTRY | 12 | 4 | 5 | 1 | 22 |
| SUSHITRY | 6 | 5 | 0 | 2 | 13 |
| SXTTRY | 8 | 5 | 1 | 0 | 14 |
| SYRUPTRY | 9 | 2 | 1 | 0 | 12 |
| TAOTRY | 18 | 10 | 3 | 1 | 32 |
| THETATRY | 7 | 4 | 1 | 0 | 12 |
| THETRY | 18 | 11 | 1 | 1 | 31 |
| TIATRY | 48 | 19 | 8 | 5 | 80 |
| TLMTRY | 25 | 14 | 8 | 1 | 48 |
| TNSRTRY | 5 | 2 | 0 | 0 | 7 |
| TOWNSTRY | 3 | 2 | 0 | 1 | 6 |
| TRBTRY | 5 | 4 | 3 | 1 | 13 |
| TREETRY | 3 | 1 | 3 | 0 | 7 |
| TRUMPTRY | 21 | 10 | 7 | 2 | 40 |
| TSTTRY | 43 | 19 | 13 | 6 | 81 |
| TURBOTRY | 2 | 2 | 1 | 0 | 5 |
| TWTTRY | 8 | 2 | 2 | 2 | 14 |
| UMATRY | 2 | 2 | 4 | 1 | 9 |
| UNITRY | 33 | 12 | 10 | 4 | 59 |
| USUALTRY | 13 | 2 | 1 | 0 | 16 |
| VANATRY | 2 | 0 | 0 | 0 | 2 |
| VETTRY | 12 | 4 | 3 | 0 | 19 |
| VIRTUALTRY | 4 | 1 | 1 | 1 | 7 |
| WALTRY | 9 | 6 | 1 | 2 | 18 |
| WCTTRY | 3 | 1 | 0 | 0 | 4 |
| WIFTRY | 14 | 10 | 6 | 0 | 30 |
| WLDTRY | 55 | 23 | 14 | 9 | 101 |
| WLFITRY | 4 | 2 | 1 | 0 | 7 |
| WTRY | 9 | 3 | 2 | 0 | 14 |
| XAITRY | 22 | 10 | 7 | 2 | 41 |
| XAUTTRY | 5 | 1 | 1 | 0 | 7 |
| XECTRY | 12 | 5 | 1 | 2 | 20 |
| XLMTRY | 16 | 8 | 6 | 1 | 31 |
| XPLTRY | 34 | 10 | 5 | 2 | 51 |
| XRPTRY | 32 | 9 | 7 | 0 | 48 |
| XTZTRY | 5 | 5 | 1 | 0 | 11 |
| XVGTRY | 9 | 3 | 0 | 0 | 12 |
| YBTRY | 2 | 1 | 0 | 0 | 3 |
| ZBTTRY | 10 | 5 | 2 | 1 | 18 |
| ZILTRY | 10 | 7 | 2 | 1 | 20 |
| ZKCTRY | 2 | 2 | 1 | 0 | 5 |
| ZKPTRY | 9 | 4 | 5 | 0 | 18 |
| ZKTRY | 17 | 14 | 1 | 0 | 32 |
| ZROTRY | 26 | 13 | 4 | 1 | 44 |

## En yüksek 10 yükseliş

| Sembol | TF | Kural | Sinyal zamanı | Fiyat | MFE | Zirveye dk | Sonrakine dk | Açık uçlu |
|---|---|---|---|---:|---:|---:|---:|---|
| HEITRY | H1 | fast_cross_mid | 03.08 08:00 | 4.02 | 536.82% | 4560 | 6900 | hayır |
| ACETRY | M30 | fast_cross_mid | 06.08 02:00 | 3.429 | 427.56% | 12900 | 13440 | hayır |
| ACETRY | H1 | mid_cross_slow | 25.07 03:00 | 5.024 | 260.07% | 30120 | 36600 | hayır |
| BMTTRY | M30 | fast_cross_mid | 23.07 18:00 | 0.582 | 236.77% | 24810 | 25170 | hayır |
| ONETRY | M15 | fast_cross_mid | 17.08 02:15 | 0.036 | 222.22% | 46065 | 46425 | hayır |
| ONETRY | M30 | mid_cross_slow | 02.09 11:00 | 0.03711 | 212.58% | 22500 | 22950 | hayır |
| HEMITRY | H1 | mid_cross_slow | 25.07 08:00 | 0.2504 | 204.51% | 39300 | 41880 | hayır |
| MAGICTRY | M30 | fast_cross_mid | 01.10 19:30 | 2.66 | 203.01% | 12150 | 15540 | hayır |
| MUBARAKTRY | H1 | fast_cross_mid | 04.09 16:00 | 1.439 | 195.97% | 26280 | 31740 | hayır |
| GTRY | M30 | fast_cross_mid | 04.08 01:00 | 0.17 | 190.59% | 65790 | 66570 | hayır |

## En zayıf 10 sinyal

| Sembol | TF | Kural | Sinyal zamanı | Fiyat | MFE | Zirveye dk | Sonrakine dk | Açık uçlu |
|---|---|---|---|---:|---:|---:|---:|---|
| PEOPLETRY | M5 | fast_cross_mid | 02.08 16:30 | 0.339 | -0.89% | 5 | 15 | hayır |
| DODOTRY | M15 | fast_cross_mid | 14.08 04:15 | 1.1197 | -0.78% | 15 | 3540 | hayır |
| MINATRY | M15 | fast_cross_mid | 07.09 15:45 | 3.97 | -0.76% | 15 | 60 | hayır |
| SUSHITRY | M5 | mid_cross_slow | 06.09 05:15 | 12.62 | -0.48% | 5 | 780 | hayır |
| AAVETRY | M5 | mid_cross_slow | 01.10 17:35 | 8306 | -0.41% | 70 | 70 | hayır |
| SUSHITRY | M15 | fast_cross_mid | 06.09 05:00 | 12.95 | -0.39% | 15 | 450 | hayır |
| LUMIATRY | M15 | fast_cross_mid | 13.10 17:00 | 5.508 | -0.33% | 15 | 2670 | hayır |
| ORDITRY | M5 | fast_cross_mid | 08.09 14:00 | 216.1 | -0.32% | 5 | 40 | hayır |
| LATRY | M5 | fast_cross_mid | 31.08 18:10 | 3.09 | -0.32% | 5 | 650 | hayır |
| HOLOTRY | M5 | fast_cross_mid | 29.08 02:00 | 3.218 | -0.31% | 5 | 10 | hayır |

## Dürüst sınırlar

- Mum verisi Binance TR herkese açık klines ucundan; sinyal mumu KAPANIŞI giriş fiyatı sayılır (spread/kayma yok).
- MFE "en yüksek görülen fiyat"tır, gerçekleşmiş kazanç değildir; çıkış kuralı simüle edilmemiştir.
- Açık uçlu sinyaller veri sonuna kadar ölçüldüğü için gerçek MFE daha yüksek olabilir.
- Sembol evreni raporun üretildiği andaki aktif + izlenen listedir; geçmişte aktif olup çıkanlar yoktur.

## Canlı sembol seçimi (yeniden üretim)

- Her 600 sn: 24 sa yükselenler ilk 50 (5m mumlardan: son kapanış / 24 sa önceki kapanış; 24 sa quote hacim). Her 3600 sn: aktivite filtresi (hacim ≥ 1,000,000 TL, 15 dk aralık ≥ %0.05, ATR ≥ 0.0012, hacim oranı ≥ 0.5, M1 düz mum filtresi açık [5/4, 30/25], kapsamlı pasiflik analizi).
- Saatlik anlık görüntü: 2160; izlenen evrene giren sembol: 310; saat başına AKTİF: ortalama 11.6, en az 0, en çok 33; aktif küme boş olup izlenen listeye düşülen saat: 1.
- Aktivite kararları: {'PASSIVE': 82891, 'ACTIVE': 25109}. Sinyal elemesi: 192405 ham sinyalden 8225 tanesi o anda taranan sembolde (kalanı sistem görmezdi).

| Sembol | Aktif saat | Sinyal |
|---|---:|---:|
| PUMPTRY | 424 | 168 |
| MUBARAKTRY | 418 | 145 |
| ENATRY | 409 | 150 |
| ACETRY | 391 | 103 |
| NILTRY | 388 | 132 |
| HEITRY | 348 | 125 |
| CHIPTRY | 330 | 129 |
| COTITRY | 316 | 115 |
| BOMETRY | 315 | 127 |
| HEMITRY | 298 | 113 |
| WLDTRY | 288 | 101 |
| SAGATRY | 288 | 96 |
| NEARTRY | 276 | 116 |
| PORTALTRY | 272 | 103 |
| ESPTRY | 265 | 90 |
| INJTRY | 253 | 106 |
| ETHFITRY | 246 | 89 |
| PEPETRY | 242 | 74 |
| SENTTRY | 240 | 83 |
| BANKTRY | 239 | 80 |

Sadeleştirmeler: açık paper pozisyonlarının evrene eklenmesi yok; ticker `priceChangePercent` yerine 5m kapanış oranı; `_m1_activity_features` karara girmediği için hesaplanmadı; aktivite kararı yalnız izlenen sembollerde (canlıda izlenmeyen sembolün 5m serisi olmadığından WARMING kalır).
