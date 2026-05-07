# main.py

import os
from datetime import datetime

import pandas as pd
from wcwidth import wcswidth
from tabulate import tabulate

from data_loader import load_a_stock_spot, disable_proxy
from filters import apply_filters
from config import OUTPUT_FILE
from strategy import scan_main_rising_stocks
from concept_analyzer import analyze_concept_resonance

# pip install -r requirements.txt

# =========================
# 运行开关
# =========================

# 是否执行第二步：主升信号扫描
RUN_SIGNAL_SCAN = True

# 是否执行第三步：题材共振分析
RUN_CONCEPT_ANALYSIS = False


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


# def print_stock_table(df: pd.DataFrame, max_rows: int = 50):
#     """
#     终端中以表格形式展示股票结果。
#     """

#     if df is None or df.empty:
#         print("没有可展示的股票。")
#         return

#     show_cols = [
#         "代码",
#         "名称",
#         "题材",
#         "最新价",
#         "涨跌幅",
#         "行业",
#         "命中策略",
#         "市值_亿元",
#         "量比",
#         "15日涨停",
#     ]

#     show_cols = [col for col in show_cols if col in df.columns]

#     show_df = df[show_cols].copy().head(max_rows)

#     if "代码" in show_df.columns:
#         show_df["代码"] = show_df["代码"].astype(str).str.zfill(6)

#     # 统一转字符串，减少中文表格错位
#     for col in show_df.columns:
#         show_df[col] = show_df[col].astype(str)

#     print(
#         tabulate(
#             show_df,
#             headers="keys",
#             tablefmt="grid",
#             showindex=False,
#             stralign="center",
#             numalign="center",
#             disable_numparse=True,
#         )
#     )

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
    elif align == "center":
        left = padding // 2
        right = padding - left
        return " " * left + text + " " * right
    else:
        return text + " " * padding


def print_stock_table(df: pd.DataFrame, max_rows: int = 50):
    """
    终端中以纯文本方式展示股票结果。
    重点解决中文列名、中文股票名、行业名导致的错位问题。
    """

    if df is None or df.empty:
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

    if "代码" in show_df.columns:
        show_df["代码"] = show_df["代码"].astype(str).str.zfill(6)

    # 数字格式化
    for col in ["最新价", "涨跌幅", "市值_亿元", "量比"]:
        if col in show_df.columns:
            show_df[col] = pd.to_numeric(show_df[col], errors="coerce").map(
                lambda x: "" if pd.isna(x) else f"{x:.2f}"
            )

    if "15日涨停" in show_df.columns:
        show_df["15日涨停"] = pd.to_numeric(show_df["15日涨停"], errors="coerce").map(
            lambda x: "" if pd.isna(x) else str(int(x))
        )

    # 每列最小宽度
    min_widths = {
        "代码": 8,
        "名称": 10,
        "题材": 20,
        "最新价": 8,
        "涨跌幅": 8,
        "行业": 12,
        "命中策略": 24,
        "市值_亿元": 10,
        "量比": 8,
        "15日涨停": 10,
    }

    # 计算每列宽度
    col_widths = {}

    for col in show_cols:
        max_width = wcswidth(col)

        for value in show_df[col].astype(str).tolist():
            max_width = max(max_width, wcswidth(value))

        col_widths[col] = max(max_width, min_widths.get(col, 8))

    # 数字列右对齐，文字列左对齐
    right_align_cols = {"最新价", "涨跌幅", "市值_亿元", "量比", "15日涨停"}

    # 打印表头
    header_parts = []

    for col in show_cols:
        align = "right" if col in right_align_cols else "left"
        header_parts.append(align_text(col, col_widths[col], align))

    print(" | ".join(header_parts))

    # 打印分隔线
    sep_parts = []

    for col in show_cols:
        sep_parts.append("-" * col_widths[col])

    print("-+-".join(sep_parts))

    # 打印内容
    for _, row in show_df.iterrows():
        row_parts = []

        for col in show_cols:
            align = "right" if col in right_align_cols else "left"
            row_parts.append(align_text(row[col], col_widths[col], align))

        print(" | ".join(row_parts))


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


