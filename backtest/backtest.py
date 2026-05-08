# backtest.py
# 基于本地 BaoStock 历史K线缓存，对现有策略做简单日线回测

import os
import sys
import time
import argparse
from wcwidth import wcswidth
from datetime import datetime

import pandas as pd

# 让 backtest.py 可以导入项目根目录下的 strategy.py
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from strategy import (
    HIST_CACHE_DIR,
    prepare_hist_data,
    check_strategy_1,
    check_strategy_2,
    check_strategy_1_main_promotion,
    check_strategy_2_main_promotion,
    check_strategy_3_main_promotion,
    check_strategy_4_main_promotion,
    check_secondary_filters,
)


OUTPUT_DIR = "output/backtest"

def align_text(text, width, align="left"):
    """
    按中文显示宽度对齐字符串。
    中文字符通常占2个宽度，英文数字占1个宽度。
    """
    text = "" if pd.isna(text) else str(text)
    text_width = wcswidth(text)

    padding = width - text_width

    if padding <= 0:
        return text

    if align == "right":
        return " " * padding + text

    if align == "center":
        left = padding // 2
        right = padding - left
        return " " * left + text + " " * right

    return text + " " * padding


def print_backtest_summary_table(summary_df: pd.DataFrame):
    """
    以整齐表格形式打印回测总体统计。
    """

    if summary_df is None or summary_df.empty:
        print("没有可展示的回测统计结果。")
        return

    show_cols = [
        "持有天数",
        "信号次数",
        "盈利次数",
        "亏损次数",
        "胜率%",
        "平均收益率%",
        "中位数收益率%",
        "最大单笔收益%",
        "最大单笔亏损%",
        "平均盈利%",
        "平均亏损%",
        "盈亏比",
    ]

    show_cols = [col for col in show_cols if col in summary_df.columns]
    show_df = summary_df[show_cols].copy()

    number_cols = show_df.columns

    for col in number_cols:
        if col in ["持有天数", "信号次数", "盈利次数", "亏损次数"]:
            show_df[col] = pd.to_numeric(show_df[col], errors="coerce").map(
                lambda x: "" if pd.isna(x) else str(int(x))
            )
        else:
            show_df[col] = pd.to_numeric(show_df[col], errors="coerce").map(
                lambda x: "" if pd.isna(x) else f"{x:.2f}"
            )

    min_widths = {
        "持有天数": 2,
        "信号次数": 10,
        "盈利次数": 10,
        "亏损次数": 10,
        "胜率%": 8,
        "平均收益率%": 12,
        "中位数收益率%": 14,
        "最大单笔收益%": 14,
        "最大单笔亏损%": 14,
        "平均盈利%": 10,
        "平均亏损%": 10,
        "盈亏比": 8,
    }

    col_widths = {}

    for col in show_cols:
        max_width = wcswidth(col)
        for value in show_df[col].astype(str).tolist():
            max_width = max(max_width, wcswidth(value))
        col_widths[col] = max(max_width, min_widths.get(col, 8))

    right_align_cols = set(show_cols)

    header_parts = []
    for col in show_cols:
        align = "right" if col in right_align_cols else "left"
        header_parts.append(align_text(col, col_widths[col], align))

    print(" | ".join(header_parts))

    sep_parts = ["-" * col_widths[col] for col in show_cols]
    print("-+-".join(sep_parts))

    for _, row in show_df.iterrows():
        row_parts = []
        for col in show_cols:
            align = "right" if col in right_align_cols else "left"
            row_parts.append(align_text(row[col], col_widths[col], align))
        print(" | ".join(row_parts))

def load_hist_cache(code: str) -> pd.DataFrame:
    """
    读取本地 BaoStock 历史K线缓存。
    """

    code = str(code).zfill(6)
    file_path = os.path.join(HIST_CACHE_DIR, f"{code}_bs.csv")

    if not os.path.exists(file_path):
        return pd.DataFrame()

    df = pd.read_csv(file_path, dtype={"代码": str})

    if df.empty:
        return pd.DataFrame()

    df["代码"] = code

    needed_cols = ["日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额", "涨跌幅", "代码"]

    for col in needed_cols:
        if col not in df.columns:
            return pd.DataFrame()

    df["日期"] = pd.to_datetime(df["日期"])

    numeric_cols = ["开盘", "最高", "最低", "收盘", "成交量", "成交额", "涨跌幅"]

    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["开盘", "最高", "最低", "收盘"])
    df = df.sort_values("日期").reset_index(drop=True)

    return df


