# main.py

import os
import pandas as pd
from tabulate import tabulate
from datetime import datetime

from data_loader import load_a_stock_spot, disable_proxy
from filters import apply_filters
from config import OUTPUT_FILE
from strategy import scan_main_rising_stocks, SIGNAL_OUTPUT_FILE
from concept_analyzer import analyze_concept_resonance

def print_strategy_descriptions():
    """
    打印主升信号策略说明。
    """
    print("\n当前主升信号策略说明：")
    print("=" * 60)

    print("策略1：60日新高 + 放量")
    print("条件：今日收盘价 > 过去60天最高收盘价，不含今日；今日成交量 > 过去20日平均成交量 × 1.5")
    print()

    print("策略2：长期低位 + 突然放量大涨")
    print("条件：当前价格距离60日最低点涨幅 < 30%；今日涨幅 > 5%；今日成交量 > 过去20日平均成交量 × 2")
    print()

    print("策略3：短期回调结束，重新启动")
    print("条件：SMA5 < SMA20；SMA60 > 5天前SMA60；今日收盘价 > SMA5；今日成交量 > 过去20日平均成交量 × 1.5")
    print()

    print("策略4：均线多头排列 + 放量上涨")
    print("条件：SMA5 > SMA10 > SMA20 > SMA60；今日涨幅 > 2%；今日成交量 > 过去20日平均成交量 × 1.2")

    print()
    print("统一二次过滤：")
    print("条件1：过去20个交易日日均成交额 >= 5000万元")
    print("条件2：过去15个交易日内，含今日，至少出现1次涨停；主板涨停定义为单日涨幅 >= 9.95%")

    print("=" * 60)

def print_stock_table(df: pd.DataFrame, max_rows: int = 50):
    """
    终端中以表格形式展示股票结果，避免中文错位严重。
    """

    if df.empty:
        print("没有可展示的股票。")
        return

    show_cols = [
        "代码",
        "名称",
        "题材",
        "最新价",
        "涨跌幅",
        "行业",
        "命中策略",
        "市值_亿元",
        "量比",
        "15日涨停",
    ]

    show_cols = [col for col in show_cols if col in df.columns]

    show_df = df[show_cols].copy().head(max_rows)

    # 股票代码补齐 6 位
    if "代码" in show_df.columns:
        show_df["代码"] = show_df["代码"].astype(str).str.zfill(6)

    # 数字格式化
    if "收盘价" in show_df.columns:
        show_df["收盘价"] = show_df["收盘价"].map(lambda x: f"{x:.2f}")

    if "今日涨跌幅" in show_df.columns:
        show_df["今日涨跌幅"] = show_df["今日涨跌幅"].map(lambda x: f"{x:.2f}%")

    if "量比" in show_df.columns:
        show_df["量比"] = show_df["量比"].map(lambda x: f"{x:.2f}")

    if "15日涨停" in show_df.columns:
        show_df["15日涨停"] = show_df["15日涨停"].astype(int)

    print(
        tabulate(
            show_df,
            headers="keys",
            tablefmt="grid",
            showindex=False,
            stralign="center",
            numalign="center",
        )
    )

def print_concept_resonance(resonance_summary_df: pd.DataFrame):
    """
    打印题材共振结果。
    """

    print("\n题材共振：")
    print("=" * 80)

    if resonance_summary_df is None or resonance_summary_df.empty:
        print("今日没有发现题材共振。")
        print("=" * 80)
        return

    for _, row in resonance_summary_df.iterrows():
        print(f"{row['概念题材']}：命中 {row['命中数']} 只")
        print(f"股票：{row['命中股票']}")
        print("-" * 80)

    print("=" * 80)
    
