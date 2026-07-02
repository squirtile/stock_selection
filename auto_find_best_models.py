# -*- coding: utf-8 -*-
"""全自动：扫描强势股 → grid_test → 筛选胜率>65%+信号>100的pkl"""
import os, sys, glob, re, subprocess, time
import pandas as pd, numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))

def find_strong_stocks(top_n=6):
    hist_dir = os.path.join(ROOT, "cache", "hist")
    results = []
    files = glob.glob(os.path.join(hist_dir, "*.csv"))
    print(f"扫描 {len(files)} 个日线...")
    for csv_file in files:
        m = re.search(r'(\d{6})', os.path.basename(csv_file))
        if not m: continue
        code = m.group(1)
        try:
            df = pd.read_csv(csv_file)
            if len(df) < 70: continue
            close = pd.to_numeric(df.get('收盘', df.get('close', pd.Series())), errors='coerce')
            pct_col = next((c for c in ['涨跌幅','pct_chg'] if c in df.columns), None)
            if pct_col is None or close.empty: continue
            pct = pd.to_numeric(df[pct_col], errors='coerce')
            c10 = close.tail(10)
            if len(c10.dropna()) < 5: continue
            ret10 = (c10.iloc[-1]/c10.iloc[0]-1)*100
            ma20 = close.rolling(20).mean(); ma60 = close.rolling(60).mean()
            score = ret10 * 0.5
            if close.iloc[-1] > ma20.iloc[-1]: score += 15
            if close.iloc[-1] > ma60.iloc[-1]: score += 15
            if pd.notna(ma20.iloc[-1]) and pd.notna(ma60.iloc[-1]) and ma20.iloc[-1] > ma60.iloc[-1]: score += 15
            results.append({'代码':code,'得分':round(score,1),'10日涨幅':round(ret10,1)})
        except: pass
    df = pd.DataFrame(results).nlargest(top_n, '得分')
    print(f"Top {top_n}:")
    for _,r in df.iterrows(): print(f"  {r['代码']} 得分{r['得分']} 涨幅{r['10日涨幅']}%")
    return df['代码'].tolist()

def run_grid_test(codes):
    proven = ['002552','002428','601991']
    all_codes = list(dict.fromkeys(codes + proven))
    codes_str = ','.join(all_codes)
    print(f"\n模板股 ({len(all_codes)}只): {codes_str}")
    n = len(all_codes)
    n_combos = n*(n-1)//2
    n_tasks = n_combos * 3 * 3
    print(f"预计: {n_combos}组合 x 3horizon x 3target = {n_tasks} 训练任务")

    cmd = [
        sys.executable, 'cli/ml_grid_test_modified.py',
        '--codes', codes_str,
        '--mode', 'combination', '--combo-size', '2',
        '--threshold', '0.60',
        '--horizons', '3,4,5',
        '--targets', '6,8,10',
        '--hold-days', '3,5',
        '--workers', '8', '--force',
    ]
    print(f"\n{'='*70}\n启动 grid_test\n{'='*70}")
    t0 = time.time()
    r = subprocess.run(cmd, cwd=ROOT)
    elapsed = (time.time()-t0)/60
    print(f"\ngrid_test 完成 耗时{elapsed:.1f}分钟 返回码{r.returncode}")
    return r.returncode == 0

def filter_results():
    bt_files = glob.glob(os.path.join(ROOT, 'output/ml_grid_test/backtest_*_tpl_*.xlsx'))
    print(f"\n扫描 {len(bt_files)} 个回测报告...")
    results = []
    for f in bt_files:
        try:
            df = pd.read_excel(f, sheet_name='按持有期统计', nrows=5)
            for _, row in df.iterrows():
                d = row.to_dict(); d['文件'] = os.path.basename(f)
                results.append(d)
        except: pass
    if not results:
        print("无法读取回测结果"); return
    df_r = pd.DataFrame(results)
    df_r['胜率%'] = pd.to_numeric(df_r['胜率%'], errors='coerce')
    df_r['信号次数'] = pd.to_numeric(df_r['信号次数'], errors='coerce')
    mask = (df_r['胜率%'] > 65) & (df_r['信号次数'] > 100)
    good = df_r[mask].sort_values(['胜率%','信号次数'], ascending=False)
    print(f"\n{'='*70}")
    print(f"胜率>65% 且 信号>100: {len(good)} 个")
    print(f"{'='*70}")
    if not good.empty:
        cols = ['文件','持有天数','信号次数','胜率%','平均收益率%','盈亏比']
        for _,r in good.iterrows():
            print(f"  {r['文件']}")
            for c in cols:
                if c in r: print(f"    {c}: {r[c]}")
            tpl = r['文件'].split('_tpl_')[1].split('_h')[0] if '_tpl_' in r['文件'] else ''
            for pkl in glob.glob(os.path.join(ROOT, 'output/ml_models', f'*{tpl}*.pkl')):
                print(f"    pkl: {os.path.basename(pkl)}")
            print()
    else:
        print("\n没有完全达标的模型。最佳候选：")
        top = df_r.nlargest(20, '胜率%')
        print(f"{'文件':<55} {'持有':>4} {'信号':>8} {'胜率%':>7} {'收益率%':>8}")
        for _,r in top.iterrows():
            fn = r['文件'][:52]
            print(f"{fn:<55} {str(r.get('持有天数','')):>4} {int(r.get('信号次数',0)):>8} {r.get('胜率%',0):>7.1f} {r.get('平均收益率%',0):>8.2f}")

if __name__ == '__main__':
    print("="*70)
    print("全自动：扫强势股→grid_test→筛高胜率模型(>65%,>100信号)")
    print("="*70)
    codes = find_strong_stocks(top_n=6)
    ok = run_grid_test(codes)
    if ok: filter_results()
    else: print("grid_test 失败")
