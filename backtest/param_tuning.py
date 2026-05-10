"""
针对持股2天胜率最高的策略进行参数调优。
单次扫描所有股票，同时测试多组参数。
"""

import os, sys, time
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from strategy import HIST_CACHE_DIR, prepare_hist_data, check_secondary_filters

HOLD_DAYS = 2


def load_stock(file_path):
    df = pd.read_csv(file_path, dtype={"代码": str})
    code = os.path.basename(file_path).replace("_bs.csv", "")
    if df.empty or len(df) < 80:
        return None
    for col in ["日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额", "涨跌幅"]:
        if col not in df.columns:
            return None
    df["代码"] = code
    df["日期"] = pd.to_datetime(df["日期"])
    for col in ["开盘", "最高", "最低", "收盘", "成交量", "成交额", "涨跌幅"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["开盘", "最高", "最低", "收盘"])
    return df.sort_values("日期").reset_index(drop=True)


# ===== S2 底部放量反转 参数变体 =====
# 原版: distance<0.20, pct>5, vol>avg*2
S2_VARIANTS = [
    # (名称, distance_threshold, pct_threshold, vol_multiplier)
    ("S2_distance15pct_vol1.8", 0.15, 5.0, 1.8),
    ("S2_distance15pct_vol2.0", 0.15, 5.0, 2.0),
    ("S2_distance15pct_vol2.5", 0.15, 5.0, 2.5),
    ("S2_distance20pct_vol1.5", 0.20, 5.0, 1.5),
    ("S2_distance20pct_vol1.8", 0.20, 5.0, 1.8),
    ("S2_distance20pct_vol2.0", 0.20, 5.0, 2.0),  # original
    ("S2_distance20pct_vol2.5", 0.20, 5.0, 2.5),
    ("S2_distance20pct_vol3.0", 0.20, 5.0, 3.0),
    ("S2_distance25pct_vol1.8", 0.25, 5.0, 1.8),
    ("S2_distance25pct_vol2.0", 0.25, 5.0, 2.0),
    ("S2_distance25pct_vol2.5", 0.25, 5.0, 2.5),
    ("S2_pct3_distance20_vol2", 0.20, 3.0, 2.0),
    ("S2_pct4_distance20_vol2", 0.20, 4.0, 2.0),
    ("S2_pct6_distance20_vol2", 0.20, 6.0, 2.0),
    ("S2_pct7_distance20_vol2", 0.20, 7.0, 2.0),
]


def test_s2(row, dist, pct, vol):
    distance_from_40d_low = row["收盘"] / row["过去40日最低价"] - 1
    return (
        distance_from_40d_low < dist
        and row["涨跌幅"] > pct
        and row["成交量"] > row["过去20日平均成交量"] * vol
    )


# ===== M3 主升缩量回调启动 参数变体 =====
# 原版: SMA5<SMA20, SMA60>SMA60_5日前, 收盘>SMA5, vol>avg*1.5
M3_VARIANTS = [
    # (名称, vol_multiplier)
    ("M3_vol1.2", 1.2),
    ("M3_vol1.5", 1.5),  # original
    ("M3_vol1.8", 1.8),
    ("M3_vol2.0", 2.0),
    ("M3_vol2.5", 2.5),
]


def test_m3(row, vol):
    return (
        row["SMA5"] < row["SMA20"]
        and row["SMA60"] > row["SMA60_5日前"]
        and row["收盘"] > row["SMA5"]
        and row["成交量"] > row["过去20日平均成交量"] * vol
    )


# ===== M1 主升箱体突破 参数变体 =====
# 原版: 收盘>过去60日最高收盘, vol>avg*1.5
M1_VARIANTS = [
    ("M1_vol1.3", 1.3),
    ("M1_vol1.5", 1.5),  # original
    ("M1_vol1.8", 1.8),
    ("M1_vol2.0", 2.0),
    ("M1_vol2.5", 2.5),
    ("M1_vol3.0", 3.0),
]


def test_m1(row, vol):
    return (
        row["收盘"] > row["过去60日最高收盘"]
        and row["成交量"] > row["过去20日平均成交量"] * vol
    )


# ===== M4 主升均线多头 参数变体 =====
# 原版: SMA5>SMA10>SMA20>SMA60, pct>2, vol>avg*1.2
M4_VARIANTS = [
    ("M4_pct0_vol1.0", 0.0, 1.0),  # pure MA alignment
    ("M4_pct1_vol1.2", 1.0, 1.2),
    ("M4_pct2_vol1.2", 2.0, 1.2),  # original
    ("M4_pct2_vol1.5", 2.0, 1.5),
    ("M4_pct2_vol1.8", 2.0, 1.8),
    ("M4_pct3_vol1.5", 3.0, 1.5),
    ("M4_pct3_vol1.2", 3.0, 1.2),
]


def test_m4(row, pct, vol):
    return (
        row["SMA5"] > row["SMA10"]
        and row["SMA10"] > row["SMA20"]
        and row["SMA20"] > row["SMA60"]
        and row["涨跌幅"] > pct
        and row["成交量"] > row["过去20日平均成交量"] * vol
    )