def format_base_pool_df(selected_df: pd.DataFrame) -> pd.DataFrame:
    """
    整理基础股票池字段和单位。
    """

    selected_df = selected_df.copy()

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

    columns = [col for col in columns if col in selected_df.columns]

    selected_df = selected_df[columns]

    if "代码" in selected_df.columns:
        selected_df["代码"] = selected_df["代码"].astype(str).str.zfill(6)

    # 成交额：元 -> 亿元
    if "成交额" in selected_df.columns:
        selected_df["成交额"] = pd.to_numeric(selected_df["成交额"], errors="coerce") / 100000000
        selected_df = selected_df.rename(columns={"成交额": "成交额_亿元"})

    # 流通市值：元 -> 亿元
    if "流通市值" in selected_df.columns:
        selected_df["流通市值"] = pd.to_numeric(selected_df["流通市值"], errors="coerce") / 100000000
        selected_df = selected_df.rename(columns={"流通市值": "流通市值_亿元"})

    # 所有数字列保留 2 位小数
    number_cols = selected_df.select_dtypes(include=["number"]).columns
    selected_df[number_cols] = selected_df[number_cols].round(2)

    return selected_df


def load_or_create_base_pool() -> pd.DataFrame:
    """
    加载或生成基础股票池。
    """

    os.makedirs("output", exist_ok=True)

    if os.path.exists(OUTPUT_FILE):
        print(f"发现已有筛选结果文件：{OUTPUT_FILE}")
        print("直接读取本地文件，不重新获取 A 股数据。")

        selected_df = pd.read_excel(OUTPUT_FILE, dtype={"代码": str})
        selected_df["代码"] = selected_df["代码"].astype(str).str.zfill(6)

        print(f"本地股票池数量：{len(selected_df)}")

        return selected_df

    print("未发现本地筛选结果文件，开始获取 A 股数据...")

    df = load_a_stock_spot()

    print(f"原始股票数量：{len(df)}")

    print("正在执行基础筛选...")
    selected_df = apply_filters(df)

    print(f"基础筛选后股票数量：{len(selected_df)}")

    selected_df = format_base_pool_df(selected_df)

    selected_df.to_excel(OUTPUT_FILE, index=False)

    print(f"筛选结果已导出：{OUTPUT_FILE}")

    backup_file = f"output/a_stock_selected_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    selected_df.to_excel(backup_file, index=False)

    print(f"基础股票池备份已导出：{backup_file}")

    return selected_df


# def prepare_signal_export_df(signal_df: pd.DataFrame, stock_theme_map: dict) -> pd.DataFrame:
#     """
#     整理最终导出的主升信号股票。
#     """

#     signal_df = signal_df.copy()

#     signal_df["代码"] = signal_df["代码"].astype(str).str.zfill(6)

#     # 用策略计算时的K线数据覆盖展示字段，避免使用基础股票池里的旧行情
#     if "收盘价" in signal_df.columns:
#         signal_df["最新价"] = signal_df["收盘价"]

#     if "今日涨跌幅" in signal_df.columns:
#         signal_df["涨跌幅"] = signal_df["今日涨跌幅"]

#     # 题材列：只显示共振题材
#     signal_df["题材"] = signal_df["代码"].map(stock_theme_map).fillna("")

#     # 命中策略数量，用于排序
#     signal_df["命中策略数"] = signal_df["命中策略"].astype(str).apply(
#         lambda x: len([i for i in x.split("、") if i.strip()])
#     )

#     # 所有数字列统一保留 2 位小数
#     number_cols = signal_df.select_dtypes(include=["number"]).columns
#     signal_df[number_cols] = signal_df[number_cols].round(2)

#     # 按命中策略数量、15日涨停、量比排序
#     sort_cols = []
#     ascending = []

#     if "命中策略数" in signal_df.columns:
#         sort_cols.append("命中策略数")
#         ascending.append(False)

#     if "15日涨停" in signal_df.columns:
#         sort_cols.append("15日涨停")
#         ascending.append(False)

#     if "量比" in signal_df.columns:
#         sort_cols.append("量比")
#         ascending.append(False)

#     if sort_cols:
#         signal_df = signal_df.sort_values(by=sort_cols, ascending=ascending)

