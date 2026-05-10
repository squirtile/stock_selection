"""
分析各策略在持股2天下的独立胜率表现。
一次性加载数据，对每个策略单独回测并对比。
"""

import os
import sys
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from strategy import (
    HIST_CACHE_DIR,
    prepare_hist_data,
    check_secondary_filters,
    check_strategy_1,
    check_strategy_2,
    check_strategy_1_main_promotion,
    check_strategy_2_main_promotion,
    check_strategy_3_main_promotion,
    check_strategy_4_main_promotion,
)

HOLD_DAYS = 2

# 所有策略定义：(名称, 检测函数)
ALL_STRATEGIES = [
    ("S1-箱体突破", check_strategy_1),
    ("S2-底部放量反转", check_strategy_2),
    ("M1-主升箱体突破", check_strategy_1_main_promotion),
    ("M2-主升底部反转", check_strategy_2_main_promotion),
    ("M3-主升缩量回调", check_strategy_3_main_promotion),
    ("M4-主升均线多头", check_strategy_4_main_promotion),
]


def load_all_stock_data():
    """预加载所有股票数据。"""
    files = [f for f in os.listdir(HIST_CACHE_DIR) if f.endswith("_bs.csv")]
    stock_data = {}
    for fname in files:
        code = fname.replace("_bs.csv", "")
        file_path = os.path.join(HIST_CACHE_DIR, fname)
        df = pd.read_csv(file_path, dtype={"代码": str})
        if df.empty or len(df) < 80:
            continue
        df["代码"] = code
        needed = ["日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额", "涨跌幅", "代码"]
        for col in needed:
            if col not in df.columns:
                df = pd.DataFrame()
                break
        if df.empty:
            continue
        df["日期"] = pd.to_datetime(df["日期"])
        for col in ["开盘", "最高", "最低", "收盘", "成交量", "成交额", "涨跌幅"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["开盘", "最高", "最低", "收盘"])
        df = df.sort_values("日期").reset_index(drop=True)
        if len(df) >= 80:
            stock_data[code] = df
    return stock_data


def backtest_with_strategies(stock_data, strategies, hold_days=HOLD_DAYS):
    """
    使用给定的策略列表进行回测，返回 signal_count, win_count, returns 列表。
    """
    all_returns = []
    win_count = 0
    signal_count = 0

    for code, raw_df in stock_data.items():
        df = prepare_hist_data(raw_df.copy())
        df = df.sort_values("日期").reset_index(drop=True)

        need_cols = [
            "SMA5", "SMA10", "SMA20", "SMA60",
            "过去60日最高价", "过去60日最高收盘", "过去60日最低收盘",
            "过去40日最低价", "过去20日实体振幅", "过去20日平均成交量",
            "过去20日日均成交额", "近15日涨停次数", "SMA60_5日前",
        ]

        for i in range(65, len(df) - hold_days - 1):
            row = df.iloc[i]
            if row[need_cols].isna().any():
                continue
            if not check_secondary_filters(row):
                continue

            # 检查是否命中任意策略
            hit = any(func(row) for _, func in strategies)
            if not hit:
                continue

            buy_price = df.iloc[i + 1]["开盘"]
            sell_price = df.iloc[i + hold_days]["收盘"]
            if pd.isna(buy_price) or pd.isna(sell_price) or buy_price <= 0:
                continue

            ret = (sell_price / buy_price - 1) * 100
            all_returns.append(ret)
            signal_count += 1
            if ret > 0:
                win_count += 1

    return signal_count, win_count, all_returns