def get_signal_from_row(row):
    """
    判断某一天是否命中策略。
    返回命中策略列表。
    """

    breakthrough_strategies = []
    main_promotion_strategies = []

    if check_strategy_1(row):
        breakthrough_strategies.append("箱体突破")

    if check_strategy_2(row):
        breakthrough_strategies.append("底部放量反转")

    if check_strategy_1_main_promotion(row):
        main_promotion_strategies.append("主升-箱体突破")

    if check_strategy_2_main_promotion(row):
        main_promotion_strategies.append("主升-底部放量反转")

    if check_strategy_3_main_promotion(row):
        main_promotion_strategies.append("主升-缩量回调启动")

    if check_strategy_4_main_promotion(row):
        main_promotion_strategies.append("主升-均线多头排列")

    hit_strategies = breakthrough_strategies + main_promotion_strategies

    if not hit_strategies:
        return "", "", "", 0

    signal_types = []

    if breakthrough_strategies:
        signal_types.append("突破反转")

    if main_promotion_strategies:
        signal_types.append("主升")

    return (
        "、".join(signal_types),
        "、".join(breakthrough_strategies),
        "、".join(main_promotion_strategies),
        len(hit_strategies),
    )


def backtest_one_stock(
    code: str,
    name: str = "",
    hold_days: int = 3,
    use_secondary_filter: bool = True,
) -> list:
    """
    回测单只股票。

    规则：
    1. 第 T 日出现信号
    2. 第 T+1 日开盘买入
    3. 持有 hold_days 天
    4. 第 T+hold_days 日收盘卖出
    """

    raw_df = load_hist_cache(code)

    if raw_df.empty or len(raw_df) < 80:
        return []

    df = prepare_hist_data(raw_df)

    df = df.sort_values("日期").reset_index(drop=True)

    results = []

    need_cols = [
        "SMA5",
        "SMA10",
        "SMA20",
        "SMA60",
        "过去60日最高价",
        "过去60日最高收盘",
        "过去60日最低收盘",
        "过去40日最低价",
        "过去20日实体振幅",
        "过去20日平均成交量",
        "过去20日日均成交额",
        "近15日涨停次数",
        "SMA60_5日前",
    ]

    # 从第65根K线后开始，避免指标不完整
    for i in range(65, len(df) - hold_days - 1):
        row = df.iloc[i]

        if row[need_cols].isna().any():
            continue

        if use_secondary_filter and not check_secondary_filters(row):
            continue

        signal_type, breakthrough, main_promotion, hit_count = get_signal_from_row(row)

        if hit_count == 0:
            continue

        signal_date = row["日期"]

        buy_row = df.iloc[i + 1]
        sell_row = df.iloc[i + hold_days]

        buy_date = buy_row["日期"]
        sell_date = sell_row["日期"]

        buy_price = buy_row["开盘"]
        sell_price = sell_row["收盘"]

        if pd.isna(buy_price) or pd.isna(sell_price) or buy_price <= 0:
            continue

        return_pct = (sell_price / buy_price - 1) * 100

        results.append(
            {
                "代码": code,
                "名称": name,
                "信号日期": signal_date,
                "买入日期": buy_date,
                "卖出日期": sell_date,
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
            }
        )

    return results


def summarize_backtest(result_df: pd.DataFrame, hold_days: int) -> pd.DataFrame:
    """
    汇总回测结果。
    """

    if result_df.empty:
        return pd.DataFrame()

    total = len(result_df)
    win_count = int(result_df["是否盈利"].sum())
    loss_count = total - win_count

    win_rate = win_count / total * 100

    avg_return = result_df["收益率%"].mean()
    median_return = result_df["收益率%"].median()
    max_return = result_df["收益率%"].max()
    min_return = result_df["收益率%"].min()

    avg_win = result_df.loc[result_df["收益率%"] > 0, "收益率%"].mean()
    avg_loss = result_df.loc[result_df["收益率%"] <= 0, "收益率%"].mean()

    if pd.isna(avg_loss) or avg_loss == 0:
        profit_loss_ratio = None
    else:
        profit_loss_ratio = abs(avg_win / avg_loss)

    summary = pd.DataFrame(
        [
            {
                "持有天数": hold_days,
                "信号次数": total,
                "盈利次数": win_count,
                "亏损次数": loss_count,
                "胜率%": win_rate,
                "平均收益率%": avg_return,
                "中位数收益率%": median_return,
                "最大单笔收益%": max_return,
                "最大单笔亏损%": min_return,
                "平均盈利%": avg_win,
                "平均亏损%": avg_loss,
                "盈亏比": profit_loss_ratio,
            }
        ]
    )

    number_cols = summary.select_dtypes(include=["number"]).columns
    summary[number_cols] = summary[number_cols].round(2)

    return summary


def summarize_by_strategy(result_df: pd.DataFrame) -> pd.DataFrame:
    """
    按策略类型汇总胜率。
    """

    if result_df.empty:
        return pd.DataFrame()

    rows = []

    strategy_cols = ["突破反转策略", "主升策略"]

    for col in strategy_cols:
        if col not in result_df.columns:
            continue

        temp = result_df.copy()
        temp[col] = temp[col].fillna("").astype(str)

        # 一个股票可能命中多个策略，用顿号拆开统计
        exploded = []

        for _, row in temp.iterrows():
            strategies = [x for x in row[col].split("、") if x.strip()]
            for strategy in strategies:
                new_row = row.copy()
                new_row["单策略"] = strategy
                exploded.append(new_row)

        if not exploded:
            continue

        exploded_df = pd.DataFrame(exploded)

        group_df = (
            exploded_df
            .groupby("单策略")
            .agg(
                信号次数=("代码", "count"),
                胜率=("是否盈利", "mean"),
                平均收益率=("收益率%", "mean"),
                中位数收益率=("收益率%", "median"),
                最大收益=("收益率%", "max"),
                最大亏损=("收益率%", "min"),
            )
            .reset_index()
        )

        group_df["胜率"] = group_df["胜率"] * 100
        rows.append(group_df)

    if not rows:
        return pd.DataFrame()

    result = pd.concat(rows, ignore_index=True)
    result = result.sort_values(by=["胜率", "平均收益率"], ascending=False)

    number_cols = result.select_dtypes(include=["number"]).columns
    result[number_cols] = result[number_cols].round(2)

    return result


