# strategy.py

import os
import time
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import pandas as pd

from data_loader import get_tushare_pro

from strategies import evaluate_daily_strategies


HIST_CACHE_DIR = "cache/hist"
SIGNAL_OUTPUT_FILE = "output/a_stock_signal_selected.xlsx"
VERBOSE_KLINE_LOG = False

# 二次过滤条件
MIN_AVG_AMOUNT_20D = 50_000_000      # 过去20天日均成交额 >= 5000万
LIMIT_UP_PCT = 9.95                  # 主板涨停判断：涨幅 >= 9.95%
LIMIT_UP_WINDOW = 15                 # 过去15个交易日


def check_secondary_filters(row) -> bool:
    """
    策略命中后的统一二次过滤：

    1. 过去20天日均成交额 >= 5000万
    2. 过去15个交易日，含今日，至少出现1次涨停
    """

    return (
        row["过去20日日均成交额"] >= MIN_AVG_AMOUNT_20D
        and row["近15日涨停次数"] >= 1
    )


# 兼容别名：从 strategy.py 导入（已全面替换为 Tushare）
from strategy import get_hist_data_tushare as get_hist_data_baostock, get_ts_code as get_bs_code


def prepare_hist_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    整理 K 线数据，计算策略所需指标。
    """

    df = df.copy()

    df["日期"] = pd.to_datetime(df["日期"])
    df = df.sort_values("日期").reset_index(drop=True)

    numeric_cols = ["开盘", "收盘", "最高", "最低", "成交量", "成交额", "涨跌幅"]

    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 均线
    df["SMA5"] = df["收盘"].rolling(5).mean()
    df["SMA10"] = df["收盘"].rolling(10).mean()
    df["SMA20"] = df["收盘"].rolling(20).mean()
    df["SMA60"] = df["收盘"].rolling(60).mean()

    # 过去60个交易日最高价，不含今日
    df["过去60日最高价"] = df["最高"].shift(1).rolling(60).max()

    # 过去60个交易日最高收盘，不含今日，保留备用
    df["过去60日最高收盘"] = df["收盘"].shift(1).rolling(60).max()

    # 过去40个交易日最低价，含今日，用于判断当前是否还在底部附近
    df["过去40日最低价"] = df["最低"].rolling(40).min()

    # 过去60个交易日最低收盘，不含今日，保留备用
    df["过去60日最低收盘"] = df["收盘"].shift(1).rolling(60).min()

    # K线实体上下沿，避免影线插针误判
    df["实体上沿"] = df[["开盘", "收盘"]].max(axis=1)
    df["实体下沿"] = df[["开盘", "收盘"]].min(axis=1)

    # 过去20个交易日实体最高和实体最低，不含今日
    df["过去20日实体最高"] = df["实体上沿"].shift(1).rolling(20).max()
    df["过去20日实体最低"] = df["实体下沿"].shift(1).rolling(20).min()

    # 过去20个交易日K线实体振幅，不含今日
    df["过去20日实体振幅"] = (
        df["过去20日实体最高"] / df["过去20日实体最低"] - 1
    )

    # 过去20日平均成交量，不含今日
    df["过去20日平均成交量"] = df["成交量"].shift(1).rolling(20).mean()

    # 过去20日日均成交额，含今日
    df["过去20日日均成交额"] = df["成交额"].rolling(20).mean()

    # 过去15个交易日内涨停次数，含今日
    df["近15日涨停次数"] = (
        df["涨跌幅"] >= LIMIT_UP_PCT
    ).rolling(LIMIT_UP_WINDOW).sum()

    # 5天前的60日均线
    df["SMA60_5日前"] = df["SMA60"].shift(5)

    # =========================
    # 长庄建仓洗盘突破策略辅助字段
    # =========================
    # 建仓区间：最近 60-120 个交易日之间，避开最近20天的突破阶段。
    # 等价于取 [-120:-20] 这一段作为建仓平台。
    df["建仓区间最高价"] = df["最高"].shift(20).rolling(100).max()
    df["建仓区间最低价"] = df["最低"].shift(20).rolling(100).min()
    df["建仓区间中位价"] = (df["建仓区间最高价"] + df["建仓区间最低价"]) / 2
    df["建仓平台振幅"] = (
        df["建仓区间最高价"] - df["建仓区间最低价"]
    ) / df["建仓区间中位价"]

    # 洗盘区间：最近 180 个交易日，避开最近10天。
    # 用来判断是否经历了较长时间横盘洗盘。
    df["洗盘区间最高价"] = df["最高"].shift(10).rolling(170).max()
    df["洗盘区间最低价"] = df["最低"].shift(10).rolling(170).min()
    df["洗盘区间中位价"] = (df["洗盘区间最高价"] + df["洗盘区间最低价"]) / 2
    df["洗盘区间振幅"] = (
        df["洗盘区间最高价"] - df["洗盘区间最低价"]
    ) / df["洗盘区间中位价"]

    # 近期人气：近15日涨停次数，或者5%以上大阳次数。
    df["近15日5点大阳次数"] = (
        df["涨跌幅"] >= 5.0
    ).rolling(15).sum()

    # 近期是否突破建仓平台上沿。
    df["是否突破建仓平台"] = df["收盘"] > df["建仓区间最高价"] * 1.02
    df["近5日是否突破建仓平台"] = (
        df["是否突破建仓平台"].rolling(5).sum() >= 1
    )

    # 近期量能是否放大。
    df["近5日平均成交量"] = df["成交量"].rolling(5).mean()
    df["建仓后基准成交量"] = df["成交量"].shift(10).rolling(50).mean()

    # =========================
    # 长庄建仓洗盘突破策略：防止火箭式加速过滤字段
    # =========================
    df["近10日涨幅"] = df["收盘"] / df["收盘"].shift(10) - 1
    df["近20日涨幅"] = df["收盘"] / df["收盘"].shift(20) - 1
    df["近60日涨幅"] = df["收盘"] / df["收盘"].shift(60) - 1

    df["近10日5点大阳次数"] = (
        df["涨跌幅"] >= 5.0
    ).rolling(10).sum()

    df["近20日5点大阳次数"] = (
        df["涨跌幅"] >= 5.0
    ).rolling(20).sum()

    df["距离20日线乖离"] = df["收盘"] / df["SMA20"] - 1
    df["距离60日线乖离"] = df["收盘"] / df["SMA60"] - 1

    df["SMA20_10日前"] = df["SMA20"].shift(10)
    df["SMA60_20日前"] = df["SMA60"].shift(20)

    df["SMA20近10日涨幅"] = df["SMA20"] / df["SMA20_10日前"] - 1
    df["SMA60近20日涨幅"] = df["SMA60"] / df["SMA60_20日前"] - 1

    df["单日振幅"] = df["最高"] / df["最低"] - 1

    df["近20日高位巨震次数"] = (
        (df["单日振幅"] >= 0.12)
        | (df["涨跌幅"] <= -6.0)
    ).rolling(20).sum()

    df["近20日最高价"] = df["最高"].rolling(20).max()
    df["近20日最低价"] = df["最低"].rolling(20).min()
    df["近20日最大区间涨幅"] = df["近20日最高价"] / df["近20日最低价"] - 1

    df["近60日最高价"] = df["最高"].rolling(60).max()
    df["近60日最低价"] = df["最低"].rolling(60).min()
    df["近60日最大区间涨幅"] = df["近60日最高价"] / df["近60日最低价"] - 1

    df["是否阶梯趋势"] = (
        (df["收盘"] > df["SMA20"])
        & (df["SMA20"] > df["SMA60"])
        & (df["SMA20近10日涨幅"] > 0)
        & (df["SMA60近20日涨幅"] > 0)
        & (df["距离20日线乖离"] <= 0.28)
        & (df["距离60日线乖离"] <= 0.75)
    )

    # =========================
    # 主升策略5：大阳启动后3-5个交易日缩量回踩不破5/10日线
    # =========================
    # 这个策略用于识别：第一次涨幅 >= 8% 的放量大阳启动后，
    # 第3-5个交易日仍处于强势缩量回踩区间，且不有效跌破短均线的形态。
    df["是否8点大阳启动"] = (
        (df["涨跌幅"] >= 8.0)
        & (df["成交量"] >= df["过去20日平均成交量"] * 1.5)
        & (df["收盘"] > df["SMA5"])
        & (df["收盘"] > df["SMA10"])
    )

    # 以下字段按“最近一次启动大阳线”逐行计算。
    # 不把这些字段放进 get_required_strategy_columns，避免影响其他原有策略。
    df["近5日是否有8点大阳启动"] = False
    df["启动大阳距今天数"] = pd.NA
    df["近5日启动大阳收盘"] = pd.NA
    df["近5日启动大阳成交量"] = pd.NA
    df["启动后回撤不深"] = False
    df["回踩不破5日或10日线"] = False
    df["近5日不破10日线"] = False
    df["回调缩量"] = False
    df["当前不破10日线"] = False

    big_yang_positions = df.index[df["是否8点大阳启动"].fillna(False)].tolist()

    for pos in range(len(df)):
        # 只在当前K线之前找启动大阳，避免当天大阳线直接把自己也判成“回踩”。
        # 短线版只看启动后的第3-5个交易日。
        candidate_positions = [p for p in big_yang_positions if 3 <= pos - p <= 5]
        if not candidate_positions:
            continue

        start_pos = candidate_positions[-1]
        days_since_start = pos - start_pos

        start_row = df.iloc[start_pos]
        latest_row = df.iloc[pos]
        pullback_df = df.iloc[start_pos + 1: pos + 1].copy()

        if pullback_df.empty:
            continue

        start_close = start_row["收盘"]
        start_volume = start_row["成交量"]

        if pd.isna(start_close) or pd.isna(start_volume) or start_close <= 0 or start_volume <= 0:
            continue

        # 回踩不有效跌破10日线，允许2%误差；
        # 同时保留“5日或10日线”的字段，后续你想调成更强条件也方便。
        valid_ma10 = pullback_df["SMA10"].notna()
        no_break_ma10 = bool(
            valid_ma10.any()
            and (pullback_df.loc[valid_ma10, "最低"] >= pullback_df.loc[valid_ma10, "SMA10"] * 0.98).all()
        )

        valid_ma5_or_ma10 = pullback_df["SMA5"].notna() & pullback_df["SMA10"].notna()
        no_break_ma5_or_ma10 = bool(
            valid_ma5_or_ma10.any()
            and (
                (pullback_df.loc[valid_ma5_or_ma10, "最低"] >= pullback_df.loc[valid_ma5_or_ma10, "SMA5"] * 0.98)
                | (pullback_df.loc[valid_ma5_or_ma10, "最低"] >= pullback_df.loc[valid_ma5_or_ma10, "SMA10"] * 0.98)
            ).all()
        )

        # 回调阶段缩量：启动后到当前的平均量，不超过启动大阳量的70%。
        pullback_avg_volume = pd.to_numeric(pullback_df["成交量"], errors="coerce").mean()
        volume_shrink = bool(pd.notna(pullback_avg_volume) and pullback_avg_volume <= start_volume * 0.70)

        # 启动后不能回撤太深，防止大阳后直接走坏。
        drawdown_ok = bool(pd.notna(latest_row["收盘"]) and latest_row["收盘"] >= start_close * 0.88)

        # 当前仍在10日线附近上方，允许2%误差。
        current_no_break_ma10 = bool(
            pd.notna(latest_row["SMA10"])
            and pd.notna(latest_row["收盘"])
            and latest_row["收盘"] >= latest_row["SMA10"] * 0.98
        )

        df.iat[pos, df.columns.get_loc("近5日是否有8点大阳启动")] = True
        df.iat[pos, df.columns.get_loc("启动大阳距今天数")] = days_since_start
        df.iat[pos, df.columns.get_loc("近5日启动大阳收盘")] = start_close
        df.iat[pos, df.columns.get_loc("近5日启动大阳成交量")] = start_volume
        df.iat[pos, df.columns.get_loc("启动后回撤不深")] = drawdown_ok
        df.iat[pos, df.columns.get_loc("回踩不破5日或10日线")] = no_break_ma5_or_ma10
        df.iat[pos, df.columns.get_loc("近5日不破10日线")] = no_break_ma10
        df.iat[pos, df.columns.get_loc("回调缩量")] = volume_shrink
        df.iat[pos, df.columns.get_loc("当前不破10日线")] = current_no_break_ma10

    return df


def check_strategy_1(row) -> bool:
    """
    策略1：箱体突破
    前期横盘 + 放量创新高
    """

    return (
        row["收盘"] > row["过去60日最高价"]
        and row["成交量"] > row["过去20日平均成交量"] * 1.3
        and row["过去20日实体振幅"] <= 0.20
    )


def check_strategy_2(row) -> bool:
    """
    策略2：底部放量反转
    V型启动
    """

    distance_from_40d_low = row["收盘"] / row["过去40日最低价"] - 1

    return (
        distance_from_40d_low < 0.20
        and row["涨跌幅"] > 5
        and row["成交量"] > row["过去20日平均成交量"] * 2
    )


def check_strategy_1_main_promotion(row) -> bool:
    """
    主升策略1：股价创60天新高，伴随放量。
    """

    return (
        row["收盘"] > row["过去60日最高收盘"]
        and row["成交量"] > row["过去20日平均成交量"] * 1.5
    )


def check_strategy_2_main_promotion(row) -> bool:
    """
    主升策略2：长期低位 + 突然放量大涨。
    """

    distance_from_low = row["收盘"] / row["过去60日最低收盘"] - 1

    return (
        distance_from_low < 0.30
        and row["涨跌幅"] > 5
        and row["成交量"] > row["过去20日平均成交量"] * 2
    )


def check_strategy_3_main_promotion(row) -> bool:
    """
    主升策略3：缩量回调启动。
    """

    return (
        row["SMA5"] < row["SMA20"]
        and row["SMA60"] > row["SMA60_5日前"]
        and row["收盘"] > row["SMA5"]
        and row["成交量"] > row["过去20日平均成交量"] * 1.5
    )


def check_strategy_4_main_promotion(row) -> bool:
    """
    主升策略4：均线多头排列。
    """

    return (
        row["SMA5"] > row["SMA10"]
        and row["SMA10"] > row["SMA20"]
        and row["SMA20"] > row["SMA60"]
        and row["涨跌幅"] > 2
        and row["成交量"] > row["过去20日平均成交量"] * 1.2
    )


def get_required_strategy_columns() -> list[str]:
    """策略计算前必须存在且不能为 NaN 的指标列。"""

    return [
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


def build_signal_info(latest: pd.Series, breakthrough_strategies: list[str], main_promotion_strategies: list[str]) -> dict:
    """把策略命中结果整理成主程序、实时扫描、回测都能复用的字段。"""

    hit_strategies = breakthrough_strategies + main_promotion_strategies

    signal_types = []
    if breakthrough_strategies:
        signal_types.append("突破反转")
    if main_promotion_strategies:
        signal_types.append("主升")

    return {
        "信号类型": "、".join(signal_types),
        "突破反转策略": "、".join(breakthrough_strategies),
        "主升策略": "、".join(main_promotion_strategies),
        "突破反转策略数": len(breakthrough_strategies),
        "主升策略数": len(main_promotion_strategies),
        "命中策略数": len(hit_strategies),

        "K线日期": latest["日期"],
        "收盘价": latest["收盘"],
        "最新价": latest["收盘"],
        "今日涨跌幅": latest["涨跌幅"],
        "涨跌幅": latest["涨跌幅"],
        "今日成交量": latest["成交量"],
        "过去20日平均成交量": latest["过去20日平均成交量"],
        "量比": latest["成交量"] / latest["过去20日平均成交量"],

        "过去20日日均成交额": latest["过去20日日均成交额"],
        "过去20日日均成交额_万元": latest["过去20日日均成交额"] / 10000,
        "15日涨停": int(latest["近15日涨停次数"]),

        "过去60日最高价": latest["过去60日最高价"],
        "过去60日最高收盘": latest["过去60日最高收盘"],
        "过去60日最低收盘": latest["过去60日最低收盘"],
        "过去40日最低价": latest["过去40日最低价"],
        "距40日低点涨幅": latest["收盘"] / latest["过去40日最低价"] - 1,
        "过去20日实体振幅": latest["过去20日实体振幅"],
        "距60日低点涨幅": latest["收盘"] / latest["过去60日最低收盘"] - 1,
        "SMA5": latest["SMA5"],
        "SMA10": latest["SMA10"],
        "SMA20": latest["SMA20"],
        "SMA60": latest["SMA60"],

        # 主升-大阳缩量回踩辅助字段，方便导出后复盘。
        "启动大阳距今天数": latest.get("启动大阳距今天数", pd.NA),
        "启动大阳收盘": latest.get("近5日启动大阳收盘", pd.NA),
        "启动大阳成交量": latest.get("近5日启动大阳成交量", pd.NA),
        "回踩不破5日或10日线": latest.get("回踩不破5日或10日线", pd.NA),
        "回调缩量": latest.get("回调缩量", pd.NA),
    }


def evaluate_latest_signal(latest: pd.Series):
    """
    对已经计算好指标的最新K线执行全部已注册日线策略。

    返回：是否命中、命中策略文本、指标信息。
    这是日线扫描、盘中实时扫描、后续回测共用的核心入口。
    """

    need_cols = get_required_strategy_columns()

    if latest[need_cols].isna().any():
        return False, "", None

    signals = evaluate_daily_strategies(latest)

    if not signals:
        return False, "", None

    # 命中策略后，再执行统一二次过滤。
    if not check_secondary_filters(latest):
        return False, "", None

    breakthrough_strategies = [signal.name for signal in signals if signal.category == "突破反转"]
    main_promotion_strategies = [signal.name for signal in signals if signal.category == "主升"]
    hit_strategies = breakthrough_strategies + main_promotion_strategies

    info = build_signal_info(latest, breakthrough_strategies, main_promotion_strategies)

    return True, "、".join(hit_strategies), info


def check_main_rising_signal(code: str):
    """
    检查某只股票是否命中已注册日线策略。
    返回：是否命中、命中的策略、最新行情指标。
    """

    try:
        hist_df = get_hist_data_baostock(code)

        if hist_df is None or hist_df.empty:
            return False, "", None

        hist_df = prepare_hist_data(hist_df)

        # 数据不足65天，无法计算完整策略。
        if len(hist_df) < 65:
            return False, "", None

        latest = hist_df.iloc[-1]
        return evaluate_latest_signal(latest)

    except Exception as e:
        print(f"{code} 策略计算失败：{e}")
        return False, "", None


def scan_main_rising_stocks(stock_pool_df: pd.DataFrame) -> pd.DataFrame:
    """
    对基础股票池进行主升信号扫描。

    BaoStock 版本：
    1. 统一登录一次 BaoStock
    2. 历史K线优先读取本地 cache/hist/*_bs.csv
    3. 终端只单行刷新扫描进度，不逐只刷屏
    """

    result_list = []
    total = len(stock_pool_df)

    print("Tushare 无需登录，直接扫描...")
    scan_start_time = time.time()

    try:
        for scan_no, (_, row) in enumerate(stock_pool_df.iterrows(), start=1):
            code = str(row["代码"]).zfill(6)
            name = row["名称"]

            is_hit, hit_strategy, info = check_main_rising_signal(code)

            if is_hit:
                result = row.to_dict()
                result["命中策略"] = hit_strategy

                if info:
                    result.update(info)

                result_list.append(result)

            elapsed_seconds = time.time() - scan_start_time
            avg_seconds = elapsed_seconds / scan_no
            remaining_count = total - scan_no
            estimated_remaining_seconds = avg_seconds * remaining_count

            print(
                f"日线扫描进度：{scan_no}/{total} | "
                f"当前：{code} {name} | "
                f"命中数：{len(result_list)} | "
                f"预计剩余：{estimated_remaining_seconds / 60:.2f} 分钟",
                end="\r",
                flush=True,
            )

            # BaoStock相对稳定，轻微限速即可
            time.sleep(0.05)

        print()

    finally:
        pass  # Tushare 无需登出

    total_seconds = time.time() - scan_start_time

    print("\n第二步信号扫描完成。")
    print(f"扫描股票总数：{total}")
    print(f"命中股票数量：{len(result_list)}")
    print(f"总耗时：{total_seconds / 60:.2f} 分钟")
    if total > 0:
        print(f"平均耗时：{total_seconds / total:.2f} 秒/只")

    if not result_list:
        print("没有股票命中主升信号。")
        return pd.DataFrame()

    result_df = pd.DataFrame(result_list)

    if "量比" in result_df.columns:
        result_df = result_df.sort_values(by="量比", ascending=False)

    return result_df
