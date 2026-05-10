"""
批量测试不同持有天数的回测胜率（1-10天），一次性加载数据高效完成。
"""

import os
import sys
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from strategy import HIST_CACHE_DIR
from backtest.backtest import (
    load_hist_cache,
    backtest_one_stock,
    summarize_backtest,
    summarize_by_strategy,
    load_stock_names_from_base_pool,
    print_backtest_summary_table,
)


def run_all_hold_days(hold_days_list, max_stocks=0):
    """一次性加载所有股票数据，对每个持有天数分别回测。"""

    files = [f for f in os.listdir(HIST_CACHE_DIR) if f.endswith("_bs.csv")]
    if max_stocks and max_stocks > 0:
        files = files[:max_stocks]
    total = len(files)

    stock_name_map = load_stock_names_from_base_pool()

    # 预加载所有股票的原始数据
    print(f"正在预加载 {total} 只股票的K线数据...")
    all_stock_data = {}
    for idx, fname in enumerate(files, 1):
        code = fname.replace("_bs.csv", "")
        raw_df = load_hist_cache(code)
        if not raw_df.empty and len(raw_df) >= 80:
            all_stock_data[code] = {
                "raw_df": raw_df,
                "name": stock_name_map.get(code, ""),
            }
        if idx % 200 == 0:
            print(f"  加载进度: {idx}/{total}")

    print(f"有效股票数量: {len(all_stock_data)}")

    all_summaries = []

    for hold_days in hold_days_list:
        print(f"\n{'='*60}")
        print(f"正在回测 持有天数 = {hold_days} ...")
        start = time.time()

        all_results = []
        for code, info in all_stock_data.items():
            from strategy import prepare_hist_data, check_secondary_filters
            from backtest import get_signal_from_row

            raw_df = info["raw_df"]
            name = info["name"]

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

                signal_type, breakthrough, main_promotion, hit_count = get_signal_from_row(row)
                if hit_count == 0:
                    continue

                buy_row = df.iloc[i + 1]
                sell_row = df.iloc[i + hold_days]

                buy_price = buy_row["开盘"]
                sell_price = sell_row["收盘"]

                if pd.isna(buy_price) or pd.isna(sell_price) or buy_price <= 0:
                    continue

                return_pct = (sell_price / buy_price - 1) * 100

                all_results.append({
                    "代码": code,
                    "名称": name,
                    "信号日期": row["日期"],
                    "买入日期": buy_row["日期"],
                    "卖出日期": sell_row["日期"],
                    "买入价": buy_price,
                    "卖出价": sell_price,
                    "持有天数": hold_days,
                    "收益率%": return_pct,
                    "是否盈利": return_pct > 0,
                    "信号类型": signal_type,
                    "突破反转策略": breakthrough,
                    "主升策略": main_promotion,
                    "命中策略数": hit_count,
                    "信号日收盘价": row["收盘"],
                    "信号日涨跌幅": row["涨跌幅"],
                    "信号日量比": row["成交量"] / row["过去20日平均成交量"],
                    "信号日20日日均成交额": row["过去20日日均成交额"],
                    "信号日15日涨停": int(row["近15日涨停次数"]),
                })

        elapsed = time.time() - start
        print(f"  信号数: {len(all_results)} | 耗时: {elapsed:.1f} 秒")

        import pandas as pd
        result_df = pd.DataFrame(all_results)
        summary = summarize_backtest(result_df, hold_days)
        all_summaries.append(summary)

    print(f"\n{'='*60}")
    print("全部回测完成！汇总对比：\n")

    import pandas as pd
    combined = pd.concat(all_summaries, ignore_index=True)
    combined = combined.sort_values("持有天数").reset_index(drop=True)

    print_backtest_summary_table(combined)

    # 找出胜率最高的持有天数
    best = combined.loc[combined["胜率%"].idxmax()]
    print(f"\n胜率最高的持有天数: {int(best['持有天数'])} 天 ({best['胜率%']:.2f}%)")

    return combined


if __name__ == "__main__":
    hold_days_list = list(range(1, 11))
    run_all_hold_days(hold_days_list)
