"""
全策略参数调优：6原始 + 4新增 = 10策略，持股5天。
单次扫描所有股票，同时测试所有参数变体，按胜率排序。
"""

import os, sys, time
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
import numpy as np
from strategy import HIST_CACHE_DIR, prepare_hist_data, check_secondary_filters

HOLD_DAYS = 5  # 持股5天


def load_stock(file_path):
    df = pd.read_csv(file_path, dtype={"代码": str})
    if df.empty or len(df) < 80:
        return None
    for col in ["日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额", "涨跌幅"]:
        if col not in df.columns:
            return None
    df["日期"] = pd.to_datetime(df["日期"])
    for col in ["开盘", "最高", "最低", "收盘", "成交量", "成交额", "涨跌幅"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["开盘", "最高", "最低", "收盘"])
    return df.sort_values("日期").reset_index(drop=True)


# ============================================================================
# 策略变体定义：(名称, 检测函数, 分类)
# ============================================================================

ALL_VARIANTS = []

# ---- S1 箱体突破 ----
S1_VARIANTS = [
    ("S1_amp15_vol1.3", 0.15, 1.3),
    ("S1_amp15_vol1.5", 0.15, 1.5),
    ("S1_amp20_vol1.3_原版", 0.20, 1.3),
    ("S1_amp20_vol1.5", 0.20, 1.5),
    ("S1_amp20_vol1.8", 0.20, 1.8),
    ("S1_amp20_vol2.0", 0.20, 2.0),
    ("S1_amp25_vol1.5", 0.25, 1.5),
]

for name, amp, vol in S1_VARIANTS:
    ALL_VARIANTS.append((name, "S1-箱体突破",
        lambda r, a=amp, v=vol: r["收盘"] > r["过去60日最高价"]
        and r["成交量"] > r["过去20日平均成交量"] * v
        and r["过去20日实体振幅"] <= a))

# ---- S2 底部放量反转 ----
S2_VARIANTS = [
    ("S2_dist15_pct5_vol2.0", 0.15, 5.0, 2.0),
    ("S2_dist15_pct5_vol2.5", 0.15, 5.0, 2.5),
    ("S2_dist20_pct4_vol1.8", 0.20, 4.0, 1.8),
    ("S2_dist20_pct4_vol2.0", 0.20, 4.0, 2.0),
    ("S2_dist20_pct5_vol1.8", 0.20, 5.0, 1.8),
    ("S2_dist20_pct5_vol2.0_原版", 0.20, 5.0, 2.0),
    ("S2_dist20_pct5_vol2.5", 0.20, 5.0, 2.5),
    ("S2_dist20_pct5_vol3.0", 0.20, 5.0, 3.0),
    ("S2_dist20_pct6_vol2.0", 0.20, 6.0, 2.0),
    ("S2_dist20_pct7_vol2.5", 0.20, 7.0, 2.5),
    ("S2_dist25_pct5_vol1.8", 0.25, 5.0, 1.8),
    ("S2_dist25_pct5_vol2.0", 0.25, 5.0, 2.0),
    ("S2_dist25_pct5_vol2.5", 0.25, 5.0, 2.5),
]

for name, dist, pct, vol in S2_VARIANTS:
    ALL_VARIANTS.append((name, "S2-底部放量反转",
        lambda r, d=dist, p=pct, v=vol:
        r["收盘"] / r["过去40日最低价"] - 1 < d
        and r["涨跌幅"] > p
        and r["成交量"] > r["过去20日平均成交量"] * v))

# ---- M1 主升箱体突破 ----
M1_VARIANTS = [
    ("M1_vol1.3", 1.3),
    ("M1_vol1.5_原版", 1.5),
    ("M1_vol1.8", 1.8),
    ("M1_vol2.0", 2.0),
    ("M1_vol2.5", 2.5),
    ("M1_vol3.0", 3.0),
]

for name, vol in M1_VARIANTS:
    ALL_VARIANTS.append((name, "M1-主升箱体突破",
        lambda r, v=vol: r["收盘"] > r["过去60日最高收盘"]
        and r["成交量"] > r["过去20日平均成交量"] * v))

# ---- M2 主升底部反转 ----
M2_VARIANTS = [
    ("M2_dist20_pct4_vol1.8", 0.20, 4.0, 1.8),
    ("M2_dist20_pct5_vol2.0", 0.20, 5.0, 2.0),
    ("M2_dist25_pct4_vol1.8", 0.25, 4.0, 1.8),
    ("M2_dist25_pct5_vol1.8", 0.25, 5.0, 1.8),
    ("M2_dist30_pct5_vol2.0_原版", 0.30, 5.0, 2.0),
    ("M2_dist30_pct6_vol2.0", 0.30, 6.0, 2.0),
    ("M2_dist30_pct5_vol2.5", 0.30, 5.0, 2.5),
]