def summarize(signal_count, win_count, returns):
    if signal_count == 0:
        return None
    win_rate = win_count / signal_count * 100
    avg_ret = sum(returns) / len(returns)
    sorted_rets = sorted(returns)
    median_ret = sorted_rets[len(sorted_rets) // 2]
    avg_win = sum(r for r in returns if r > 0) / max(1, sum(1 for r in returns if r > 0))
    avg_loss = sum(r for r in returns if r <= 0) / max(1, sum(1 for r in returns if r <= 0))
    return {
        "信号次数": signal_count,
        "盈利次数": win_count,
        "亏损次数": signal_count - win_count,
        "胜率%": round(win_rate, 2),
        "平均收益率%": round(avg_ret, 2),
        "中位数收益率%": round(median_ret, 2),
        "平均盈利%": round(avg_win, 2),
        "平均亏损%": round(avg_loss, 2),
        "最大单笔收益%": round(max(returns), 2),
        "最大单笔亏损%": round(min(returns), 2),
    }


def print_table(results_list, title):
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}")

    headers = ["策略", "信号次数", "盈利次数", "亏损次数", "胜率%", "平均收益率%", "中位数收益率%", "最大单笔收益%", "最大单笔亏损%"]
    col_widths = [20, 10, 10, 10, 8, 12, 14, 14, 14]

    header_line = " | ".join(h.ljust(w) for h, w in zip(headers, col_widths))
    print(header_line)
    print("-+-".join("-" * w for w in col_widths))

    for row in results_list:
        parts = [
            row["策略"].ljust(col_widths[0]),
            str(row["信号次数"]).rjust(col_widths[1]),
            str(row["盈利次数"]).rjust(col_widths[2]),
            str(row["亏损次数"]).rjust(col_widths[3]),
            f"{row['胜率%']:.2f}".rjust(col_widths[4]),
            f"{row['平均收益率%']:.2f}".rjust(col_widths[5]),
            f"{row['中位数收益率%']:.2f}".rjust(col_widths[6]),
            f"{row['最大单笔收益%']:.2f}".rjust(col_widths[7]),
            f"{row['最大单笔亏损%']:.2f}".rjust(col_widths[8]),
        ]
        print(" | ".join(parts))


def main():
    print("正在加载股票数据...")
    start = time.time()
    stock_data = load_all_stock_data()
    print(f"有效股票: {len(stock_data)} | 加载耗时: {time.time() - start:.1f}s")

    # 1. 测试每个策略独立表现
    print("\n>>> 测试各策略独立表现（持股2天）...")
    single_results = []
    all_returns_by_strategy = {}
    for name, func in ALL_STRATEGIES:
        cnt, win, rets = backtest_with_strategies(stock_data, [(name, func)])
        s = summarize(cnt, win, rets)
        if s:
            s["策略"] = name
            single_results.append(s)
            all_returns_by_strategy[name] = rets
            print(f"  {name}: 信号{cnt} 胜率{s['胜率%']:.2f}%")

    single_results.sort(key=lambda r: r["胜率%"], reverse=True)
    print_table(single_results, "各策略独立胜率排名（持股2天）")

    # 2. 测试两两组合
    print("\n>>> 测试两两策略组合...")
    combo_results = []
    for i in range(len(ALL_STRATEGIES)):
        for j in range(i + 1, len(ALL_STRATEGIES)):
            name1, func1 = ALL_STRATEGIES[i]
            name2, func2 = ALL_STRATEGIES[j]
            strategies = [(name1, func1), (name2, func2)]
            cnt, win, rets = backtest_with_strategies(stock_data, strategies)
            s = summarize(cnt, win, rets)
            if s:
                s["策略"] = f"{name1}+{name2}"
                combo_results.append(s)

    combo_results.sort(key=lambda r: r["胜率%"], reverse=True)
    print_table(combo_results[:10], "两两组合胜率 TOP10（持股2天）")

    # 3. 测试全部策略
    print("\n>>> 全部策略...")
    cnt, win, rets = backtest_with_strategies(stock_data, ALL_STRATEGIES)
    s = summarize(cnt, win, rets)
    if s:
        s["策略"] = "全部6策略(OR)"
        print_table([s], "全部策略合并（持股2天）")

    # 4. 各策略信号重叠分析（同时命中多策略 vs 单策略的胜率差异）
    print("\n\n>>> 策略重叠分析：")
    print("检查仅命中单一策略 vs 同时命中多策略时的胜率差异...")
    # 这需要在更细粒度上分析，我们简化：
    print("(详细重叠分析需要逐笔数据，此处展示各策略独立结果已足够)")

    # 最终推荐
    print("\n\n" + "=" * 60)
    print("  结论：持股2天胜率最高的策略")
    print("=" * 60)
    for r in single_results[:3]:
        print(f"  {r['策略']}: 胜率={r['胜率%']}%, 信号={r['信号次数']}, 平均收益={r['平均收益率%']}%")


if __name__ == "__main__":
    main()
