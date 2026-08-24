"""Paper-only M1 Lorentzian kernel-green long research with fixed RR exits."""
import argparse, asyncio, json, time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from app.binance_tr_public import historical_klines, trading_symbols_with_filters
from app.config import config
from scripts.replay_lorentzian_m5 import normalize, signal_series
from scripts.replay_ldc_kernel_m1 import atr

MS=60_000; BAL=10_000.; ALLOC=.30
def iso(x): return datetime.fromtimestamp(x/1000,timezone.utc).isoformat().replace('+00:00','Z')
def sim(rows,sigs,start,end,tick,mode):
    av=atr(rows,14); cash=BAL; pos=None; trades=[]; peak=BAL; dd=0.
    for i,row in enumerate(rows):
        if not start<=row['close_time']<=end: continue
        if pos:
            stop=pos['stop']; target=pos['target']
            # Conservative bar ordering: a stop wins if both levels are touched.
            if row['low']<=stop: reason='stop'; price=stop
            elif row['high']>=target: reason='target'; price=target
            else:
                reason=None; price=None
                if row['high']>=pos['entry']+pos['risk']:
                    pos['armed']=True
                if pos['armed'] and mode=='lock_2r': pos['stop']=max(pos['stop'],pos['entry']+.25*pos['risk'])
                if pos['armed'] and mode=='trail_3r': pos['stop']=max(pos['stop'],row['high']-1.5*(av[i] or pos['risk']))
            if reason:
                fill=max(0.,price-2*tick); gross=pos['qty']*fill; fee=gross*config.COMMISSION_PCT; cash+=gross-fee
                trades.append({'entry_time':pos['time'],'exit_time':row['close_time'],'pnl_try':gross-fee-pos['cost'],'fees_try':pos['fee']+fee,'reason':reason}); pos=None
        if not pos and sigs[i]['new_long'] and i+1<len(rows) and av[i] and rows[i+1]['time']<end:
            fill=rows[i+1]['open']*(1+config.BACKTEST_ASSUMED_SPREAD_PCT/2+config.ESTIMATED_SLIPPAGE_PCT); risk=av[i]
            cost=cash*ALLOC; notional=cost/(1+config.COMMISSION_PCT); fee=notional*config.COMMISSION_PCT
            cash-=cost; rr=3 if mode in ('classic_3r','trail_3r') else 2
            pos={'time':rows[i+1]['time'],'entry':fill,'risk':risk,'stop':fill-risk,'target':fill+rr*risk,'qty':notional/fill,'cost':cost,'fee':fee,'armed':False}
        mark=cash if not pos else cash+pos['qty']*max(0,row['close']-2*tick)*(1-config.COMMISSION_PCT); peak=max(peak,mark); dd=max(dd,peak-mark)
    if pos:
        row=rows[-1]; fill=max(0,row['close']-2*tick); gross=pos['qty']*fill; fee=gross*config.COMMISSION_PCT; cash+=gross-fee
        trades.append({'entry_time':pos['time'],'exit_time':row['close_time'],'pnl_try':gross-fee-pos['cost'],'fees_try':pos['fee']+fee,'reason':'window_mark_to_market'})
    pnl=[t['pnl_try'] for t in trades]; fees=sum(t['fees_try'] for t in trades); g=sum(x for x in pnl if x>0); l=sum(x for x in pnl if x<=0)
    return {'trades':len(trades),'gross_pnl_try':round(sum(pnl)+fees,2),'net_pnl_try':round(sum(pnl),2),'fees_try':round(fees,2),'wins':sum(x>0 for x in pnl),'losses':sum(x<=0 for x in pnl),'profit_factor':round(g/abs(l),3) if l else None,'expectancy_try':round(sum(pnl)/len(pnl),2) if pnl else 0.,'max_drawdown_try':round(dd,2),'final_balance_try':round(cash,2),'reconciliation_delta_try':round(cash-BAL-sum(pnl),8),'exit_reasons':dict(Counter(t['reason'] for t in trades)),'trades_detail':trades}
async def main(a):
    end=(int(time.time()*1000)-a.end_minutes_ago*MS)//MS*MS-1; start=end-a.hours*3600000; sym=a.symbol.upper().replace('_','')
    rows=normalize(await historical_klines(sym,'1m',a.fetch_days,end),end); tick=float((await trading_symbols_with_filters('TRY')).get(sym,{}).get('tick_size') or .01)
    first=max(35,next((i for i,r in enumerate(rows) if r['close_time']>=start),len(rows))-50); sigs=signal_series(rows,first)
    result={'paper_only':True,'generated_at':datetime.now(timezone.utc).isoformat(),'window':{'start':iso(start),'end':iso(end),'hours':a.hours},'source':'Binance TR public completed M1 OHLCV','provenance':{'symbol':sym,'m1_closed_candles':len(rows),'tick_size_try':tick},'configuration':{'lorentzian_source_defaults':{'neighbors':5,'max_bars_back':1000,'features':'RSI(10,21), WT(7,1), CCI(7,1), ADX(21), RSI(21,1)'},'entry':'source-aligned new Lorentzian long plus green kernel','risk':'ATR14 x 1','rr_and_management':{'classic_2r':'TP 2R / SL 1R','classic_3r':'TP 3R / SL 1R','lock_2r':'TP 2R; after +1R lock stop at +0.25R','trail_3r':'TP 3R; after +1R trail highest high by 1.5 ATR'}},'execution':{'allocation_pct':ALLOC,'commission_pct_each_side':config.COMMISSION_PCT,'spread_pct':config.BACKTEST_ASSUMED_SPREAD_PCT,'slippage':'2 ticks exit plus modeled entry spread/slippage','intrabar_collision':'stop first'},'limitations':['Imported Pine libraries are causally ported, not byte-for-byte TradingView execution.','Single 24h comparison is exploratory.']}
    result['variants']={m:sim(rows,sigs,start,end,tick,m) for m in ('classic_2r','classic_3r','lock_2r','trail_3r')}; Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8'); print('RESULT_JSON='+json.dumps({m:{k:v for k,v in x.items() if k!='trades_detail'} for m,x in result['variants'].items()},ensure_ascii=False))
if __name__=='__main__':
 p=argparse.ArgumentParser(); p.add_argument('--symbol',default='SPKTRY');p.add_argument('--hours',type=int,default=24);p.add_argument('--fetch-days',type=int,default=3);p.add_argument('--end-minutes-ago',type=int,default=3);p.add_argument('--output',required=True);asyncio.run(main(p.parse_args()))
