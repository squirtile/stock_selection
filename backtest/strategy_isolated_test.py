"""
Test each strategy ISOLATED (only that strategy fires) with hold_days=2.
Single pass through data for efficiency.
"""

import os
import sys
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from strategy import (
    HIST_CACHE_DIR, prepare_hist_data, check_secondary_filters,
    check_strategy_1, check_strategy_2,
    check_strategy_1_main_promotion, check_strategy_2_main_promotion,
    check_strategy_3_main_promotion, check_strategy_4_main_promotion,
)

HOLD_DAYS = 2

STRATEGIES = [
    ("S1_箱体突破", check_strategy_1),
    ("S2_底部放量反转", check_strategy_2),
    ("M1_主升箱体突破", check_strategy_1_main_promotion),
    ("M2_主升底部放量反转", check_strategy_2_main_promotion),
    ("M3_主升缩量回调启动", check_strategy_3_main_promotion),
    ("M4_主升均线多头排列", check_strategy_4_main_promotion),
]


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
    df = df.sort_values("日期").reset_index(drop=True)
    return df if len(df) >= 80 else None


def test_all_strategies():
    files = sorted(os.listdir(HIST_CACHE_DIR))
    files = [f for f in files if f.endswith("_bs.csv")]
    total_files = len(files)

    # Per-strategy accumulators
    strat_data = {name: {"signals": 0, "wins": 0, "returns": []} for name, _ in STRATEGIES}

    need_cols = [
        "SMA5", "SMA10", "SMA20", "SMA60",
        "过去60日最高价", "过去60日最高收盘", "过去60日最低收盘",
        "过去40日最低价", "过去20日实体振幅", "过去20日平均成交量",
        "过去20日日均成交额", "近15日涨停次数", "SMA60_5日前",
    ]

    t0 = time.time()
    stocks_processed = 0

    for fi, fname in enumerate(files, 1):
        file_path = os.path.join(HIST_CACHE_DIR, fname)
        raw_df = load_stock(file_path)
        if raw_df is None:
            continue

        stocks_processed += 1
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
            is_win = ret > 0

            # Test each strategy independently on this row
            for name, func in STRATEGIES:
                if func(row):
                    strat_data[name]["signals"] += 1
                    strat_data[name]["returns"].append(ret)
                    if is_win:
                        strat_data[name]["wins"] += 1

        if fi % 200 == 0:
            elapsed = time.time() - t0
            print(f"  进度: {fi}/{total_files} | 耗时: {elapsed:.0f}s")

    print(f"\n处理完成: {stocks_processed} 只股票, 总耗时: {time.time() - t0:.0f}s\n")

    return strat_data


def print_results(strat_data):
    rows = []
    for name, d in strat_data.items():
        cnt = d["signals"]
        wins = d["wins"]
        if cnt == 0:
            continue
        rets = d["returns"]
        win_rate = wins / cnt * 100
        avg_ret = sum(rets) / len(rets)
        median_ret = sorted(rets)[len(rets) // 2]
        avg_win = sum(r for r in rets if r > 0) / max(1, sum(1 for r in rets if r > 0))
        avg_loss = sum(r for r in rets if r <= 0) / max(1, sum(1 for r in rets if r <= 0))
        rows.append({
            "策略": name,
            "信号数": cnt,
            "盈利": wins,
            "亏损": cnt - wins,
            "胜率%": round(win_rate, 2),
            "平均收益%": round(avg_ret, 2),
            "中位数%": round(median_ret, 2),
            "最大收益%": round(max(rets), 2),
            "最大亏损%": round(min(rets), 2),
            "平均盈利%": round(avg_win, 2),
            "平均亏损%": round(avg_loss, 2),
        })

    rows.sort(key=lambda r: r["胜率%"], reverse=True)

    print("=" * 100)
    print("  各策略【独立】回测结果 - 持股2天")
    print("  (仅当该策略单独命中时计入，不受其他策略干扰)")
    print("=" * 100)

    headers = ["策略", "信号数", "盈利", "亏损", "胜率%", "平均收益%", "中位数%", "最大收益%", "最大亏损%", "平均盈利%", "平均亏损%"]
    widths = [24, 8, 8, 8, 8, 10, 8, 10, 10, 10, 10]
    hline = " | ".join(h.ljust(w) for h, w in zip(headers, widths))
    sep = "-+-".join("-" * w for w in widths)
    print(hline)
    print(sep)

    for r in rows:
        parts = [
            r["策略"].ljust(widths[0]),
            str(r["信号数"]).rjust(widths[1]),
            str(r["盈利"]).rjust(widths[2]),
            str(r["亏损"]).rjust(widths[3]),
            f"{r['胜率%']:.2f}".rjust(widths[4]),
            f"{r['平均收益%']:.2f}".rjust(widths[5]),
            f"{r['中位数%']:.2f}".rjust(widths[6]),
            f"{r['最大收益%']:.2f}".rjust(widths[7]),
            f"{r['最大亏损%']:.2f}".rjust(widths[8]),
            f"{r['平均盈利%']:.2f}".rjust(widths[9]),
            f"{r['平均亏损%']:.2f}".rjust(widths[10]),
        ]
        print(" | ".join(parts))

    print()
    top = rows[0]
    print(f"胜率最高: {top['策略']} = {top['胜率%']}% (信号{top['信号数']}次)")
    for r in rows[1:3]:
        print(f"其次: {r['策略']} = {r['胜率%']}%")


if __name__ == "__main__":
    data = test_all_strategies()
    print_results(data)
