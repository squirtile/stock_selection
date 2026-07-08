"""测试涨停回调一日游策略 v2"""
import sys, numpy as np, pandas as pd
sys.path.insert(0, '.')

from strategy import prepare_hist_data, get_hist_data_baostock
from strategies.daily_strategies import LimitUpPullbackDayTradeStrategy

st = LimitUpPullbackDayTradeStrategy()

selected = pd.read_excel(r'output\a_stock_selected.xlsx')
codes = selected['代码'].astype(str).str.zfill(6).tolist()

hits = []
for code in codes:
    try:
        df = get_hist_data_baostock(code, cache_only=True)
        if df.empty: continue
        df = prepare_hist_data(df)
        last = df.iloc[-1]
        if st.match(last):
            days = int(last['涨停距今天数'])
            limit_close = float(last['涨停日收盘'])
            close = float(last['收盘'])
            vol = float(last['成交量'])
            limit_vol = float(last['涨停日成交量'])
            pct = float(last['涨跌幅'])
            limit_low = float(last['涨停日最低价'])
            pos_idx = len(df) - 1
            pullback_df = df.iloc[pos_idx - days + 1:pos_idx + 1]
            pullback_low = pullback_df['最低'].min()
            hits.append({
                '代码': code, '天数': days,
                '涨停价': limit_close, '今日价': close,
                '回调%': round((close/limit_close-1)*100, 1),
                '缩量比': f'{vol/limit_vol*100:.0f}%',
                '涨停低': limit_low, '回调低': round(pullback_low, 2),
                '今日涨跌%': round(pct, 2),
            })
    except Exception as e:
        pass

print(f'\n命中「涨停回调一日游」: {len(hits)} 只\n')
if hits:
    for h in sorted(hits, key=lambda x: x['回调%']):
        print(f"  {h['代码']} | {h['天数']}天前涨停 | "
              f"涨停价{h['涨停价']}→今日{h['今日价']}({h['回调%']}%) | "
              f"缩量至{h['缩量比']} | 涨停低{h['涨停低']} 回调低{h['回调低']} | "
              f"今日涨跌{h['今日涨跌%']}%")
else:
    print('无命中。')
