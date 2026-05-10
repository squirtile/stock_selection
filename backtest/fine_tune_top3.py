"""
Focused parameter sweep for top-3 strategies with 3-day holding.
N22-V型反转, N1-双底放量反转, M2-主升底部反转
"""
import os, sys, time
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
import numpy as np
from strategy import HIST_CACHE_DIR, prepare_hist_data, check_secondary_filters

HOLD_DAYS = 3

def load_stock(fp):
    df = pd.read_csv(fp, dtype={"代码": str})
    if df.empty or len(df) < 80: return None
    for c in ["日期","开盘","最高","最低","收盘","成交量","成交额","涨跌幅"]:
        if c not in df.columns: return None
    df["日期"] = pd.to_datetime(df["日期"])
    for c in ["开盘","最高","最低","收盘","成交量","成交额","涨跌幅"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["开盘","最高","最低","收盘"])
    return df.sort_values("日期").reset_index(drop=True)

def enrich(df):
    df = df.copy()
    df["昨收"] = df["收盘"].shift(1)
    df["昨开"] = df["开盘"].shift(1)
    df["昨低"] = df["最低"].shift(1)
    df["昨高"] = df["最高"].shift(1)
    df["昨量"] = df["成交量"].shift(1)
    df["昨涨跌"] = df["涨跌幅"].shift(1)
    df["前涨跌"] = df["涨跌幅"].shift(2)
    df["SMA5"] = df["收盘"].rolling(5).mean()
    df["SMA10"] = df["收盘"].rolling(10).mean()
    df["SMA20"] = df["收盘"].rolling(20).mean()
    df["SMA60"] = df["收盘"].rolling(60).mean()
    df["SMA60_5d"] = df["SMA60"].shift(5)
    df["均量"] = df["过去20日平均成交量"]
    df["收阳"] = (df["收盘"] > df["开盘"]).fillna(0).astype(int)
    df["昨收阳"] = df["收阳"].shift(1).fillna(0).astype(int)
    return df

# ============================================================
# N22 V型反转 - Fine sweep
# Params: dist (distance from 40-day low), pct (today's gain), vol (volume multiple)
# ============================================================
N22_VARIANTS = []
for dist in [0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25]:
    for pct in [2.0, 2.5, 3.0, 3.5, 4.0, 5.0]:
        for vol in [1.2, 1.5, 1.8, 2.0, 2.5]:
            name = f"N22_d{dist*100:.0f}_p{pct:.0f}_v{vol:.1f}"
            N22_VARIANTS.append((name, dist, pct, vol))

# ============================================================
# N1 双底放量反转 - Fine sweep
# ============================================================
N1_VARIANTS = []
for d40 in [0.10, 0.12, 0.15, 0.18, 0.20]:
    for d60 in [0.15, 0.18, 0.20, 0.25, 0.30]:
        for pct in [2.0, 2.5, 3.0, 3.5, 4.0]:
            for vol in [1.3, 1.5, 1.8, 2.0, 2.5]:
                name = f"N1_d40_{d40*100:.0f}_d60_{d60*100:.0f}_p{pct:.0f}_v{vol:.1f}"
                N1_VARIANTS.append((name, d40, d60, pct, vol))

# ============================================================
# M2 主升底部反转 - Fine sweep
# ============================================================
M2_VARIANTS = []
for dist in [0.15, 0.18, 0.20, 0.22, 0.25, 0.28, 0.30, 0.35]:
    for pct in [3.0, 3.5, 4.0, 4.5, 5.0, 6.0]:
        for vol in [1.5, 1.8, 2.0, 2.2, 2.5, 3.0]:
            name = f"M2_d{dist*100:.0f}_p{pct:.0f}_v{vol:.1f}"
            M2_VARIANTS.append((name, dist, pct, vol))

