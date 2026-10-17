# indicators_ext — dışa açık fonksiyonlar (backend/app/rescan/indicators_ext.py)

Hepsi 1-boyutlu float dizileri alır; nedensel (i. değer ≤ i barları; swing onayı right bar gecikmeli). `compute_all(arr, tf)` 9 kolonlu pattern_study dizisinden (open_time,o,h,l,c,v,quote_v,taker_base,taker_quote; boşluklar `pattern_study.fill_gaps` ile doldurulmuş) tüm özellikleri `<tf>.<ad>` sütunları olarak üretir (5m/15m: 134 sütun; 1m: POC yok → 133). float32 matris; ısınma NaN.

Çıktısı sözlük olanlarda anahtarlar docstring'te yazar.

| fonksiyon | imza | açıklama |
|---|---|---|
| `sma` | `sma(x, n: 'int') -> 'np.ndarray'` | Basit hareketli ortalama; ilk n-1 (ve baştaki NaN'lar sonrası) NaN. |
| `ema` | `ema(x, n: 'int') -> 'np.ndarray'` | SMA tohumlu EMA (kanonik, pattern_study.ema_seeded). |
| `wma` | `wma(x, n: 'int') -> 'np.ndarray'` | Ağırlıklı HO (en yeni bar ağırlığı n, en eski 1). |
| `alma` | `alma(x, n: 'int' = 9, offset: 'float' = 0.85, sigma: 'float' = 6.0) -> 'np.ndarray'` | Arnaud Legoux HO: Gauss ağırlıkları, tepe konumu offset·(n-1) (varsayılan 0,85 → yeni barlara yakın). |
| `hull_ma` | `hull_ma(x, n: 'int' = 21) -> 'np.ndarray'` | Hull HO = WMA(2·WMA(n/2) − WMA(n), √n). |
| `dema` | `dema(x, n: 'int' = 20) -> 'np.ndarray'` | Çift üstel HO = 2·EMA − EMA(EMA). |
| `tema` | `tema(x, n: 'int' = 20) -> 'np.ndarray'` | Üçlü üstel HO = 3·EMA − 3·EMA² + EMA³. |
| `kama` | `kama(x, n: 'int' = 10, fast: 'int' = 2, slow: 'int' = 30) -> 'np.ndarray'` | Kaufman uyarlanabilir HO (verimlilik oranı ER → yumuşatma sabiti). |
| `mcginley` | `mcginley(x, n: 'int' = 14) -> 'np.ndarray'` | McGinley Dynamic: MD = MD₁ + (x − MD₁) / (n·(x/MD₁)⁴). |
| `linreg_band` | `linreg_band(x, n: 'int' = 20) -> 'dict[str, np.ndarray]'` | LSMA (doğrusal regresyon son-değer) + standart hata: {"value", "slope" (birim/bar), "stderr"}. |
| `obv` | `obv(c, v) -> 'np.ndarray'` | On-Balance Volume (birikimli). |
| `obv_slope` | `obv_slope(c, v, n: 'int' = 12) -> 'np.ndarray'` | OBV n-bar değişimi / n-bar hacim (net işaretli hacim payı). |
| `ad_line` | `ad_line(h, l, c, v) -> 'np.ndarray'` | Birikim/Dağıtım çizgisi. |
| `ad_slope` | `ad_slope(h, l, c, v, n: 'int' = 12) -> 'np.ndarray'` | A/D çizgisinin n-bar değişimi / n-bar hacim. |
| `cmf` | `cmf(h, l, c, v, n: 'int' = 20) -> 'np.ndarray'` | Chaikin Para Akışı. |
| `chaikin_osc` | `chaikin_osc(h, l, c, v, fast: 'int' = 3, slow: 'int' = 10) -> 'np.ndarray'` | EMA(AD, fast) − EMA(AD, slow), SMA(hacim, slow) ile ölçeklenmiş. |
| `klinger` | `klinger(h, l, c, v, fast: 'int' = 34, slow: 'int' = 55, sig: 'int' = 13) -> 'dict[str, np.ndarray]'` | Klinger Hacim Osilatörü: {"kvo", "signal", "hist"} — SMA(hacim, slow) ile ölçeklenmiş. |
| `ease_of_movement` | `ease_of_movement(h, l, qv, n: 'int' = 14) -> 'np.ndarray'` | Hareket Kolaylığı (ölçeksiz): orta nokta % değişimi / (göreli hacim / aralık%), SMA(n); uçlar ±10'a kırpılı. |
| `force_index` | `force_index(c, v, n: 'int' = 13) -> 'np.ndarray'` | Elder Kuvvet Endeksi: EMA(getiri% × göreli hacim, n) (ölçeksiz). |
| `pvt` | `pvt(c, v) -> 'np.ndarray'` | Fiyat-Hacim Trendi (birikimli). |
| `pvt_slope` | `pvt_slope(c, v, n: 'int' = 12) -> 'np.ndarray'` | PVT n-bar değişimi / n-bar hacim. |
| `volume_oscillator` | `volume_oscillator(v, fast: 'int' = 5, slow: 'int' = 10) -> 'np.ndarray'` | Hacim osilatörü: (SMA(hacim,fast) − SMA(hacim,slow)) / SMA(hacim,slow) × 100. |
| `cvd` | `cvd(qv, tbq) -> 'np.ndarray'` | Taker tabanlı net hacim: birikimli Σ(2·taker_alış_quote − toplam_quote). |
| `cvd_slope` | `cvd_slope(qv, tbq, n: 'int' = 12) -> 'np.ndarray'` | CVD n-bar değişimi / n-bar quote hacmi ∈ [-1, 1] (≈ 2·taker payı − 1; mevcut tk_share ile affin eşdeğer). |
| `orderflow_imbalance_z` | `orderflow_imbalance_z(qv, tbq, n: 'int' = 3, hist: 'int' = 288) -> 'np.ndarray'` | Emir akışı dengesizliği z-skoru: son n barın net taker payı, önceki `hist` barın (n bar boşluklu) aynı ölçüsünün ort/std'sine göre. |
| `cmo` | `cmo(c, n: 'int' = 14) -> 'np.ndarray'` | Chande Momentum Osilatörü. |
| `connors_rsi` | `connors_rsi(c, rsi_n: 'int' = 3, streak_n: 'int' = 2, rank_n: 'int' = 100) -> 'np.ndarray'` | Connors RSI = (RSI(c,3) + RSI(seri,2) + yüzdelik sıra(ROC1, 100)) / 3. |
| `stochastic` | `stochastic(h, l, c, k: 'int' = 14, smooth: 'int' = 3, d: 'int' = 3) -> 'dict[str, np.ndarray]'` | Yavaş Stokastik: {"k", "d", "raw"} (ham %K'nın SMA(smooth)'ı = K; D = SMA(K, d)). Aralık 0 → 50. |
| `stochrsi` | `stochrsi(c, rsi_n: 'int' = 14, stoch_n: 'int' = 14, k: 'int' = 3, d: 'int' = 3) -> 'dict[str, np.ndarray]'` | StochRSI (mevcut `app.rescan.stochrsi`'e sarmalayıcı): {"rsi","stoch","k","d"}. |
| `williams_r` | `williams_r(h, l, c, n: 'int' = 14) -> 'np.ndarray'` | Williams %R (−100…0). |
| `ultimate_osc` | `ultimate_osc(h, l, c, p1: 'int' = 7, p2: 'int' = 14, p3: 'int' = 28) -> 'np.ndarray'` | Ultimate Oscillator. |
| `awesome_osc` | `awesome_osc(h, l, fast: 'int' = 5, slow: 'int' = 34) -> 'np.ndarray'` | AO = SMA(orta,5) − SMA(orta,34), yavaş ortalamaya göre % (ölçeksiz). |
| `tsi` | `tsi(c, long: 'int' = 25, short: 'int' = 13) -> 'np.ndarray'` | Gerçek Güç Endeksi: 100·EMA(EMA(Δc))/EMA(EMA(/Δc/)). |
| `trix` | `trix(c, n: 'int' = 15) -> 'np.ndarray'` | TRIX = üçlü EMA'nın 1-bar % değişimi. |
| `kst` | `kst(c, signal: 'int' = 9) -> 'dict[str, np.ndarray]'` | Know Sure Thing: ROC(10/15/20/30) SMA(10/10/10/15) ağırlık 1/2/3/4; {"kst","signal"}. |
| `fisher_transform` | `fisher_transform(h, l, n: 'int' = 9) -> 'dict[str, np.ndarray]'` | Fisher Dönüşümü: {"fisher","trigger"(1 bar gecikmeli)}. |
| `rvi_vigor` | `rvi_vigor(o, h, l, c, n: 'int' = 10) -> 'dict[str, np.ndarray]'` | Göreli Canlılık Endeksi (RVI): {"rvi","signal"}. |
| `balance_of_power` | `balance_of_power(o, h, l, c, smooth: 'int' = 14) -> 'np.ndarray'` | Güç Dengesi: SMA((c−o)/(h−l)). |
| `cci` | `cci(h, l, c, n: 'int' = 20) -> 'np.ndarray'` | Commodity Channel Index. |
| `dpo` | `dpo(c, n: 'int' = 20) -> 'np.ndarray'` | Trendden arındırılmış fiyat osilatörü (kapanışa göre %): c[i-(n/2+1)] − SMA(c,n)[i]. |
| `smi_ergodic` | `smi_ergodic(c, long: 'int' = 20, short: 'int' = 5, signal: 'int' = 5) -> 'dict[str, np.ndarray]'` | SMI Ergodic = TSI(short, long) ve sinyal EMA: {"smi","signal"}. |
| `coppock` | `coppock(c, wma_n: 'int' = 10, r1: 'int' = 14, r2: 'int' = 11) -> 'np.ndarray'` | Coppock eğrisi: WMA(ROC14 + ROC11, 10). |
| `vortex` | `vortex(h, l, c, n: 'int' = 14) -> 'dict[str, np.ndarray]'` | Vortex: {"plus","minus","diff"}. |
| `parabolic_sar` | `parabolic_sar(h, l, af0: 'float' = 0.02, step: 'float' = 0.02, af_max: 'float' = 0.2) -> 'dict[str, np.ndarray]'` | Parabolik SAR: {"sar","state"(+1 yükseliş/−1 düşüş),"flip"(+1 yukarı dönüş, −1 aşağı, bu barda)}. İlk 35 bar ısınma (NaN). |
| `supertrend` | `supertrend(h, l, c, period: 'int' = 10, mult: 'float' = 3.0) -> 'dict[str, np.ndarray]'` | SuperTrend: {"line","state"(+1 yükseliş/−1 düşüş),"flip"}. ATR = Wilder RMA(TR). İlk 3·period bar ısınma (NaN). |
| `supertrend_cluster` | `supertrend_cluster(h, l, c, params=((10, 1.0), (11, 2.0), (12, 3.0))) -> 'dict[str, np.ndarray]'` | 3 SuperTrend kümesi: {"sum" (−3..+3: yükselişte olanlar − düşüşte olanlar), "flip_up_3" (son 3 barda yükselişe dönen SuperTrend sayısı), |
| `ichimoku` | `ichimoku(h, l, c, tenkan_n: 'int' = 9, kijun_n: 'int' = 26, senkou_n: 'int' = 52, disp: 'int' = 26) -> 'dict[str, np.ndarray]'` | Ichimoku (nedensel): bulut i'de `disp` bar önce hesaplanan Senkou A/B'dir. Çıktılar: |
| `donchian` | `donchian(h, l, c, n: 'int' = 20) -> 'dict[str, np.ndarray]'` | Donchian: {"pos" ((c−LL)/(HH−LL), pencere bugünü içerir), "break_up" (c, ÖNCEKİ n barın en yükseğini aştı), "width" (% aralık)}. |
| `inside_bar_breakout` | `inside_bar_breakout(h, l, c) -> 'dict[str, np.ndarray]'` | İç-bar kırılım filtresi: ana mum m=i−2, iç mum i−1 (h[i−1] < h[m], l[i−1] > l[m]); i'de kapanış > h[m] ("up") / < l[m] ("down"). |
| `keltner` | `keltner(h, l, c, n: 'int' = 20, atr_n: 'int' = 10, mult: 'float' = 1.5) -> 'dict[str, np.ndarray]'` | Keltner: {"pos" ((c−orta)/(mult·ATR)), "width" (% = 2·mult·ATR/orta), "upper","lower","mid"}. |
| `squeeze` | `squeeze(h, l, c, n: 'int' = 20, bb_k: 'float' = 2.0, kc_mult: 'float' = 1.5, release_look: 'int' = 6) -> 'dict[str, np.ndarray]'` | Sıkışma (Bollinger, Keltner içinde): {"on" (0/1), "run" (üst üste sıkışık bar), "ratio" (BB genişliği / KC genişliği), |
| `choppiness` | `choppiness(h, l, c, n: 'int' = 14) -> 'np.ndarray'` | Choppiness Index (0–100; yüksek = yatay/testere). |
| `mass_index` | `mass_index(h, l, ema_n: 'int' = 9, sum_n: 'int' = 25) -> 'np.ndarray'` | Mass Index: Σ_25 EMA9(h−l) / EMA9(EMA9(h−l)). |
| `hist_vol` | `hist_vol(c, n: 'int' = 20) -> 'np.ndarray'` | Tarihsel oynaklık: log getirinin n-bar std'si (% / bar). |
| `chaikin_volatility` | `chaikin_volatility(h, l, ema_n: 'int' = 10, roc_n: 'int' = 10) -> 'np.ndarray'` | Chaikin Oynaklığı: EMA(h−l) ROC %. |
| `relative_volatility_index` | `relative_volatility_index(c, std_n: 'int' = 10, smooth: 'int' = 14) -> 'np.ndarray'` | Göreli Oynaklık Endeksi (RSI benzeri, std üzerinde). |
| `atr_ratio` | `atr_ratio(h, l, c, fast: 'int' = 7, slow: 'int' = 50) -> 'np.ndarray'` | ATR(fast)/ATR(slow): oynaklık genişlemesi. |
| `vwap_session` | `vwap_session(open_time, h, l, c, v) -> 'np.ndarray'` | Oturum VWAP'ı (oturum = UTC günü, hacim ağırlıklı tipik fiyat); oturumda hacim 0 ise tipik fiyat. |
| `anchored_vwap_swing_low` | `anchored_vwap_swing_low(h, l, c, v, window: 'int' = 288) -> 'dict[str, np.ndarray]'` | Son `window` barın (24 sa) en düşük dibinden (en yeni eşitlik) çapalanmış VWAP: {"vwap","age" (bar sayısı/window)}. |
| `volume_profile_poc` | `volume_profile_poc(h, l, c, v, window: 'int' = 288, bins: 'int' = 50, chunk: 'int' = 2048) -> 'np.ndarray'` | Son `window` barın hacim profili POC fiyatı (pencerenin [en düşük, en yüksek] aralığı `bins` kutuya bölünür; bar hacmi tipik fiyatının kutusuna eklenir). |
| `swing_pivots` | `swing_pivots(h, l, left: 'int' = 3, right: 'int' = 3) -> 'dict[str, np.ndarray]'` | Fraktal tepe/dipler. Tepe j: h[j] ≥ önceki `left` barın en yükseği VE h[j] > sonraki `right` barın en yükseği (dip simetrik). |
| `market_structure` | `market_structure(o, h, l, c, left: 'int' = 3, right: 'int' = 3, eq_tol_atr: 'float' = 0.15, reclaim_bars: 'int' = 3) -> 'dict[str, np.ndarray]'` | SMC piyasa yapısı (nedensel; salınımlar `right` bar sonra onaylanır). Çıktılar (i barı): |
| `fair_value_gaps` | `fair_value_gaps(h, l, c, min_atr: 'float' = 0.25, max_age: 'int' = 50) -> 'dict[str, np.ndarray]'` | Adil Değer Boşlukları (3 mum): yükseliş FVG: l[i] > h[i−2]; düşüş: h[i] < l[i−2]; boşluk ≥ min_atr·ATR14[i−1] olmalı. Çıktılar: |
| `displacement` | `displacement(o, c, h, l, k: 'float' = 1.5) -> 'dict[str, np.ndarray]'` | Yer değiştirme: gövde > k·ATR14[i−1]. {"body_atr" (işaretli gövde/ATR), "up", "down", "up_cnt5" (son 5 barda yukarı yer değiştirme sayısı)}. |
| `order_blocks` | `order_blocks(o, h, l, c, k: 'float' = 1.5, lookback: 'int' = 5, max_age: 'int' = 60) -> 'dict[str, np.ndarray]'` | Yükseliş order block: yukarı yer değiştirme (gövde > k·ATR14[i−1]) barından önceki SON düşüş mumunun [low, high] bölgesi (j−1…j−lookback). |
| `td_sequential` | `td_sequential(c) -> 'dict[str, np.ndarray]'` | TD Sequential KURULUM sayacı (9'a kadar döner): "buy" = ardışık (c < c[−4]) sayısı, "sell" = ardışık (c > c[−4]); "buy9"/"sell9" = bu barda 9 tamamlandı. |
| `compute_all` | `compute_all(arr: 'np.ndarray', tf: 'str' = '5m') -> 'tuple[list[str], np.ndarray]'` | Kütüphanenin TÜM özelliklerini bir zaman dilimi dizisi için hesaplar: (isimler `<tf>.<ad>`, float32 matris n × F). |
| `feature_names` | `feature_names(tf: 'str' = '5m') -> 'list[str]'` | `compute_all`'ın üreteceği sütun adları (sahte dizi üzerinden; FAMILY'yi de doldurur). |
| `shift` | `shift(x, k: 'int') -> 'np.ndarray'` | out[i] = x[i-k] (başı NaN). |
| `rsum` | `rsum(x, n: 'int') -> 'np.ndarray'` | n barlık kayan toplam (baştaki NaN'lara izin verir). |
| `rolling_max` | `rolling_max(x, w: 'int') -> 'np.ndarray'` |  |
| `rolling_min` | `rolling_min(x, w: 'int') -> 'np.ndarray'` |  |
| `flow_share` | `flow_share(cum, vol, n: 'int') -> 'np.ndarray'` | Birikimli akış serisinin n bar değişimi / n bar toplam hacim → [-1, 1] bandında ölçeksiz pay. |

## `compute_all` sütunları (5m) ve aileleri

- **ma** (17): px_alma, slope_alma, px_wma, slope_wma, px_hma, slope_hma, px_dema, slope_dema, px_tema, slope_tema, px_kama, slope_kama, px_mcg, slope_mcg, lsma_px, lsma_z, lsma_se_pct
- **flow** (15): obv_slope12, obv_slope48, ad_slope12, cmf20, cmf20_chg5, chaikin_osc, kvo, kvo_hist, eom14, efi13, pvt_slope12, vol_osc, cvd_slope12, cvd_slope48, ofi_z
- **osc** (28): cmo14, crsi, stoch_k, stoch_d, stoch_kd, stochrsi_k, stochrsi_d, stochrsi_kd, willr14, ultosc, ao_pct, ao_chg, tsi, tsi_sig_diff, trix, trix_sig_diff, kst, kst_sig_diff, fisher, fisher_chg, rvi, rvi_sig_diff, bop14, cci20, dpo20, smi_erg, smi_sig_diff, coppock
- **trend** (34): vi_plus, vi_minus, vi_diff, vortex_cross_up3, psar_state, psar_dist, psar_flip_up3, st_state, st_dist, st_flip_up3, st_cluster_sum, st_cluster_flip_up3, st_cluster_agree_up, st_cluster_flip_all_up, ichi_cloud_pos, ichi_cloud_dist, ichi_cloud_thick, ichi_tk_diff, ichi_tk_cross_up, ichi_chikou, donch_pos20, donch_break20, donch_width20, inside_break_up, kc_pos, kc_width, squeeze_on, squeeze_run, bb_kc_ratio, squeeze_since_off, squeeze_release, chop14, chop_drop12, mass_index
- **vol** (4): atr_ratio, hv20, chaikin_vol, rvi_vol
- **loc** (4): vwap_dist, avwap_dist, avwap_age, poc_dist
- **smc** (32): ms_trend, ms_bos_up, ms_choch_up, ms_bos_dn, ms_choch_dn, ms_since_choch_up, ms_dist_sh, ms_dist_sl, ms_sweep_low, ms_sweep_low_recent3, ms_sweep_depth, ms_eql, ms_eqh, ms_sweep_eql, fvg_bull_new, fvg_bull_open, fvg_bull_tap, fvg_bull_age, fvg_bear_new, fvg_bear_open, ob_dist, ob_active, ob_tap, ob_age, disp_body_atr, disp_up, disp_down, disp_up_cnt5, td_buy, td_sell, td_buy9, td_sell9

## Zaten `pattern_study.features_matrix` içinde olanlar (kütüphanede YOK)
EMA7/20/50/99 uzaklık+eğim+fan, RSI14, MFI14, ATR14%, BB genişlik/%B, MACD hist(+eğim), ADX/±DI, Aroon, linreg eğimi(10/20), ret1…20, hacim oranı, 24sa yüksek/alçak uzaklığı, range_pos24, yeşil/higher-low koşuları, drawdown12, taker (tk_share*, tk_net*, tk_share_z3…). Ayrıca `stochrsi.py` (StochRSI), `rqk.py` (RQK).

## Değişiklik notu (READY işaretinden sonra, API adları aynı)
- `compute_all`: sonsuz ya da |x| > 1e9 değerler NaN yapılır (float32 taşmasını önler).
- `chaikin_volatility`: düz mumlarda EMA(h−l) sıfıra çöküp ROC patlamasın diye payda tabanı 1e-6·|h|, çıktı ±1000'e kırpılı.
