| bölme | havuz | desen | tür | koşullar (VE) | taker koşulu var | recall (eğitim) | YA eşleşmiş | YA havuz |
|---|---|---|---|---|---|---|---|---|
| A | base | A | ağaç d=2 @t0 | `5m.ret1 <= 0,1015` ∧ `5m.ret5 <= -0,1498` | hayır | %69,6 | %35,50 | %33,87 |
| A | base | B | elle seçim @t0 | `1m.px_ema20 <= 0,04472` ∧ `1m.bb_pctb <= 0,5188` ∧ `5m.ret1 <= 0` | hayır | %71,1 | %43,72 | %45,62 |
| A | base | C | ağaç d=3 @t0 | `5m.ret1 <= 0,1015` ∧ `5m.ret5 <= -1,664` | hayır | %26,9 | %7,47 | %2,16 |
| A | base | D | ağaç d=3 @t0+15dk | `5m.ret3 > 1,329` ∧ `1m.px_ema20 <= 2,634` | hayır | %66,3 | %6,13 | %2,23 |
| A | base | E | seçici ağaç d=4 @t0 (havuz YA≤%0,5) | `3m.atr14_pct > 0,5788` ∧ `1m.ema7_slope3 <= -0,0382` ∧ `5m.atr14_pct > 1,026` ∧ `1m.drawdown12_pct > 3,961` | hayır | %5,5 | %1,16 | %0,06 |
| A | base | F | seçici ağaç d=4 @t0+15dk (havuz YA≤%0,5) | `5m.ret3 > 2,101` ∧ `3m.max_candle12 <= 3,235` ∧ `1m.atr14_pct > 0,186` | hayır | %37,6 | %1,98 | %0,25 |
| A | all | A | ağaç d=2 @t0 | `1m.ret5 <= 0,1015` ∧ `1m.px_ema20 <= -0,3588` | hayır | %50,6 | %21,34 | %10,79 |
| A | all | B | elle seçim @t0 | `1m.px_ema20 <= 0,04472` ∧ `1m.bb_pctb <= 0,5188` ∧ `5m.ret1 <= 0` | hayır | %71,1 | %43,35 | %44,64 |
| A | all | C | ağaç d=3 @t0 | `1m.ret5 <= 0,1015` ∧ `1m.px_ema20 <= -0,3588` ∧ `5m.px_ema7 > -2,082` | hayır | %40,7 | %19,98 | %10,50 |
| A | all | D | ağaç d=3 @t0+15dk | `5m.ret3 > 1,329` ∧ `1m.px_ema20 <= 2,634` | hayır | %66,3 | %6,25 | %2,35 |
| A | all | E | seçici ağaç d=4 @t0 (havuz YA≤%0,5) | `3m.atr14_pct > 0,5788` ∧ `1m.px_ema20 <= -0,7151` ∧ `1m.px_ema20 > -2,118` ∧ `1m.drawdown12_pct <= 2,148` | hayır | %12,6 | %3,71 | %0,37 |
| A | all | F | seçici ağaç d=4 @t0+15dk (havuz YA≤%0,5) | `5m.ret3 > 2,335` ∧ `1m.linreg20_pct <= 0,3308` ∧ `5m.max_candle12 > 1,299` | hayır | %32,2 | %1,79 | %0,17 |
| A | all | G | C + taker ek koşul(lar)ı @t0 | `1m.ret5 <= 0,1015` ∧ `1m.px_ema20 <= -0,3588` ∧ `5m.px_ema7 > -2,082` ∧ `1m.tk_share12 <= 0,4046` ∧ `1m.tk_share_slope6 <= -0,01554` | evet | %14,2 | %4,48 | %2,93 |
| A | all | H | yalnız-taker ağaç d=3 @t0 | `1m.tk_net6 <= -0,09753` ∧ `1m.tk_share_z3 <= 0,01907` ∧ `1m.tk_share12 > 0,1566` | evet | %37,9 | %16,50 | %11,75 |
| A | all | I | yalnız-taker ağaç d=3 @t0+15dk | `5m.tk_share_z3 > -0,01841` ∧ `1m.tk_net12 > 0,4248` ∧ `5m.tk_share_slope6 > 0,03598` | evet | %19,6 | %3,89 | %6,83 |
| B | base | A | ağaç d=2 @t0 | `5m.ret1 <= 0,1096` ∧ `1m.px_ema20 <= -0,3326` | hayır | %46,4 | %21,24 | %9,80 |
| B | base | B | elle seçim @t0 | `1m.px_ema7 <= 0,01281` ∧ `1m.ret10 <= 0` ∧ `1m.bb_pctb <= 0,5513` | hayır | %71,0 | %43,71 | %45,60 |
| B | base | C | ağaç d=3 @t0 | `5m.ret1 <= 0,1096` ∧ `1m.px_ema20 <= -0,3326` ∧ `5m.ret3 <= -2,032` | hayır | %12,1 | %3,59 | %0,63 |
| B | base | D | ağaç d=3 @t0+15dk | `5m.ret3 > 1,547` | hayır | %53,1 | %5,07 | %1,27 |
| B | base | E | seçici ağaç d=4 @t0 (havuz YA≤%0,5) | `3m.atr14_pct > 0,4878` ∧ `1m.ema7_slope3 > -0,09491` ∧ `5m.max_candle12 > 2,69` ∧ `5m.drawdown12_pct <= 3,094` | hayır | %3,4 | %2,05 | %0,24 |
| B | base | F | seçici ağaç d=4 @t0+15dk (havuz YA≤%0,5) | `5m.ret3 > 2,367` ∧ `1m.px_ema20 <= 3,122` | hayır | %29,5 | %1,97 | %0,28 |
| B | all | A | ağaç d=2 @t0 | `5m.ret1 <= 0,1096` ∧ `1m.px_ema20 <= -0,3326` | hayır | %46,8 | %21,51 | %10,03 |
| B | all | B | elle seçim @t0 | `1m.px_ema7 <= 0,01329` ∧ `1m.ret10 <= 0` ∧ `1m.bb_pctb <= 0,5485` | hayır | %71,0 | %43,37 | %44,43 |
| B | all | C | ağaç d=3 @t0 | `5m.ret1 <= 0,1096` ∧ `1m.px_ema20 <= -0,3326` ∧ `5m.ret3 <= -2,032` | hayır | %12,2 | %3,65 | %0,67 |
| B | all | D | ağaç d=3 @t0+15dk | `5m.ret3 > 1,547` | hayır | %53,1 | %5,17 | %1,34 |
| B | all | E | seçici ağaç d=4 @t0 (havuz YA≤%0,5) | `3m.atr14_pct > 0,4878` ∧ `1m.ema7_slope3 > -0,09491` ∧ `5m.max_candle12 > 2,69` ∧ `5m.drawdown12_pct <= 3,094` | hayır | %3,4 | %2,09 | %0,26 |
| B | all | F | seçici ağaç d=4 @t0+15dk (havuz YA≤%0,5) | `5m.ret3 > 2,367` ∧ `1m.px_ema20 <= 3,122` | hayır | %29,5 | %2,01 | %0,30 |
| B | all | G | C + en iyi tek taker koşulu (zorunlu) @t0 | `5m.ret1 <= 0,1096` ∧ `1m.px_ema20 <= -0,3326` ∧ `5m.ret3 <= -2,032` ∧ `3m.tk_share_slope6 > -0,008581` | evet | %6,2 | %1,54 | %0,33 |
| B | all | H | yalnız-taker ağaç d=3 @t0 | `1m.tk_net6 <= -0,09338` ∧ `1m.tk_net12 <= -0,3852` ∧ `1m.tk_share1 <= 0,6784` | evet | %16,6 | %7,76 | %8,40 |
| B | all | I | yalnız-taker ağaç d=3 @t0+15dk | `5m.tk_share_z3 > -0,2806` ∧ `5m.tk_qratio > 1,21` ∧ `3m.tk_share3 <= 0,9963` | evet | %44,3 | %18,04 | %15,88 |
| C1 | base | A | ağaç d=2 @t0 | `1m.bb_pctb <= 0,3023` ∧ `5m.ret1 <= 0,06291` | hayır | %62,7 | %31,73 | %32,12 |
| C1 | base | B | elle seçim @t0 | `1m.ema7_slope3 <= 0,001114` ∧ `1m.bb_pctb <= 0,5247` ∧ `5m.macd_hist_slope <= 0,004849` | hayır | %69,9 | %41,76 | %44,07 |
| C1 | base | C | ağaç d=3 @t0 | `1m.bb_pctb <= 0,3023` ∧ `5m.ret1 <= 0,06291` ∧ `1m.px_ema7 <= -0,06216` | hayır | %58,3 | %26,72 | %17,50 |
| C1 | base | D | ağaç d=3 @t0+15dk | `5m.ret3 > 1,239` ∧ `1m.ret10 <= 4,957` | hayır | %68,6 | %9,63 | %2,16 |
| C1 | base | F | seçici ağaç d=4 @t0+15dk (havuz YA≤%0,5) | `5m.ret3 > 1,943` ∧ `1m.green_share12 > 0,2083` ∧ `5m.max_candle12 <= 2,466` | hayır | %30,8 | %1,57 | %0,20 |
| C1 | all | A | ağaç d=2 @t0 | `1m.bb_pctb <= 0,3023` ∧ `5m.ret1 <= 0,06291` | hayır | %62,8 | %31,61 | %31,53 |
| C1 | all | B | elle seçim @t0 | `1m.ema7_slope3 <= 0,001106` ∧ `1m.bb_pctb <= 0,5243` ∧ `5m.macd_hist_slope <= 0,00474` | hayır | %69,8 | %41,53 | %43,26 |
| C1 | all | C | ağaç d=3 @t0 | `1m.bb_pctb <= 0,3023` ∧ `5m.ret1 <= 0,06291` ∧ `1m.px_ema7 <= -0,06216` | hayır | %58,4 | %26,82 | %17,77 |
| C1 | all | D | ağaç d=3 @t0+15dk | `5m.ret3 > 1,239` ∧ `1m.ret10 <= 4,957` | hayır | %68,6 | %9,72 | %2,26 |
| C1 | all | F | seçici ağaç d=4 @t0+15dk (havuz YA≤%0,5) | `5m.ret3 > 1,943` ∧ `1m.green_share12 > 0,2083` ∧ `5m.max_candle12 <= 2,466` | hayır | %30,8 | %1,58 | %0,22 |
| C1 | all | G | C + taker ek koşul(lar)ı @t0 | `1m.bb_pctb <= 0,3023` ∧ `5m.ret1 <= 0,06291` ∧ `1m.px_ema7 <= -0,06216` ∧ `5m.tk_qratio > 0,7012` | evet | %29,8 | %11,50 | %6,07 |
| C1 | all | H | yalnız-taker ağaç d=3 @t0 | `1m.tk_net6 <= -0,05926` ∧ `1m.tk_share1 <= 0,7652` ∧ `3m.tk_share3 > 0,0008588` | evet | %36,1 | %23,54 | %19,96 |
| C1 | all | I | yalnız-taker ağaç d=3 @t0+15dk | `1m.tk_net12 > 0,4954` ∧ `1m.tk_qratio > 0,0004504` | evet | %19,2 | %4,56 | %4,28 |
| C2 | base | A | ağaç d=2 @t0 | `1m.bb_pctb <= 0,3232` ∧ `1m.px_ema20 <= -0,5588` | hayır | %30,3 | %11,21 | %3,91 |
| C2 | base | B | elle seçim @t0 | `1m.ema7_slope3 <= 0,004197` ∧ `1m.bb_pctb <= 0,5139` ∧ `5m.macd_hist_slope <= 0,005582` | hayır | %68,7 | %40,98 | %43,15 |
| C2 | base | C | ağaç d=3 @t0 | `1m.bb_pctb <= 0,3232` ∧ `1m.px_ema20 <= -0,5588` ∧ `1m.ret5 <= 0,1976` | hayır | %30,2 | %10,71 | %3,80 |
| C2 | base | D | ağaç d=3 @t0+15dk | `5m.ret3 > 1,093` ∧ `1m.ret10 <= 4,664` | hayır | %66,8 | %9,06 | %3,27 |
| C2 | base | F | seçici ağaç d=4 @t0+15dk (havuz YA≤%0,5) | `5m.ret3 > 1,219` ∧ `5m.ret3 <= 1,719` ∧ `5m.atr14_pct > 0,5506` ∧ `1m.px_ema20 <= 0,7514` | hayır | %10,7 | %1,90 | %0,41 |
| C2 | all | A | ağaç d=2 @t0 | `5m.ret1 <= 0,007814` ∧ `1m.ret10 <= -0,03205` | hayır | %70,4 | %37,04 | %34,38 |
| C2 | all | B | elle seçim @t0 | `1m.ema7_slope3 <= 0,003818` ∧ `1m.bb_pctb <= 0,5131` ∧ `5m.macd_hist_slope <= 0,005523` | hayır | %68,7 | %40,70 | %42,30 |
| C2 | all | C | ağaç d=3 @t0 | `5m.ret1 <= 0,007814` ∧ `1m.ret10 <= -0,03205` ∧ `1m.px_ema20 <= -0,5354` | hayır | %31,3 | %11,12 | %4,14 |
| C2 | all | D | ağaç d=3 @t0+15dk | `5m.ret3 > 1,093` ∧ `1m.ret10 <= 4,664` | hayır | %66,9 | %9,17 | %3,41 |
| C2 | all | F | seçici ağaç d=4 @t0+15dk (havuz YA≤%0,5) | `5m.ret3 > 1,219` ∧ `5m.ret3 <= 1,719` ∧ `5m.atr14_pct > 0,5506` ∧ `1m.ret20 <= 1,456` | hayır | %11,4 | %1,72 | %0,42 |
| C2 | all | G | C + en iyi tek taker koşulu (zorunlu) @t0 | `5m.ret1 <= 0,007814` ∧ `1m.ret10 <= -0,03205` ∧ `1m.px_ema20 <= -0,5354` ∧ `3m.tk_share6 > 0,4694` | evet | %12,9 | %4,06 | %1,46 |
| C2 | all | H | yalnız-taker ağaç d=3 @t0 | `1m.tk_net6 <= -0,5638` ∧ `5m.tk_share1 <= 0,4709` | evet | %10,2 | %4,15 | %4,99 |
| C2 | all | I | yalnız-taker ağaç d=3 @t0+15dk | `1m.tk_net12 > 0,1477` ∧ `1m.tk_qratio > 0,004669` ∧ `5m.tk_qratio > 1,189` | evet | %27,4 | %7,81 | %6,02 |
| C3 | base | A | ağaç d=2 @t0 | `5m.green_run <= 0,5` ∧ `1m.ret10 <= -0,06664` | hayır | %67,3 | %36,63 | %32,19 |
| C3 | base | B | elle seçim @t0 | `1m.ema7_slope3 <= 0,01074` ∧ `1m.bb_pctb <= 0,5687` ∧ `5m.macd_hist_slope <= 0,007379` | hayır | %69,0 | %44,17 | %46,41 |
| C3 | base | C | ağaç d=3 @t0 | `5m.green_run <= 0,5` ∧ `1m.ret10 <= -0,06664` ∧ `5m.ret3 <= -0,483` | hayır | %43,6 | %19,64 | %11,61 |
| C3 | base | D | ağaç d=3 @t0+15dk | `5m.ret3 > 0,9403` ∧ `1m.ret10 <= 4,387` | hayır | %73,0 | %11,76 | %4,82 |
| C3 | base | E | seçici ağaç d=4 @t0 (havuz YA≤%0,5) | `3m.atr14_pct > 0,5032` ∧ `1m.drawdown12_pct > 3,938` ∧ `5m.qv24_log10 > 8,017` | hayır | %3,5 | %1,37 | %0,12 |
| C3 | base | F | seçici ağaç d=4 @t0+15dk (havuz YA≤%0,5) | `5m.ret3 > 2,1` ∧ `1m.px_ema20 <= 3` ∧ `5m.max_candle12 <= 2,504` | hayır | %26,1 | %1,03 | %0,29 |
| C3 | all | A | ağaç d=2 @t0 | `5m.green_run <= 0,5` ∧ `1m.ret10 <= -0,06664` | hayır | %67,6 | %36,69 | %32,26 |
| C3 | all | B | elle seçim @t0 | `1m.ema7_slope3 <= 0,01005` ∧ `1m.bb_pctb <= 0,5658` ∧ `5m.macd_hist_slope <= 0,007138` | hayır | %69,2 | %43,71 | %45,40 |
| C3 | all | C | ağaç d=3 @t0 | `5m.green_run <= 0,5` ∧ `1m.ret10 <= -0,06664` ∧ `5m.ret3 <= -0,483` | hayır | %43,8 | %19,78 | %11,72 |
| C3 | all | D | ağaç d=3 @t0+15dk | `5m.ret3 > 0,9403` ∧ `1m.ret10 <= 4,387` | hayır | %73,0 | %11,93 | %5,04 |
| C3 | all | E | seçici ağaç d=4 @t0 (havuz YA≤%0,5) | `3m.atr14_pct > 0,5032` ∧ `1m.ema7_slope3 <= -0,09739` ∧ `1m.atr14_pct > 0,3564` ∧ `5m.drawdown12_pct > 5,121` | hayır | %7,7 | %2,74 | %0,37 |
| C3 | all | F | seçici ağaç d=4 @t0+15dk (havuz YA≤%0,5) | `5m.ret3 > 2,1` ∧ `1m.px_ema20 <= 3` ∧ `5m.max_candle12 <= 2,504` | hayır | %26,1 | %1,05 | %0,30 |
| C3 | all | G | C + en iyi tek taker koşulu (zorunlu) @t0 | `5m.green_run <= 0,5` ∧ `1m.ret10 <= -0,06664` ∧ `5m.ret3 <= -0,483` ∧ `1m.tk_qratio > 0,1627` | evet | %26,5 | %10,95 | %3,85 |
| C3 | all | H | yalnız-taker ağaç d=3 @t0 | `5m.tk_share1 <= 0,4753` ∧ `1m.tk_net12 <= -0,2344` ∧ `5m.tk_share_z3 <= -0,04221` | evet | %24,0 | %13,57 | %13,96 |
| C3 | all | I | yalnız-taker ağaç d=3 @t0+15dk | `1m.tk_net12 > 0,8852` ∧ `3m.tk_qratio > 0,08726` | evet | %13,2 | %3,09 | %3,32 |