# ===== S1 箱体突破 参数变体 =====
# 原版: 收盘>过去60日最高价, vol>avg*1.3, amp<=0.20
S1_VARIANTS = [
    ("S1_amp15_vol1.3", 0.15, 1.3),
    ("S1_amp15_vol1.5", 0.15, 1.5),
    ("S1_amp20_vol1.3", 0.20, 1.3),  # original
    ("S1_amp20_vol1.5", 0.20, 1.5),
    ("S1_amp20_vol1.8", 0.20, 1.8),
    ("S1_amp25_vol1.5", 0.25, 1.5),
    ("S1_amp25_vol1.3", 0.25, 1.3),
]


def test_s1(row, amp, vol):
    return (
        row["收盘"] > row["过去60日最高价"]
        and row["成交量"] > row["过去20日平均成交量"] * vol
        and row["过去20日实体振幅"] <= amp
    )


# Combined variant definitions
ALL_VARIANTS = []

for name, dist, pct, vol in S2_VARIANTS:
    ALL_VARIANTS.append((name, lambda r, d=dist, p=pct, v=vol: test_s2(r, d, p, v)))

for name, vol in M3_VARIANTS:
    ALL_VARIANTS.append((name, lambda r, v=vol: test_m3(r, v)))

for name, vol in M1_VARIANTS:
    ALL_VARIANTS.append((name, lambda r, v=vol: test_m1(r, v)))

for name, pct, vol in M4_VARIANTS:
    ALL_VARIANTS.append((name, lambda r, p=pct, v=vol: test_m4(r, p, v)))

for name, amp, vol in S1_VARIANTS:
    ALL_VARIANTS.append((name, lambda r, a=amp, v=vol: test_s1(r, a, v)))


def test_all_variants():
    files = sorted([f for f in os.listdir(HIST_CACHE_DIR) if f.endswith("_bs.csv")])
    total = len(files)

    # Initialize accumulators
    acc = {}
    for name, _ in ALL_VARIANTS:
        acc[name] = {"signals": 0, "wins": 0, "returns": []}

    need_cols = [
        "SMA5", "SMA10", "SMA20", "SMA60",
        "过去60日最高价", "过去60日最高收盘", "过去60日最低收盘",
        "过去40日最低价", "过去20日实体振幅", "过去20日平均成交量",
        "过去20日日均成交额", "近15日涨停次数", "SMA60_5日前",
    ]

    t0 = time.time()
    for fi, fname in enumerate(files, 1):
        file_path = os.path.join(HIST_CACHE_DIR, fname)
        raw_df = load_stock(file_path)
        if raw_df is None:
            continue

        df = prepare_hist_data(raw_df.copy())
        df = df.sort_values("日期").reset_index(drop=True)

        for i in range(65, len(df) - HOLD_DAYS - 1):
            row = df.iloc[i]
            if row[need_cols].isna().any():
                continue
            if not check_secondary_filters(row):
                continue

            buy_price = df.iloc[i + 1]["开盘"]
            sell_price = df.iloc[i + HOLD_DAYS]["收盘"]
            if pd.isna(buy_price) or pd.isna(sell_price) or buy_price <= 0:
                continue

            ret = (sell_price / buy_price - 1) * 100

            for name, func in ALL_VARIANTS:
                if func(row):
                    acc[name]["signals"] += 1
                    acc[name]["returns"].append(ret)
                    if ret > 0:
                        acc[name]["wins"] += 1

        if fi % 300 == 0:
            print(f"  进度: {fi}/{total} ({time.time() - t0:.0f}s)")

    print(f"\n完成: {time.time() - t0:.0f}s\n")

    # Build results
    results = []
    for name, d in acc.items():
        cnt = d["signals"]
        if cnt < 20:
            continue
        rets = d["returns"]
        wr = d["wins"] / cnt * 100
        avg_ret = sum(rets) / len(rets)
        med = sorted(rets)[len(rets) // 2]
        results.append((name, cnt, d["wins"], cnt - d["wins"], round(wr, 2), round(avg_ret, 2), round(med, 2)))

    results.sort(key=lambda r: r[4], reverse=True)

    print("=" * 100)
    print("  策略参数调优结果 - 持股2天 (按胜率排序)")
    print("=" * 100)
    print(f"{'变体名称':<32} {'信号数':>6} {'盈利':>6} {'亏损':>6} {'胜率%':>8} {'平均收益%':>10} {'中位数%':>8}")
    print("-" * 90)
    for name, cnt, w, l, wr, av, md in results:
        marker = " <-- ORIGINAL" if any(k in name for k in ["S2_distance20pct_vol2.0 ", "M3_vol1.5 ", "M1_vol1.5 ", "M4_pct2_vol1.2 ", "S1_amp20_vol1.3 "]) else ""
        print(f"{name:<32} {cnt:>6} {w:>6} {l:>6} {wr:>8.2f} {av:>10.2f} {md:>8.2f}{marker}")

    # Top 5 by win rate
    print("\n\nTOP 5 最佳参数配置:")
    for rank, (name, cnt, w, l, wr, av, md) in enumerate(results[:5], 1):
        print(f"  {rank}. {name} | 胜率={wr}% | 信号={cnt} | 平均收益={av}%")


if __name__ == "__main__":
    test_all_variants()