def run():
    all_variants = [
        ("N22-V型反转", N22_VARIANTS),
        ("N1-双底放量反转", N1_VARIANTS),
        ("M2-主升底部反转", M2_VARIANTS),
    ]

    files = sorted([f for f in os.listdir(HIST_CACHE_DIR) if f.endswith("_bs.csv")])
    total = len(files)

    need_cols = [
        "SMA5", "SMA10", "SMA20", "SMA60",
        "过去60日最高价", "过去60日最高收盘", "过去60日最低收盘",
        "过去40日最低价", "过去20日实体振幅", "过去20日平均成交量",
        "过去20日日均成交额", "近15日涨停次数", "SMA60_5日前",
    ]

    t0 = time.time()

    for cat_name, variants in all_variants:
        print(f"\n{'='*80}")
        print(f"  {cat_name} — {len(variants)} parameter combinations")
        print(f"{'='*80}")

        acc = {}
        for name, *params in variants:
            acc[name] = {"signals": 0, "wins": 0, "returns": []}

        for fi, fname in enumerate(files, 1):
            raw = load_stock(os.path.join(HIST_CACHE_DIR, fname))
            if raw is None: continue

            df = prepare_hist_data(raw.copy())
            df = enrich(df)
            df = df.sort_values("日期").reset_index(drop=True)

            for i in range(65, len(df) - HOLD_DAYS - 1):
                row = df.iloc[i]
                if row[need_cols].isna().any(): continue
                if not check_secondary_filters(row): continue

                bp = df.iloc[i+1]["开盘"]
                sp = df.iloc[i+HOLD_DAYS]["收盘"]
                if pd.isna(bp) or pd.isna(sp) or bp <= 0: continue

                ret = (sp/bp - 1) * 100
                iw = ret > 0

                for name, *params in variants:
                    try:
                        hit = False
                        if cat_name == "N22-V型反转":
                            dist, pct, vol = params
                            hit = (row["收盘"]/row["过去40日最低价"]-1 < dist
                                   and row["涨跌幅"] > pct
                                   and row["昨涨跌"] < -1
                                   and row["成交量"] > row["均量"] * vol
                                   and row["收阳"] == 1)
                        elif cat_name == "N1-双底放量反转":
                            d40, d60, pct, vol = params
                            hit = (row["收盘"]/row["过去40日最低价"]-1 < d40
                                   and row["收盘"]/row["过去60日最低收盘"]-1 < d60
                                   and row["涨跌幅"] > pct
                                   and row["成交量"] > row["均量"] * vol
                                   and row["收阳"] == 1)
                        elif cat_name == "M2-主升底部反转":
                            dist, pct, vol = params
                            hit = (row["收盘"]/row["过去60日最低收盘"]-1 < dist
                                   and row["涨跌幅"] > pct
                                   and row["成交量"] > row["均量"] * vol)

                        if hit:
                            acc[name]["signals"] += 1
                            acc[name]["returns"].append(ret)
                            if iw: acc[name]["wins"] += 1
                    except Exception:
                        pass

            if fi % 400 == 0:
                e = time.time() - t0
                sc = sum(d["signals"] for d in acc.values())
                print(f"  {fi}/{total} | {e:.0f}s | signals: {sc}")

        # Build results, filter for meaningful signal counts
        results = []
        for name, d in acc.items():
            cnt = d["signals"]
            if cnt < 10: continue
            rets = d["returns"]
            w = d["wins"]
            wr = w/cnt*100
            avg_r = sum(rets)/len(rets)
            avg_w = sum(r for r in rets if r>0)/max(1,sum(1 for r in rets if r>0))
            avg_l = sum(r for r in rets if r<=0)/max(1,sum(1 for r in rets if r<=0))
            pl = abs(avg_w/avg_l) if avg_l!=0 else 99
            results.append((name, cnt, wr, avg_r, avg_w, avg_l, pl, max(rets), min(rets)))

        results.sort(key=lambda x: x[2], reverse=True)

        # Print TOP 20 for this strategy
        print(f"\n  TOP 20 (sorted by win rate):")
        print(f"  {'Rank':<4} {'Name':<50} {'Signals':>6} {'WR%':>8} {'Avg%':>8} {'P/L':>7} {'MaxW%':>8} {'MaxL%':>8}")
        print(f"  {'-'*107}")
        for rank, r in enumerate(results[:20], 1):
            print(f"  {rank:<4} {r[0]:<50} {r[1]:>6} {r[2]:>8.2f} {r[3]:>8.2f} {r[6]:>7.2f} {r[7]:>8.2f} {r[8]:>8.2f}")

        # Best overall
        best = results[0]
        print(f"\n  >> BEST: {best[0]} — WR={best[2]:.2f}% signals={best[1]} avg={best[3]:.2f}% PL={best[6]:.2f}")

        # High WR + decent signals (>=50 signals)
        decent = [r for r in results if r[1] >= 50]
        if decent:
            best_decent = decent[0]
            print(f"  >> BEST (>=50 signals): {best_decent[0]} — WR={best_decent[2]:.2f}% signals={best_decent[1]} avg={best_decent[3]:.2f}%")

        # High WR + good signals (>=100 signals)
        good = [r for r in results if r[1] >= 100]
        if good:
            best_good = good[0]
            print(f"  >> BEST (>=100 signals): {best_good[0]} — WR={best_good[2]:.2f}% signals={best_good[1]} avg={best_good[3]:.2f}%")

        # Save all results
        os.makedirs("output/backtest", exist_ok=True)
        df_out = pd.DataFrame(results, columns=["name","signals","wr","avg","avg_w","avg_l","pl","max_g","max_l"])
        df_out.to_csv(f"output/backtest/fine_tune_{cat_name}_hold3d.csv", index=False, encoding="utf-8-sig")

    print(f"\n\nTotal time: {time.time()-t0:.0f}s")

if __name__ == "__main__":
    run()
