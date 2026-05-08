# minute_backtest.py
# 日线信号 + 5分钟/30分钟 B点确认回测
#
# 逻辑：
# 1. 先用本地日K缓存扫描日线策略信号
# 2. 对日线信号后的下一个交易日，读取该股票 5分钟/30分钟K线
# 3. 30分钟做结构过滤，5分钟做B点触发
# 4. B点确认后，下一根5分钟K线开盘买入
# 5. 默认按持有N个交易日卖出，符合A股非底仓不能T+0规则
#    也保留固定分钟/当日收盘模式用于研究对比
#
# 推荐运行：
#   python .\backtest\minute_backtest.py --hold-days 1 --minute-days 365
#   python .\backtest\minute_backtest.py --hold-days 3 --minute-days 365
#   python .\backtest\minute_backtest.py --hold-days 5 --minute-days 365
#
# 可选研究模式：
#   python .\backtest\minute_backtest.py --exit-mode fixed --hold-minutes 60 --minute-days 365
#   python .\backtest\minute_backtest.py --exit-mode close --minute-days 365

import os
import sys
import time
import math
import argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import numpy as np
from wcwidth import wcswidth

# 让脚本可以从 backtest 目录导入项目根目录模块
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

from minute_strategy import (
    get_minute_data_baostock,
    prepare_minute_data,
    evaluate_minute_buy_point,
    build_daily_group,
)

import baostock as bs


OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output", "minute_backtest")
BASE_POOL_FILE = os.path.join(PROJECT_ROOT, "output", "a_stock_selected.xlsx")


# =========================
# 终端表格显示
# =========================

def align_text(text, width, align="left"):
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


def print_table(df: pd.DataFrame, cols: list, min_widths: dict | None = None, right_cols: set | None = None, max_rows: int = 20):
    if df is None or df.empty:
        print("没有可展示的数据。")
        return

    min_widths = min_widths or {}
    right_cols = right_cols or set()

    show_cols = [col for col in cols if col in df.columns]
    show_df = df[show_cols].copy().head(max_rows)

    col_widths = {}
    for col in show_cols:
        max_width = wcswidth(col)
        for value in show_df[col].astype(str).tolist():
            max_width = max(max_width, wcswidth(value))
        col_widths[col] = max(max_width, min_widths.get(col, 8))

    header_parts = []
    for col in show_cols:
        align = "right" if col in right_cols else "left"
        header_parts.append(align_text(col, col_widths[col], align))
    print(" | ".join(header_parts))

    print("-+-".join(["-" * col_widths[col] for col in show_cols]))

    for _, row in show_df.iterrows():
        parts = []
        for col in show_cols:
            align = "right" if col in right_cols else "left"
            parts.append(align_text(row[col], col_widths[col], align))
        print(" | ".join(parts))


# =========================
# 日线信号扫描
# =========================

def load_hist_cache(code: str) -> pd.DataFrame:
    code = str(code).zfill(6)
    file_path = os.path.join(PROJECT_ROOT, HIST_CACHE_DIR, f"{code}_bs.csv")

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

    df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
    df = df.dropna(subset=["日期"])

    numeric_cols = ["开盘", "最高", "最低", "收盘", "成交量", "成交额", "涨跌幅"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["开盘", "最高", "最低", "收盘"])
    df = df.sort_values("日期").reset_index(drop=True)

    return df


def get_signal_from_row(row):
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


def load_stock_names_from_base_pool(base_pool_file: str = BASE_POOL_FILE) -> dict:
    if not os.path.exists(base_pool_file):
        return {}

    try:
        df = pd.read_excel(base_pool_file, dtype={"代码": str})
        df["代码"] = df["代码"].astype(str).str.zfill(6)
        if "名称" not in df.columns:
            return {}
        return dict(zip(df["代码"], df["名称"]))
    except Exception:
        return {}


