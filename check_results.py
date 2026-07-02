# -*- coding: utf-8 -*-
"""筛选高胜率模型"""
import glob, pandas as pd, sys

bt_files = sorted(glob.glob('output/ml_grid_test/backtest_*_tpl_*.xlsx'))
print(f"已生成 {len(bt_files)} 个回测报告")

results = []
for f in bt_files:
    try:
        df = pd.read_excel(f, sheet_name='总体统计', nrows=5)
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                d = row.to_dict()
                d['文件'] = f
                results.append(d)
    except:
        pass

if not results:
    print("未能读取任何回测统计")
    sys.exit(0)

df_r = pd.DataFrame(results)
if '胜率%' in df_r.columns:
    df_r['胜率%'] = pd.to_numeric(df_r['胜率%'], errors='coerce')
if '信号次数' in df_r.columns:
    df_r['信号次数'] = pd.to_numeric(df_r['信号次数'], errors='coerce')

top_win = df_r['胜率%'].max()
print(f"全部最高胜率: {top_win:.1f}%")

# 筛选: 胜率>65% 且 信号>100
mask = (df_r['胜率%'] > 65) & (df_r['信号次数'] > 100)
good = df_r[mask].sort_values('胜率%', ascending=False)
print(f"胜率>65% 且 信号>100: {len(good)} 个")

if not good.empty:
    cols = ['文件','持有天数','信号次数','胜率%','平均收益率%','盈亏比']
    print(good[[c for c in cols if c in good.columns]].to_string())
else:
    mask2 = (df_r['胜率%'] > 60) & (df_r['信号次数'] > 50)
    relaxed = df_r[mask2].sort_values('胜率%', ascending=False).head(20)
    print(f"放宽 胜率>60% 信号>50: {len(relaxed)} 个")
    if not relaxed.empty:
        cols = ['持有天数','信号次数','胜率%','平均收益率%','盈亏比']
        for _, r in relaxed.iterrows():
            print(f"  {r['文件']}")
            for c in cols:
                if c in r and pd.notna(r[c]):
                    print(f"    {c}: {r[c]}")
            print()