for name, dist, pct, vol in M2_VARIANTS:
    ALL_VARIANTS.append((name, "M2-主升底部反转",
        lambda r, d=dist, p=pct, v=vol:
        r["收盘"] / r["过去60日最低收盘"] - 1 < d
        and r["涨跌幅"] > p
        and r["成交量"] > r["过去20日平均成交量"] * v))

# ---- M3 主升缩量回调 ----
M3_VARIANTS = [
    ("M3_vol1.2", 1.2),
    ("M3_vol1.5_原版", 1.5),
    ("M3_vol1.8", 1.8),
    ("M3_vol2.0", 2.0),
    ("M3_vol2.5", 2.5),
]

for name, vol in M3_VARIANTS:
    ALL_VARIANTS.append((name, "M3-主升缩量回调",
        lambda r, v=vol:
        r["SMA5"] < r["SMA20"]
        and r["SMA60"] > r["SMA60_5日前"]
        and r["收盘"] > r["SMA5"]
        and r["成交量"] > r["过去20日平均成交量"] * v))

# ---- M4 主升均线多头 ----
M4_VARIANTS = [
    ("M4_pct0_vol1.0", 0.0, 1.0),
    ("M4_pct1_vol1.2", 1.0, 1.2),
    ("M4_pct2_vol1.0", 2.0, 1.0),
    ("M4_pct2_vol1.2_原版", 2.0, 1.2),
    ("M4_pct2_vol1.5", 2.0, 1.5),
    ("M4_pct2_vol1.8", 2.0, 1.8),
    ("M4_pct3_vol1.2", 3.0, 1.2),
    ("M4_pct3_vol1.5", 3.0, 1.5),
]

for name, pct, vol in M4_VARIANTS:
    ALL_VARIANTS.append((name, "M4-主升均线多头",
        lambda r, p=pct, v=vol:
        r["SMA5"] > r["SMA10"]
        and r["SMA10"] > r["SMA20"]
        and r["SMA20"] > r["SMA60"]
        and r["涨跌幅"] > p
        and r["成交量"] > r["过去20日平均成交量"] * v))

# ---- 策略A 竞价追涨 (1.1) ----
A_VARIANTS = [
    # (name, gap_min, gap_max, today_pct_min, vol_mult)
    ("A1_gap2-5_pct5_vol1.3", 2.0, 5.0, 5.0, 1.3),
    ("A2_gap3-6_pct5_vol1.5", 3.0, 6.0, 5.0, 1.5),
    ("A3_gap3-6_pct7_vol1.5_原版", 3.0, 6.0, 7.0, 1.5),
    ("A4_gap3-6_pct7_vol2.0", 3.0, 6.0, 7.0, 2.0),
    ("A5_gap3-7_pct5_vol1.5", 3.0, 7.0, 5.0, 1.5),
    ("A6_gap2-6_pct5_vol2.0", 2.0, 6.0, 5.0, 2.0),
    ("A7_gap3-5_pct7_vol1.5", 3.0, 5.0, 7.0, 1.5),
]

for name, gmin, gmax, tpct, vol in A_VARIANTS:
    def make_a_check(gmin, gmax, tpct, vol):
        def check(row, prev_row):
            if prev_row is None:
                return False
            if pd.isna(prev_row["涨跌幅"]) or prev_row["涨跌幅"] < 9.9:
                return False
            yc = prev_row["收盘"]
            to = row["开盘"]
            if pd.isna(yc) or pd.isna(to) or yc <= 0:
                return False
            gap = (to / yc - 1) * 100
            if gap < gmin or gap > gmax:
                return False
            if pd.isna(row["涨跌幅"]) or row["涨跌幅"] < tpct:
                return False
            avg_vol = row["过去20日平均成交量"]
            if pd.isna(avg_vol) or avg_vol <= 0:
                return False
            if row["成交量"] < avg_vol * vol:
                return False
            return True
        return check
    # We need a wrapper that takes (row, prev_row) and returns bool
    ALL_VARIANTS.append((name, "策略A-竞价追涨", make_a_check(gmin, gmax, tpct, vol)))