def scan_daily_signals_for_stock(
    code: str,
    name: str = "",
    use_secondary_filter: bool = True,
) -> list:
    """
    对单只股票扫描历史日线信号。
    注意：这里仅负责找到日线信号日，不直接产生买卖交易。
    """

    raw_df = load_hist_cache(code)

    if raw_df.empty or len(raw_df) < 80:
        return []

    df = prepare_hist_data(raw_df)
    df = df.sort_values("日期").reset_index(drop=True)

    signals = []

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

    # 至少需要60日指标，所以从65开始
    for i in range(65, len(df) - 1):
        row = df.iloc[i]

        if row[need_cols].isna().any():
            continue

        if use_secondary_filter and not check_secondary_filters(row):
            continue

        signal_type, breakthrough, main_promotion, hit_count = get_signal_from_row(row)

        if hit_count == 0:
            continue

        signal_item = {
            "代码": code,
            "名称": name,
            "信号日期": row["日期"],
            "信号类型": signal_type,
            "突破反转策略": breakthrough,
            "主升策略": main_promotion,
            "命中策略数": hit_count,
            "信号日收盘价": row["收盘"],
            "信号日涨跌幅": row["涨跌幅"],
            "信号日量比": row["成交量"] / row["过去20日平均成交量"] if row["过去20日平均成交量"] else pd.NA,
            "信号日20日日均成交额": row["过去20日日均成交额"],
            "信号日15日涨停": int(row["近15日涨停次数"]),
        }

        signals.append(signal_item)

    return signals


def print_progress_line(text: str):
    """
    单行刷新打印。先清空当前行，避免上一次较长内容残留导致显示错乱。
    """
    print(" " * 180, end="\r")
    print(text, end="\r", flush=True)


def scan_daily_signals_parallel(files, stock_name_map, max_workers: int = 4) -> list:
    """
    并发扫描所有股票的日线信号。
    这里只读取本地 cache/hist，不访问 BaoStock，适合多线程加速。
    """
    if not files:
        return []

    max_workers = max(1, int(max_workers))
    total_files = len(files)
    all_daily_signals = []
    start_time = time.time()

    def worker(file_name: str):
        code = file_name.replace("_bs.csv", "")
        name = stock_name_map.get(code, "")
        signals = scan_daily_signals_for_stock(
            code=code,
            name=name,
            use_secondary_filter=True,
        )
        return code, name, signals

    finished_count = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(worker, file_name): file_name for file_name in files}

        for future in as_completed(future_map):
            finished_count += 1
            try:
                code, name, signals = future.result()
                if signals:
                    all_daily_signals.extend(signals)
            except Exception as e:
                file_name = future_map[future]
                code = file_name.replace("_bs.csv", "")
                name = stock_name_map.get(code, "")
                print(f"\n{code} {name} 日线信号扫描失败：{e}")

            elapsed = time.time() - start_time
            avg = elapsed / finished_count if finished_count else 0
            remain = avg * (total_files - finished_count)

            if finished_count % 20 == 0 or finished_count == total_files:
                print_progress_line(
                    f"日线信号扫描进度：{finished_count}/{total_files} | "
                    f"日线信号数：{len(all_daily_signals)} | "
                    f"并发数：{max_workers} | "
                    f"预计剩余：{remain:.1f} 秒"
                )

    print()
    return all_daily_signals