#     export_cols = [
#         "代码",
#         "名称",
#         "题材",
#         "K线日期",
#         "最新价",
#         "涨跌幅",
#         "行业",
#         "命中策略",
#         "总市值_亿元",
#         "量比",
#         "15日涨停",
#     ]

#     export_cols = [col for col in export_cols if col in signal_df.columns]

#     export_signal_df = signal_df[export_cols].copy()

#     export_signal_df = export_signal_df.rename(
#         columns={"总市值_亿元": "市值_亿元"}
#     )

#     return export_signal_df

def prepare_signal_export_df(signal_df: pd.DataFrame, stock_theme_map: dict) -> pd.DataFrame:
    """
    整理最终导出的主升信号股票。
    """

    signal_df = signal_df.copy()

    signal_df["代码"] = signal_df["代码"].astype(str).str.zfill(6)

    # 用策略计算时的 K 线数据覆盖展示字段
    # 避免使用基础股票池里的旧行情
    if "收盘价" in signal_df.columns:
        signal_df["最新价"] = signal_df["收盘价"]

    if "今日涨跌幅" in signal_df.columns:
        signal_df["涨跌幅"] = signal_df["今日涨跌幅"]

    # 题材列：只显示共振题材
    signal_df["题材"] = signal_df["代码"].map(stock_theme_map).fillna("")

    # 命中策略数量，用于排序
    signal_df["命中策略数"] = signal_df["命中策略"].astype(str).apply(
        lambda x: len([i for i in x.split("、") if i.strip()])
    )

    # 所有数字列统一保留 2 位小数
    number_cols = signal_df.select_dtypes(include=["number"]).columns
    signal_df[number_cols] = signal_df[number_cols].round(2)

    # 排序：
    # 第一优先级：命中策略数，从大到小
    # 第二优先级：量比，从大到小
    sort_cols = []
    ascending = []

    if "命中策略数" in signal_df.columns:
        sort_cols.append("命中策略数")
        ascending.append(False)

    if "量比" in signal_df.columns:
        sort_cols.append("量比")
        ascending.append(False)

    if sort_cols:
        signal_df = signal_df.sort_values(by=sort_cols, ascending=ascending)

    export_cols = [
        "代码",
        "名称",
        "题材",
        "K线日期",
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

    export_signal_df = export_signal_df.rename(
        columns={"总市值_亿元": "市值_亿元"}
    )

    return export_signal_df

def main():
    disable_proxy()

    selected_df = load_or_create_base_pool()

    if not RUN_SIGNAL_SCAN:
        print("已关闭第二步主升信号扫描。")
        return

    print("\n开始执行第二步：主升信号策略扫描...")

    signal_df = scan_main_rising_stocks(selected_df)

    if signal_df is None or signal_df.empty:
        print("今日没有股票命中主升信号。")
        return

    signal_df["代码"] = signal_df["代码"].astype(str).str.zfill(6)

    if RUN_CONCEPT_ANALYSIS:
        print("\n开始执行第三步：东方财富概念题材共振分析...")

        resonance_summary_df, resonance_detail_df, stock_theme_map = analyze_concept_resonance(
            signal_df,
            min_count=3
        )

        if resonance_summary_df is not None and not resonance_summary_df.empty:
            resonance_summary_df = resonance_summary_df.sort_values(
                by="命中数",
                ascending=False
            )
    else:
        print("已关闭第三步题材共振分析。")
        resonance_summary_df = pd.DataFrame()
        resonance_detail_df = pd.DataFrame()
        stock_theme_map = {}

    export_signal_df = prepare_signal_export_df(signal_df, stock_theme_map)

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

        if resonance_detail_df is not None and not resonance_detail_df.empty:
            resonance_detail_df.to_excel(
                writer,
                sheet_name="共振明细",
                index=False
            )

    print_strategy_descriptions()

    print_concept_resonance(resonance_summary_df)

    print(f"主升信号股票数量：{len(export_signal_df)}")
    print(f"主升信号结果已导出：{signal_output_file}")

    print("\n主升信号股票预览：")
    print_stock_table(export_signal_df, max_rows=50)


if __name__ == "__main__":
    main()