# ---- 策略B 龙头回调 (1.2) ----
B_VARIANTS = [
    # (name, rise_pct_min, pullback_days_max, pullback_pct_max)
    ("B1_rise15_days5_pb30", 15.0, 5, 30.0),
    ("B2_rise15_days8_pb40", 15.0, 8, 40.0),
    ("B3_rise20_days8_pb50_原版", 20.0, 8, 50.0),
    ("B4_rise20_days5_pb30", 20.0, 5, 30.0),
    ("B5_rise20_days5_pb50", 20.0, 5, 50.0),
    ("B6_rise20_days10_pb40", 20.0, 10, 40.0),
    ("B7_rise25_days8_pb40", 25.0, 8, 40.0),
    ("B8_rise25_days5_pb30", 25.0, 5, 30.0),
]

for name, rise_min, pb_days_max, pb_pct_max in B_VARIANTS:
    def make_b_check(rise_min, pb_days_max, pb_pct_max):
        def check(df, idx):
            if idx < 20:
                return False
            today_close = df.iloc[idx]["收盘"]
            if pd.isna(today_close) or today_close <= 0:
                return False
            lookback_start = max(0, idx - 13)
            segment = df.iloc[lookback_start:idx + 1]
            closes = segment["收盘"].values
            if len(closes) < 5:
                return False
            low_idx = int(np.argmin(closes))
            high_idx = int(np.argmax(closes))
            low_p = closes[low_idx]
            high_p = closes[high_idx]
            if low_p <= 0 or high_p <= 0:
                return False
            rise_pct = (high_p / low_p - 1) * 100
            if rise_pct < rise_min:
                return False
            if high_idx <= low_idx:
                return False
            if today_close >= high_p * 0.99:
                return False
            pb_days = len(segment) - 1 - high_idx
            if pb_days < 2 or pb_days > pb_days_max:
                return False
            pb_pct = (high_p - today_close) / (high_p - low_p) * 100
            if pb_pct > pb_pct_max:
                return False
            return True
        return check
    ALL_VARIANTS.append((name, "策略B-龙头回调", make_b_check(rise_min, pb_days_max, pb_pct_max)))

# ---- 策略C 追涨突破 (1.3) ----
C_VARIANTS = [
    # (name, vol_vs_yesterday, vol_vs_avg, pct_min, lookback_days)
    ("C1_volY1.3_volA2.0_pct3_lb13", 1.3, 2.0, 3.0, 13),
    ("C2_volY1.5_volA3.0_pct5_lb13_原版", 1.5, 3.0, 5.0, 13),
    ("C3_volY1.5_volA2.0_pct5_lb13", 1.5, 2.0, 5.0, 13),
    ("C4_volY1.5_volA2.5_pct5_lb10", 1.5, 2.5, 5.0, 10),
    ("C5_volY1.5_volA3.0_pct3_lb13", 1.5, 3.0, 3.0, 13),
    ("C6_volY2.0_volA3.0_pct5_lb13", 2.0, 3.0, 5.0, 13),
    ("C7_volY1.5_volA2.0_pct3_lb20", 1.5, 2.0, 3.0, 20),
    ("C8_volY2.0_volA4.0_pct5_lb13", 2.0, 4.0, 5.0, 13),
]

for name, volY, volA, pct, lb in C_VARIANTS:
    def make_c_check(volY, volA, pct, lb):
        def check(row, prev_row, high_lb_col):
            if prev_row is None:
                return False
            yv = prev_row["成交量"]
            tv = row["成交量"]
            if pd.isna(yv) or pd.isna(tv) or yv <= 0:
                return False
            if tv < yv * volY:
                return False
            avg_vol = row["过去20日平均成交量"]
            if pd.isna(avg_vol) or avg_vol <= 0:
                return False
            if tv < avg_vol * volA:
                return False
            avg_amount = row["过去20日日均成交额"]
            if pd.isna(avg_amount) or avg_amount < 50_000_000:
                return False
            if pd.isna(row["涨跌幅"]) or row["涨跌幅"] < pct:
                return False
            high = row.get(high_lb_col)
            if high is None or pd.isna(high) or high <= 0:
                return False
            if row["收盘"] <= high:
                return False
            return True
        return check
    ALL_VARIANTS.append((name, "策略C-追涨突破", make_c_check(volY, volA, pct, lb)))

# ---- 策略D 断板反包 (1.4) ----
D_VARIANTS = [
    # (name, min_consecutive_limits, reversal_pct_min, broken_pct_min)
    ("D1_limit2_rev1_brok-8", 2, 1.0, -8.0),
    ("D2_limit2_rev2_brok-8_原版", 2, 2.0, -8.0),
    ("D3_limit2_rev2_brok-5", 2, 2.0, -5.0),
    ("D4_limit3_rev1_brok-8", 3, 1.0, -8.0),
    ("D5_limit3_rev2_brok-5", 3, 2.0, -5.0),
    ("D6_limit2_rev0_brok-8", 2, 0.0, -8.0),
    ("D7_limit3_rev0_brok-9", 3, 0.0, -9.0),
]