def prepare_minute_data_once(df: pd.DataFrame) -> pd.DataFrame:
    """
    分钟K线只预处理一次，并增加 trade_date 字段。
    避免每个日线信号、每根5分钟K线都重复 rolling 计算。
    """
    prepared = prepare_minute_data(df)
    if prepared is None or prepared.empty:
        return pd.DataFrame()

    prepared = prepared.copy()
    prepared["datetime"] = pd.to_datetime(prepared["datetime"], errors="coerce")
    prepared = prepared.dropna(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
    prepared["trade_date"] = prepared["datetime"].dt.date
    return prepared


def check_30m_structure_prepared(df30: pd.DataFrame) -> tuple[bool, str]:
    if df30 is None or len(df30) < 25:
        return False, "30分钟K线不足"

    latest = df30.iloc[-1]

    if pd.isna(latest[["MA5", "MA10", "VOL20"]]).any():
        return False, "30分钟指标不足"

    cond_ma = latest["收盘"] > latest["MA5"] and latest["MA5"] >= latest["MA10"]
    cond_vol = latest["成交量"] >= latest["VOL20"] * 0.8 if latest["VOL20"] > 0 else False

    if cond_ma and cond_vol:
        return True, "30分钟趋势结构有效"

    return False, "30分钟结构未确认"


def check_5m_pullback_start_prepared(df5: pd.DataFrame) -> tuple[bool, str]:
    if df5 is None or len(df5) < 30:
        return False, "5分钟K线不足"

    latest = df5.iloc[-1]
    prev = df5.iloc[-2]

    if pd.isna(latest[["MA5", "MA10", "MA20", "VOL20"]]).any():
        return False, "5分钟指标不足"

    trend_ok = latest["MA5"] > latest["MA10"] > latest["MA20"]
    pullback_ok = (
        prev["最低"] <= prev["MA10"] * 1.01
        or prev["最低"] <= prev["MA20"] * 1.01
    )
    restart_ok = latest["收盘"] > latest["MA5"] and latest["收盘"] > prev["最高"]
    volume_ok = latest["成交量"] > latest["VOL20"] * 1.10 if latest["VOL20"] > 0 else False

    if trend_ok and pullback_ok and restart_ok and volume_ok:
        return True, "5分钟回踩均线启动"

    return False, "5分钟回踩启动未确认"


def check_5m_platform_breakout_prepared(df5: pd.DataFrame) -> tuple[bool, str]:
    if df5 is None or len(df5) < 30:
        return False, "5分钟K线不足"

    latest = df5.iloc[-1]

    if pd.isna(latest[["前12根最高", "前12根最低", "前12根振幅", "VOL20"]]).any():
        return False, "5分钟平台指标不足"

    range_ok = latest["前12根振幅"] <= 0.04
    breakout_ok = latest["收盘"] > latest["前12根最高"]
    volume_ok = latest["成交量"] > latest["VOL20"] * 1.20 if latest["VOL20"] > 0 else False

    if range_ok and breakout_ok and volume_ok:
        return True, "5分钟平台突破确认"

    return False, "5分钟平台突破未确认"


def check_5m_volume_reversal_prepared(df5: pd.DataFrame) -> tuple[bool, str]:
    if df5 is None or len(df5) < 30:
        return False, "5分钟K线不足"

    latest = df5.iloc[-1]
    prev = df5.iloc[-2]

    if pd.isna(latest[["MA5", "MA10", "VOL20"]]).any():
        return False, "5分钟反包指标不足"

    intrabar_pct = latest["收盘"] / latest["开盘"] - 1 if latest["开盘"] > 0 else 0
    reverse_ok = latest["收盘"] > latest["MA5"] and latest["收盘"] > prev["最高"] and intrabar_pct >= 0.005
    volume_ok = latest["成交量"] > latest["VOL20"] * 1.30 if latest["VOL20"] > 0 else False

    if reverse_ok and volume_ok:
        return True, "5分钟放量反包确认"

    return False, "5分钟放量反包未确认"


def evaluate_minute_buy_point_fast(row: pd.Series, df5: pd.DataFrame, df30: pd.DataFrame):
    """
    使用已经预处理好的分钟K线判断B点。
    不再重复调用 prepare_minute_data，速度会明显快很多。
    """
    group = build_daily_group(row)

    structure_ok, structure_msg = check_30m_structure_prepared(df30)
    if not structure_ok:
        return False, [], group, structure_msg

    buy_points = []

    if "主升趋势类" in group:
        ok, msg = check_5m_pullback_start_prepared(df5)
        if ok:
            buy_points.append(msg)

    if "突破类" in group:
        ok, msg = check_5m_platform_breakout_prepared(df5)
        if ok:
            buy_points.append(msg)

    if "放量启动类" in group:
        ok, msg = check_5m_volume_reversal_prepared(df5)
        if ok:
            buy_points.append(msg)

    if group == "其他":
        ok, msg = check_5m_platform_breakout_prepared(df5)
        if ok:
            buy_points.append(msg)

    return bool(buy_points), buy_points, group, structure_msg


# =========================
# 分钟级B点回测
# =========================

def get_next_trade_date_from_minute(df5: pd.DataFrame, signal_date) -> str | None:
    """
    从5分钟K线里找信号日之后的下一个交易日。
    """

    if df5 is None or df5.empty:
        return None

    signal_date = pd.to_datetime(signal_date).date()

    temp = df5.copy()
    temp["trade_date"] = pd.to_datetime(temp["datetime"]).dt.date
    dates = sorted(set(temp["trade_date"].tolist()))

    for d in dates:
        if d > signal_date:
            return d.strftime("%Y-%m-%d")

    return None


def format_strategy_text(row: pd.Series) -> str:
    items = []
    for col in ["突破反转策略", "主升策略"]:
        text = str(row.get(col, "")).strip()
        if text and text.lower() != "nan":
            items.append(text)
    return "、".join(items)


def build_daily_signal_row(signal: dict) -> pd.Series:
    """
    构造 minute_strategy.evaluate_minute_buy_point 需要的日线候选行。
    """

    row = pd.Series(signal)
    row["命中策略"] = format_strategy_text(row)
    return row


def find_minute_buy_point_for_signal(
    signal: dict,
    df5: pd.DataFrame,
    df30: pd.DataFrame,
    hold_days: int = 1,
    hold_minutes: int = 60,
    exit_mode: str = "days",
):
    """
    快速版：对某一个日线信号，在下一交易日寻找第一个分钟级B点。

    默认卖出方式 exit_mode="days"：
    B点确认后下一根5分钟K线开盘买入，持有 hold_days 个交易日，
    在卖出交易日最后一根5分钟K线收盘卖出。

    也保留研究模式：
    exit_mode="fixed"：固定持有 hold_minutes 分钟；
    exit_mode="close"：持有到买入当日收盘。

    优化点：
    1. df5 / df30 在外层已经预处理，避免重复 rolling 计算。
    2. 使用 searchsorted 定位30分钟位置，避免每根5分钟K都全表布尔筛选。
    3. 只用当前之前的数据判断，避免未来函数。
    """

    if df5 is None or df5.empty or df30 is None or df30.empty:
        return None, "分钟K线为空"

    required_cols = {"datetime", "trade_date", "MA5", "MA10", "VOL20"}
    if not required_cols.issubset(set(df5.columns)):
        df5 = prepare_minute_data_once(df5)
    if not required_cols.issubset(set(df30.columns)):
        df30 = prepare_minute_data_once(df30)

    if df5.empty or df30.empty:
        return None, "分钟指标为空"

    signal_date = pd.to_datetime(signal["信号日期"]).date()
    all_trade_dates = sorted(set(df5["trade_date"].tolist()))
    target_dates = [d for d in all_trade_dates if d > signal_date]

    if not target_dates:
        return None, "无信号日后的分钟交易日"

    target_date_obj = target_dates[0]
    day_pos = np.flatnonzero(df5["trade_date"].to_numpy() == target_date_obj)

    if len(day_pos) == 0:
        return None, "目标交易日5分钟K线为空"

    daily_row = build_daily_signal_row(signal)
    df30_times = df30["datetime"].to_numpy()

    for pos in day_pos:
        current_time = df5.at[pos, "datetime"]

        # 当前时间之前的5分钟数据位置就是 pos。
        if pos + 1 < 30:
            continue

        # 30分钟K线取 <= 当前5分钟时间的最后一根。
        pos30 = int(np.searchsorted(df30_times, current_time.to_datetime64(), side="right") - 1)
        if pos30 + 1 < 25:
            continue

        df5_slice = df5.iloc[:pos + 1]
        df30_slice = df30.iloc[:pos30 + 1]

        is_hit, buy_points, daily_group, structure_msg = evaluate_minute_buy_point_fast(
            daily_row,
            df5_slice,
            df30_slice,
        )

        if not is_hit:
            continue

        # B点确认后，下一根5分钟K线开盘买入。
        buy_pos = pos + 1
        if buy_pos not in day_pos:
            return None, "B点出现在尾盘，无法下一根买入"

        buy_bar = df5.iloc[buy_pos]
        buy_time = buy_bar["datetime"]
        buy_price = buy_bar["开盘"]

        if pd.isna(buy_price) or buy_price <= 0:
            return None, "买入价异常"

        # 卖出：默认按交易日持有，避免A股非底仓T+0问题。
        if exit_mode == "days":
            buy_trade_date = buy_bar["trade_date"]
            all_trade_dates = sorted(set(df5["trade_date"].tolist()))

            if buy_trade_date not in all_trade_dates:
                return None, "买入交易日不在分钟K线日期中"

            buy_date_pos = all_trade_dates.index(buy_trade_date)
            sell_date_pos = buy_date_pos + max(1, int(hold_days))

            if sell_date_pos >= len(all_trade_dates):
                return None, "后续交易日不足，无法按持有天数卖出"

            sell_trade_date = all_trade_dates[sell_date_pos]
            sell_positions = np.flatnonzero(df5["trade_date"].to_numpy() == sell_trade_date)

            if len(sell_positions) == 0:
                return None, "卖出交易日5分钟K线为空"

            sell_pos = int(sell_positions[-1])
            hold_mode_text = f"{hold_days}个交易日"

        elif exit_mode == "close":
            sell_pos = int(day_pos[-1])
            hold_mode_text = "当日收盘"
        else:
            hold_bars = max(1, math.ceil(hold_minutes / 5))
            sell_pos = buy_pos + hold_bars - 1
            if sell_pos > int(day_pos[-1]):
                sell_pos = int(day_pos[-1])
            hold_mode_text = f"{hold_minutes}分钟"

        sell_bar = df5.iloc[sell_pos]
        sell_time = sell_bar["datetime"]
        sell_price = sell_bar["收盘"]

        if pd.isna(sell_price) or sell_price <= 0:
            return None, "卖出价异常"

        return_pct = (sell_price / buy_price - 1) * 100
        actual_hold_minutes = max(
            0,
            int((pd.to_datetime(sell_time) - pd.to_datetime(buy_time)).total_seconds() / 60),
        )
        actual_hold_calendar_days = max(
            0,
            (pd.to_datetime(sell_time).date() - pd.to_datetime(buy_time).date()).days,
        )

        result = {
            "代码": signal["代码"],
            "名称": signal.get("名称", ""),
            "信号日期": pd.to_datetime(signal["信号日期"]).strftime("%Y-%m-%d"),
            "日线策略": format_strategy_text(daily_row),
            "日线分组": build_daily_group(daily_row),
            "B点触发时间": pd.to_datetime(current_time).strftime("%Y-%m-%d %H:%M:%S"),
            "分钟B点": "、".join(buy_points),
            "30分钟结构": structure_msg,
            "买入时间": pd.to_datetime(buy_time).strftime("%Y-%m-%d %H:%M:%S"),
            "卖出时间": pd.to_datetime(sell_time).strftime("%Y-%m-%d %H:%M:%S"),
            "买入价": buy_price,
            "卖出价": sell_price,
            "持有方式": hold_mode_text,
            "设定持有天数": hold_days if exit_mode == "days" else pd.NA,
            "实际持有自然日": actual_hold_calendar_days,
            "设定持有分钟": hold_minutes if exit_mode == "fixed" else pd.NA,
            "实际持有分钟": actual_hold_minutes,
            "收益率%": return_pct,
            "是否盈利": return_pct > 0,
            "信号日收盘价": signal.get("信号日收盘价", pd.NA),
            "信号日涨跌幅": signal.get("信号日涨跌幅", pd.NA),
            "信号日量比": signal.get("信号日量比", pd.NA),
        }

        return result, "已触发分钟B点"

    return None, "目标交易日未触发分钟B点"


# =========================
# 统计函数
# =========================

def summarize_minute_backtest(
    result_df: pd.DataFrame,
    hold_days: int,
    hold_minutes: int,
    exit_mode: str,
    daily_signal_count: int,
) -> pd.DataFrame:
    if result_df is None or result_df.empty:
        return pd.DataFrame()

    total = len(result_df)
    win_count = int(result_df["是否盈利"].sum())
    loss_count = total - win_count

    win_rate = win_count / total * 100 if total else 0
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

    trigger_rate = total / daily_signal_count * 100 if daily_signal_count else 0

    summary = pd.DataFrame([
        {
            "日线信号数": daily_signal_count,
            "分钟B点数": total,
            "B点转化率%": trigger_rate,
            "持有方式": (
                f"{hold_days}个交易日"
                if exit_mode == "days"
                else ("收盘" if exit_mode == "close" else f"{hold_minutes}分钟")
            ),
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
    ])

    number_cols = summary.select_dtypes(include=["number"]).columns
    summary[number_cols] = summary[number_cols].round(2)
    return summary


def summarize_by_column(result_df: pd.DataFrame, column: str, name_col: str) -> pd.DataFrame:
    if result_df is None or result_df.empty or column not in result_df.columns:
        return pd.DataFrame()

    rows = []

    for _, row in result_df.iterrows():
        text = str(row.get(column, "")).strip()
        if not text or text.lower() == "nan":
            continue

        items = [x.strip() for x in text.split("、") if x.strip()]
        for item in items:
            new_row = row.copy()
            new_row[name_col] = item
            rows.append(new_row)

    if not rows:
        return pd.DataFrame()

    temp_df = pd.DataFrame(rows)

    summary = (
        temp_df
        .groupby(name_col)
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

    summary["胜率"] = summary["胜率"] * 100
    number_cols = summary.select_dtypes(include=["number"]).columns
    summary[number_cols] = summary[number_cols].round(2)

    summary = summary.sort_values(by=["胜率", "平均收益率"], ascending=False)
    return summary


# =========================
# 主流程
# =========================

def run_minute_backtest(
    hold_days: int = 1,
    hold_minutes: int = 60,
    exit_mode: str = "days",
    minute_days: int = 365,
    max_stocks: int = 0,
    max_daily_signals: int = 0,
    max_workers: int = 4,
):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    stock_name_map = load_stock_names_from_base_pool()

    files = [
        f for f in os.listdir(os.path.join(PROJECT_ROOT, HIST_CACHE_DIR))
        if f.endswith("_bs.csv")
    ]

    if max_stocks and max_stocks > 0:
        files = files[:max_stocks]

    print(f"发现历史日K缓存数量：{len(files)}")
    print(
        f"开始分钟级B点回测：exit_mode={exit_mode}，"
        f"hold_days={hold_days}，hold_minutes={hold_minutes}，"
        f"minute_days={minute_days}，max_workers={max_workers}"
    )

    # 第一步：并发扫描日线信号。
    # 这里只读取本地日K缓存，不访问 BaoStock，适合多线程加速。
    all_daily_signals = scan_daily_signals_parallel(
        files=files,
        stock_name_map=stock_name_map,
        max_workers=max_workers,
    )

    if not all_daily_signals:
        print("没有发现日线信号，分钟级回测结束。")
        return

    daily_signal_df = pd.DataFrame(all_daily_signals)
    daily_signal_df["代码"] = daily_signal_df["代码"].astype(str).str.zfill(6)
    daily_signal_df["信号日期"] = pd.to_datetime(daily_signal_df["信号日期"])

    # 按日期排序，避免输出混乱。
    daily_signal_df = daily_signal_df.sort_values(by=["信号日期", "代码"]).reset_index(drop=True)

    if max_daily_signals and max_daily_signals > 0:
        daily_signal_df = daily_signal_df.head(max_daily_signals).copy()

    daily_signal_count = len(daily_signal_df)
    unique_code_count = daily_signal_df["代码"].nunique()
    print(f"日线信号扫描完成，日线信号数量：{daily_signal_count}")
    print(f"涉及股票数量：{unique_code_count} 只")
    print("说明：分钟K会按股票读取一次并预处理一次，后续同一股票多个信号直接复用。")

    # 第二步：登录 BaoStock，逐个日线信号做分钟级B点回测。
    # 如果 cache/minute 已经完整，这一步主要是本地CSV读取和策略计算。
    lg = bs.login()
    if lg.error_code != "0":
        print(f"BaoStock 登录失败：{lg.error_msg}")
        return

    minute_results = []
    skipped_results = []
    minute_start_time = time.time()

    try:
        minute_cache = {}
        prepared_code_count = 0

        for idx, (_, signal_row) in enumerate(daily_signal_df.iterrows(), start=1):
            code = str(signal_row["代码"]).zfill(6)
            name = signal_row.get("名称", "")
            signal_date_text = pd.to_datetime(signal_row["信号日期"]).strftime("%Y-%m-%d")

            try:
                if code not in minute_cache:
                    prepared_code_count += 1
                    print_progress_line(
                        f"分钟K线准备：{prepared_code_count}/{unique_code_count} 只 | "
                        f"当前：{code} {name} | "
                        f"周期：5分钟 + 30分钟 | 最近 {minute_days} 天"
                    )

                    # use_cache=True：优先读取 cache/minute，避免每次回测都重新请求 BaoStock。
                    df5_raw = get_minute_data_baostock(code, frequency="5", days=minute_days, use_cache=True)
                    df30_raw = get_minute_data_baostock(code, frequency="30", days=minute_days, use_cache=True)

                    df5 = prepare_minute_data_once(df5_raw)
                    df30 = prepare_minute_data_once(df30_raw)
                    minute_cache[code] = (df5, df30)
                else:
                    df5, df30 = minute_cache[code]

                result, reason = find_minute_buy_point_for_signal(
                    signal=signal_row.to_dict(),
                    df5=df5,
                    df30=df30,
                    hold_days=hold_days,
                    hold_minutes=hold_minutes,
                    exit_mode=exit_mode,
                )

                if result is not None:
                    minute_results.append(result)
                else:
                    skipped_results.append(
                        {
                            "代码": code,
                            "名称": name,
                            "信号日期": signal_date_text,
                            "日线策略": format_strategy_text(signal_row),
                            "跳过原因": reason,
                        }
                    )

            except Exception as e:
                skipped_results.append(
                    {
                        "代码": code,
                        "名称": name,
                        "信号日期": signal_date_text,
                        "日线策略": format_strategy_text(signal_row),
                        "跳过原因": f"异常：{e}",
                    }
                )

            elapsed = time.time() - minute_start_time
            avg = elapsed / idx if idx else 0
            remain = avg * (daily_signal_count - idx)

            if idx % 10 == 0 or idx == daily_signal_count:
                print_progress_line(
                    f"分钟B点回测进度：{idx}/{daily_signal_count} | "
                    f"当前：{code} {name} | "
                    f"信号日：{signal_date_text} | "
                    f"已准备分钟K：{len(minute_cache)}/{unique_code_count} 只 | "
                    f"B点交易数：{len(minute_results)} | "
                    f"未触发：{len(skipped_results)} | "
                    f"累计耗时：{elapsed / 60:.2f} 分钟 | "
                    f"预计剩余：{remain / 60:.2f} 分钟"
                )

        print()

    finally:
        try:
            bs.logout()
        except Exception as e:
            print(f"\nBaoStock 退出异常，已忽略：{e}")

    if not minute_results:
        print("分钟级回测完成，但没有找到任何分钟B点交易。")
        if skipped_results:
            skipped_df = pd.DataFrame(skipped_results)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = os.path.join(OUTPUT_DIR, f"minute_backtest_no_trade_{timestamp}.xlsx")
            skipped_df.to_excel(output_file, sheet_name="未触发明细", index=False)
            print(f"未触发明细已导出：{output_file}")
        return

    result_df = pd.DataFrame(minute_results)
    skipped_df = pd.DataFrame(skipped_results)

    # 日期和数字格式化。
    number_cols = result_df.select_dtypes(include=["number"]).columns
    result_df[number_cols] = result_df[number_cols].round(2)

    summary_df = summarize_minute_backtest(
        result_df=result_df,
        hold_days=hold_days,
        hold_minutes=hold_minutes,
        exit_mode=exit_mode,
        daily_signal_count=daily_signal_count,
    )

    daily_strategy_summary_df = summarize_by_column(result_df, "日线策略", "单日线策略")
    minute_point_summary_df = summarize_by_column(result_df, "分钟B点", "单分钟B点")
    daily_group_summary_df = summarize_by_column(result_df, "日线分组", "单日线分组")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    hold_label = f"{hold_days}d" if exit_mode == "days" else ("close" if exit_mode == "close" else f"{hold_minutes}m")
    output_file = os.path.join(OUTPUT_DIR, f"minute_backtest_{hold_label}_{timestamp}.xlsx")

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="总体统计", index=False)
        daily_strategy_summary_df.to_excel(writer, sheet_name="按日线策略统计", index=False)
        daily_group_summary_df.to_excel(writer, sheet_name="按日线分组统计", index=False)
        minute_point_summary_df.to_excel(writer, sheet_name="按分钟B点统计", index=False)
        result_df.to_excel(writer, sheet_name="交易明细", index=False)

        if skipped_df is not None and not skipped_df.empty:
            skipped_df.to_excel(writer, sheet_name="未触发明细", index=False)

    print("\n分钟级B点回测完成。")
    print(f"日线信号数量：{daily_signal_count}")
    print(f"分钟B点交易数量：{len(result_df)}")

    if not summary_df.empty:
        print("\n分钟级总体统计：")
        print_table(
            summary_df,
            cols=[
                "日线信号数",
                "分钟B点数",
                "B点转化率%",
                "持有方式",
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
            ],
            right_cols={
                "日线信号数",
                "分钟B点数",
                "B点转化率%",
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
            },
            max_rows=5,
        )

    print(f"分钟级回测结果已导出：{output_file}")


# =========================
# 命令行入口
# =========================

def main():
    parser = argparse.ArgumentParser(description="A股分钟级B点回测工具：日线信号 + 5分钟/30分钟B点确认")

    parser.add_argument(
        "--hold-days",
        type=int,
        default=1,
        help="B点买入后持有多少个交易日。默认1，表示买入后的下一个交易日收盘卖出。",
    )

    parser.add_argument(
        "--hold-minutes",
        type=int,
        default=60,
        help="B点出现后固定持有多少分钟。仅 exit-mode=fixed 时生效。",
    )

    parser.add_argument(
        "--exit-mode",
        choices=["days", "fixed", "close"],
        default="days",
        help="卖出方式：days=持有N个交易日；fixed=固定持有分钟数；close=持有到当天收盘。默认 days。",
    )

    parser.add_argument(
        "--minute-days",
        type=int,
        default=365,
        help="获取最近多少个自然日的5分钟/30分钟K线，默认365天。",
    )

    parser.add_argument(
        "--max-stocks",
        type=int,
        default=0,
        help="测试用：只扫描前N只有日K缓存的股票，默认0表示全部。",
    )

    parser.add_argument(
        "--max-daily-signals",
        type=int,
        default=0,
        help="测试用：只回测前N个日线信号，默认0表示全部。",
    )

    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="并发扫描日线信号的线程数，默认4。建议先用4或6。",
    )

    args = parser.parse_args()

    run_minute_backtest(
        hold_days=args.hold_days,
        hold_minutes=args.hold_minutes,
        exit_mode=args.exit_mode,
        minute_days=args.minute_days,
        max_stocks=args.max_stocks,
        max_daily_signals=args.max_daily_signals,
        max_workers=args.max_workers,
    )


if __name__ == "__main__":
    main()