def load_stock_names_from_base_pool(base_pool_file: str = "output/a_stock_selected.xlsx") -> dict:
    """
    读取股票名称，方便回测结果显示。
    """

    if not os.path.exists(base_pool_file):
        return {}

    try:
        df = pd.read_excel(base_pool_file, dtype={"代码": str})
        df["代码"] = df["代码"].astype(str).str.zfill(6)
        return dict(zip(df["代码"], df["名称"]))
    except Exception:
        return {}


def run_backtest(hold_days: int = 3, max_stocks: int = 0):
    """
    执行全市场基础池回测。
    """

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    stock_name_map = load_stock_names_from_base_pool()

    files = [
        f for f in os.listdir(HIST_CACHE_DIR)
        if f.endswith("_bs.csv")
    ]

    if max_stocks and max_stocks > 0:
        files = files[:max_stocks]

    print(f"发现历史K线缓存数量：{len(files)}")
    print(f"开始回测，持有天数：{hold_days}")

    all_results = []

    backtest_start_time = time.time()
    total_files = len(files)

    for idx, file_name in enumerate(files, start=1):
        code = file_name.replace("_bs.csv", "")
        name = stock_name_map.get(code, "")

        results = backtest_one_stock(
            code=code,
            name=name,
            hold_days=hold_days,
            use_secondary_filter=True,
        )

        all_results.extend(results)

        elapsed_seconds = time.time() - backtest_start_time
        avg_seconds = elapsed_seconds / idx
        remaining_seconds = avg_seconds * (total_files - idx)

        # 每 20 只刷新一次进度，最后一只也刷新
        if idx % 20 == 0 or idx == total_files:
            print(
                f"回测进度：{idx}/{total_files} | "
                f"当前股票：{code} {name} | "
                f"已发现信号：{len(all_results)} | "
                f"累计耗时：{elapsed_seconds:.1f} 秒 | "
                f"预计剩余：{remaining_seconds:.1f} 秒",
                end="\r",
                flush=True,
            )

    print()

    if not all_results:
        print("没有回测信号。")
        return

    result_df = pd.DataFrame(all_results)

    result_df["信号日期"] = pd.to_datetime(result_df["信号日期"]).dt.strftime("%Y-%m-%d")
    result_df["买入日期"] = pd.to_datetime(result_df["买入日期"]).dt.strftime("%Y-%m-%d")
    result_df["卖出日期"] = pd.to_datetime(result_df["卖出日期"]).dt.strftime("%Y-%m-%d")

    number_cols = result_df.select_dtypes(include=["number"]).columns
    result_df[number_cols] = result_df[number_cols].round(2)

    summary_df = summarize_backtest(result_df, hold_days)
    strategy_summary_df = summarize_by_strategy(result_df)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(
        OUTPUT_DIR,
        f"backtest_hold_{hold_days}d_{timestamp}.xlsx"
    )

    # 交易明细导出时删除不需要展示的列
    detail_export_df = result_df.copy()

    drop_detail_cols = [
        "信号类型",
        "突破反转策略",
        "命中策略数",
        "信号日20日日均成交额",
        "信号日15日涨停",
    ]

    detail_export_df = detail_export_df.drop(
        columns=[col for col in drop_detail_cols if col in detail_export_df.columns]
    )

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="总体统计", index=False)
        strategy_summary_df.to_excel(writer, sheet_name="按策略统计", index=False)
        detail_export_df.to_excel(writer, sheet_name="交易明细", index=False)

    print("\n回测完成。")
    print(f"信号次数：{len(result_df)}")

    if not summary_df.empty:
        print("\n回测总体统计：")
        print_backtest_summary_table(summary_df)

    print(f"回测结果已导出：{output_file}")


def main():
    parser = argparse.ArgumentParser(description="A股策略回测工具")

    parser.add_argument(
        "--hold-days",
        type=int,
        default=3,
        help="信号出现后持有多少个交易日，默认3天。",
    )

    parser.add_argument(
        "--max-stocks",
        type=int,
        default=0,
        help="测试用：只回测前N只股票。默认0表示全部。",
    )

    args = parser.parse_args()

    run_backtest(
        hold_days=args.hold_days,
        max_stocks=args.max_stocks,
    )


if __name__ == "__main__":
    main()