for name, min_limits, rev_pct, brk_pct in D_VARIANTS:
    def make_d_check(min_limits, rev_pct, brk_pct):
        def check(df, idx):
            if idx < 10:
                return False
            today = df.iloc[idx]
            if pd.isna(today["收盘"]) or today["收盘"] <= 0:
                return False
            broken = df.iloc[idx - 1]
            bp = broken["涨跌幅"]
            bl = broken["最低"]
            bh = max(broken["开盘"], broken["收盘"])
            if pd.isna(bp) or pd.isna(bl):
                return False
            if bp >= 9.95:
                return False
            # Count consecutive limit-ups before broken day
            climits = 0
            for j in range(2, 10):
                ci = idx - j
                if ci < 0:
                    break
                if df.iloc[ci]["涨跌幅"] >= 9.95:
                    climits += 1
                else:
                    break
            if climits < min_limits:
                return False
            if today["收盘"] <= bh:
                return False
            tp = today["涨跌幅"]
            if pd.isna(tp) or tp < rev_pct:
                return False
            if bp < brk_pct:
                return False
            avg_vol = today.get("过去20日平均成交量")
            if avg_vol is None or pd.isna(avg_vol) or avg_vol <= 0:
                return False
            if today["成交量"] < avg_vol * 0.8:
                return False
            return True
        return check
    ALL_VARIANTS.append((name, "策略D-断板反包", make_d_check(min_limits, rev_pct, brk_pct)))


# ============================================================================
# 主测试
# ============================================================================