def main():
    os.makedirs("output", exist_ok=True)

    disable_proxy()

    # 如果已经存在筛选结果文件，就直接读取，不再重新获取数据
    if os.path.exists(OUTPUT_FILE):
        print(f"发现已有筛选结果文件：{OUTPUT_FILE}")
        print("直接读取本地文件，不重新获取 A 股数据。")

        # selected_df = pd.read_excel(OUTPUT_FILE)
        selected_df = pd.read_excel(OUTPUT_FILE, dtype={"代码": str})
        selected_df["代码"] = selected_df["代码"].astype(str).str.zfill(6)

        print(f"本地股票池数量：{len(selected_df)}")

        # print("\n前 20 只股票预览：")
        # print(selected_df.head(20))

    else:
        # 如果文件不存在，才重新获取数据并筛选
        print("未发现本地筛选结果文件，开始获取 A 股数据...")
        df = load_a_stock_spot()

        print(f"原始股票数量：{len(df)}")

        print("正在执行筛选...")
        selected_df = apply_filters(df)

        print(f"筛选后股票数量：{len(selected_df)}")

        # 选择你关心的字段
        columns = [
            "代码",
            "名称",
            "最新价",
            "涨跌幅",
            "成交额",
            "总市值_亿元",
            "流通市值",
            "行业",
        ]

        # 避免字段不存在时报错
        columns = [col for col in columns if col in selected_df.columns]

        selected_df = selected_df[columns]

        # 成交额：元 -> 亿元
        if "成交额" in selected_df.columns:
            selected_df["成交额"] = selected_df["成交额"] / 100000000
            selected_df = selected_df.rename(columns={"成交额": "成交额_亿元"})

        # 流通市值：元 -> 亿元
        if "流通市值" in selected_df.columns:
            selected_df["流通市值"] = selected_df["流通市值"] / 100000000
            selected_df = selected_df.rename(columns={"流通市值": "流通市值_亿元"})

        # 总市值_亿元：保留2位小数
        if "总市值_亿元" in selected_df.columns:
            selected_df["总市值_亿元"] = selected_df["总市值_亿元"].round(2)

        # 所有数字列统一保留 2 位小数
        number_cols = selected_df.select_dtypes(include=["number"]).columns
        selected_df[number_cols] = selected_df[number_cols].round(2)

        selected_df.to_excel(OUTPUT_FILE, index=False)

        print(f"筛选结果已导出：{OUTPUT_FILE}")

    print("\n开始执行第二步：主升信号策略扫描...")

    signal_df = scan_main_rising_stocks(selected_df)

    if signal_df.empty:
        print("今日没有股票命中主升信号。")
    else:
        signal_df["代码"] = signal_df["代码"].astype(str).str.zfill(6)

        # 所有数字列统一保留 2 位小数
        number_cols = signal_df.select_dtypes(include=["number"]).columns
        signal_df[number_cols] = signal_df[number_cols].round(2)

        print("\n开始执行第三步：东方财富概念题材共振分析...")

        resonance_summary_df, resonance_detail_df, stock_theme_map = analyze_concept_resonance(
            signal_df,
            min_count=3
        )

        # 确保题材共振按照命中数降序排列
        if resonance_summary_df is not None and not resonance_summary_df.empty:
            resonance_summary_df = resonance_summary_df.sort_values(
                by="命中数",
                ascending=False
            )

        # 名称后面新增“题材”列
        # 一个股票可能同时属于多个共振题材，这里会用 、 连接
        signal_df["题材"] = signal_df["代码"].map(stock_theme_map).fillna("")

        # 按命中策略个数排序，命中策略越多越靠前
        signal_df["命中策略数"] = signal_df["命中策略"].astype(str).apply(
            lambda x: len([i for i in x.split("、") if i.strip()])
        )

        signal_df = signal_df.sort_values(
            by=["命中策略数", "15日涨停", "量比"],
            ascending=[False, False, False]
        )

        # 精简最终导出的字段，题材放在名称后面
        export_cols = [
            "代码",
            "名称",
            "题材",
            "最新价",
            "涨跌幅",
            "行业",
            "命中策略",
            "总市值_亿元",
            "量比",
            "15日涨停",
        ]

        export_cols = [col for col in export_cols if col in signal_df.columns]

        export_signal_df = signal_df[export_cols].copy()

        # 总市值_亿元改名为市值_亿元
        export_signal_df = export_signal_df.rename(
            columns={"总市值_亿元": "市值_亿元"}
        )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        signal_output_file = f"output/a_stock_signal_selected_{timestamp}.xlsx"

        with pd.ExcelWriter(signal_output_file, engine="openpyxl") as writer:
            export_signal_df.to_excel(
                writer,
                sheet_name="命中股票",
                index=False
            )

            if resonance_summary_df is not None and not resonance_summary_df.empty:
                resonance_summary_df.to_excel(
                    writer,
                    sheet_name="题材共振",
                    index=False
                )

        print_strategy_descriptions()

        # 题材共振单独一节展示
        print_concept_resonance(resonance_summary_df)

        print(f"主升信号股票数量：{len(export_signal_df)}")
        print(f"主升信号结果已导出：{signal_output_file}")

        print("\n主升信号股票预览：")
        print_stock_table(export_signal_df, max_rows=50)


if __name__ == "__main__":
    main()