def run_all():
    print(f"策略参数调优：{len(ALL_VARIANTS)} 个变体 | 持股{HOLD_DAYS}天")
    print(f"策略分类: S1箱体突破, S2底部反转, M1-M4主升, A竞价追涨, B龙头回调, C追涨突破, D断板反包")
    print("=" * 80)

    files = sorted([f for f in os.listdir(HIST_CACHE_DIR) if f.endswith("_bs.csv")])
    total_files = len(files)
    print(f"待回测股票: {total_files}")

    # Initialize accumulators for ALL variants
    acc = {}
    for name, cat, _ in ALL_VARIANTS:
        acc[name] = {"signals": 0, "wins": 0, "returns": [], "category": cat}

    need_cols = [
        "SMA5", "SMA10", "SMA20", "SMA60",
        "过去60日最高价", "过去60日最高收盘", "过去60日最低收盘",
        "过去40日最低价", "过去20日实体振幅", "过去20日平均成交量",
        "过去20日日均成交额", "近15日涨停次数", "SMA60_5日前",
    ]

    t0 = time.time()
    stocks_done = 0

    for fi, fname in enumerate(files, 1):
        file_path = os.path.join(HIST_CACHE_DIR, fname)
        raw_df = load_stock(file_path)
        if raw_df is None:
            continue

        stocks_done += 1
        df = prepare_hist_data(raw_df.copy())
        df = df.sort_values("日期").reset_index(drop=True)
        # For strategies C and B: compute extra columns
        df["过去13日最高价"] = df["最高"].shift(1).rolling(13).max()
        df["过去10日最高价"] = df["最高"].shift(1).rolling(10).max()
        df["过去20日最高价"] = df["最高"].shift(1).rolling(20).max()

        for i in range(65, len(df) - HOLD_DAYS - 1):
            row = df.iloc[i]
            if row[need_cols].isna().any():
                continue
            if not check_secondary_filters(row):
                continue

            prev_row = df.iloc[i - 1] if i >= 1 else None

            buy_price = df.iloc[i + 1]["开盘"]
            sell_price = df.iloc[i + HOLD_DAYS]["收盘"]
            if pd.isna(buy_price) or pd.isna(sell_price) or buy_price <= 0:
                continue

            ret = (sell_price / buy_price - 1) * 100
            is_win = ret > 0

            for name, cat, func in ALL_VARIANTS:
                try:
                    hit = False
                    if cat.startswith("策略A"):
                        hit = func(row, prev_row)
                    elif cat.startswith("策略B") or cat.startswith("策略D"):
                        hit = func(df, i)
                    elif cat.startswith("策略C"):
                        if "lb13" in name or "原版" in name or "lb13" in name:
                            hit = func(row, prev_row, "过去13日最高价")
                        elif "lb10" in name:
                            hit = func(row, prev_row, "过去10日最高价")
                        else:
                            hit = func(row, prev_row, "过去20日最高价")
                    else:
                        hit = func(row)

                    if hit:
                        acc[name]["signals"] += 1
                        acc[name]["returns"].append(ret)
                        if is_win:
                            acc[name]["wins"] += 1
                except Exception:
                    pass

        if fi % 200 == 0:
            elapsed = time.time() - t0
            remaining = elapsed / fi * (total_files - fi)
            srcount = sum(d["signals"] for d in acc.values())
            print(f"  进度: {fi}/{total_files} | 耗时: {elapsed:.0f}s | 剩余: {remaining:.0f}s | 累计信号: {srcount}")

    print(f"\n完成: {stocks_done}只股票 | 总耗时: {time.time() - t0:.0f}s")

    # Build results
    results = []
    for name, d in acc.items():
        cnt = d["signals"]
        if cnt < 15:
            continue
        rets = d["returns"]
        wins = d["wins"]
        wr = wins / cnt * 100
        avg_ret = sum(rets) / len(rets)
        med = sorted(rets)[len(rets) // 2]
        avg_win = sum(r for r in rets if r > 0) / max(1, sum(1 for r in rets if r > 0))
        avg_loss = sum(r for r in rets if r <= 0) / max(1, sum(1 for r in rets if r <= 0))
        pl = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
        results.append({
            "variant": name, "category": d["category"],
            "signals": cnt, "wins": wins, "losses": cnt - wins,
            "win_rate": wr, "avg_return": avg_ret, "median": med,
            "max_gain": max(rets), "max_loss": min(rets),
            "avg_win": avg_win, "avg_loss": avg_loss, "pl_ratio": pl,
        })

    results.sort(key=lambda r: r["win_rate"], reverse=True)

    # --- Print full results ---
    print("\n")
    print("=" * 110)
    print(f"  全策略参数调优结果 - 持股{HOLD_DAYS}天 (按胜率排序)")
    print("=" * 110)
    hdr = f"{'变体':<38} {'分类':<18} {'信号':>6} {'胜率%':>8} {'平均%':>8} {'中位%':>8} {'盈亏比':>7} {'最大盈%':>8} {'最大亏%':>8}"
    print(hdr)
    print("-" * 110)

    for r in results:
        marker = " [原版]" if "原版" in r["variant"] else ""
        print(f"{r['variant']:<38} {r['category']:<18} {r['signals']:>6} {r['win_rate']:>8.2f} {r['avg_return']:>8.2f} {r['median']:>8.2f} {r['pl_ratio']:>7.2f} {r['max_gain']:>8.2f} {r['max_loss']:>8.2f}{marker}")

    # --- Best per category ---
    print("\n\n" + "=" * 80)
    print("  各策略分类最佳参数 (按胜率)")
    print("=" * 80)

    categories_order = ["S1-箱体突破", "S2-底部放量反转", "M1-主升箱体突破", "M2-主升底部反转",
                        "M3-主升缩量回调", "M4-主升均线多头",
                        "策略A-竞价追涨", "策略B-龙头回调", "策略C-追涨突破", "策略D-断板反包"]

    best_per_cat = {}
    for r in results:
        cat = r["category"]
        if cat not in best_per_cat or r["win_rate"] > best_per_cat[cat]["win_rate"]:
            best_per_cat[cat] = r

    for cat in categories_order:
        if cat in best_per_cat:
            r = best_per_cat[cat]
            print(f"  {cat:<20} {r['variant']:<35} 胜率={r['win_rate']:.2f}%  信号={r['signals']}  平均收益={r['avg_return']:.2f}%  盈亏比={r['pl_ratio']:.2f}")

    # --- TOP 10 overall ---
    print("\n\n" + "=" * 60)
    print("  TOP 10 最高胜率策略变体")
    print("=" * 60)
    for rank, r in enumerate(results[:10], 1):
        print(f"  {rank:>2}. {r['variant']:<38} ({r['category']})  胜率={r['win_rate']:.2f}%  信号={r['signals']}")

    # --- Compare originals ---
    print("\n\n" + "=" * 60)
    print("  原版策略 vs 最优版策略对比")
    print("=" * 60)
    originals = [r for r in results if "原版" in r["variant"]]
    print(f"{'策略':<35} {'原版胜率':<10} {'最优胜率':<10} {'提升':<8}")
    print("-" * 65)
    for orig in sorted(originals, key=lambda x: x["category"]):
        cat = orig["category"]
        best = best_per_cat.get(cat)
        if best:
            improvement = best["win_rate"] - orig["win_rate"]
            print(f"{orig['variant']:<35} {orig['win_rate']:.2f}%{'':>4} {best['win_rate']:.2f}%{'':>4} +{improvement:.1f}%{'':>3}")


if __name__ == "__main__":
    run_all()
